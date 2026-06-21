# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pluggable agent runner for the workflow ``agent()`` primitive.

The runner is the single seam between the orchestration DSL and the LLM. Tests
inject a deterministic fake. The default is :class:`FireflyAgentRunner`, which
runs each call through a :class:`FireflyAgent` so sub-agents inherit the full
framework stack; :class:`DefaultAgentRunner` is the lightweight alternative that
runs each call as a bare ``pydantic_ai.Agent``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.exceptions import UserError

from fireflyframework_agentic.model_utils import get_model_identifier
from fireflyframework_agentic.observability.cost_resolvers import CostContext, UnknownModelCostError, resolve_cost
from fireflyframework_agentic.observability.usage import resolve_run_usage

if TYPE_CHECKING:
    from fireflyframework_agentic.agents.base import FireflyAgent
    from fireflyframework_agentic.agents.registry import AgentRegistry

logger = logging.getLogger(__name__)


def price_call(model: Any, usage: Any) -> float:
    """Best-effort USD cost for one model call, via the genai-prices cost stack.

    Returns ``0.0`` for an unknown model or when usage is unavailable, so cost
    accounting degrades gracefully rather than failing a run.
    """
    if usage is None:
        return 0.0
    try:
        cost = resolve_cost(
            CostContext(
                model=get_model_identifier(model),
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                cache_creation_tokens=int(getattr(usage, "cache_write_tokens", 0) or 0),
                cache_read_tokens=int(getattr(usage, "cache_read_tokens", 0) or 0),
            )
        )
    except UnknownModelCostError:
        # Honour cost_strict on the workflow path: an unpriceable model must
        # fail closed rather than be silently billed as $0.
        raise
    except Exception:  # noqa: BLE001 - cost is best-effort; never break a run
        logger.debug("workflow cost resolution failed", exc_info=True)
        return 0.0
    return float(cost) if cost else 0.0


@dataclass(slots=True)
class AgentCall:
    """The outcome of a single workflow ``agent()`` invocation.

    Attributes:
        output: The agent's output (a ``str`` or the validated ``output_type``).
        tokens: Output/total tokens consumed (fed into the run's token budget).
        raw: The underlying result object, when one exists (else ``None``).
    """

    output: Any
    tokens: int = 0
    cost_usd: float = 0.0
    raw: Any = None


@runtime_checkable
class AgentRunner(Protocol):
    """Strategy that executes one workflow agent call."""

    async def run(
        self,
        prompt: Any,
        *,
        model: Any | None = None,
        output_type: Any | None = None,
        instructions: str | None = None,
        deps: Any = None,
        tools: Any | None = None,
        toolsets: Any | None = None,
        using: Any = None,
    ) -> AgentCall:
        """Execute one workflow agent call and return its result.

        ``using`` lets a call target a specific configured agent (honoured by
        :class:`FireflyAgentRunner`); runners that do not understand it ignore
        or reject it. The DSL only forwards ``using`` when it is not ``None``,
        so a runner without the parameter is never passed it.
        """
        raise NotImplementedError


class StreamHandle:
    """Yielded by a streaming agent call. Iterate :meth:`text` for token deltas;
    after the stream context exits, read :attr:`output` / :attr:`call`."""

    def __init__(self, response: Any, model: Any) -> None:
        self._response = response
        self._model = model
        self.call: AgentCall | None = None

    async def text(self) -> AsyncIterator[str]:
        """Yield text deltas as the model produces them.

        For a text run this yields incremental token deltas. For a structured
        (non-text) run, pydantic-ai's ``stream_text`` is unavailable, so this
        falls back to emitting stringified partial-object snapshots from
        ``stream_output`` (whole snapshots, not deltas) rather than crashing.
        """
        try:
            async for delta in self._response.stream_text(delta=True):
                yield delta
        except UserError:
            async for obj in self._response.stream_output():
                yield str(obj)

    @property
    def output(self) -> Any:
        """The full output (available after the stream context exits)."""
        return self.call.output if self.call is not None else None

    async def finalize(self) -> None:
        usage = resolve_run_usage(self._response)
        out = await self._response.get_output()
        tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage is not None else 0
        self.call = AgentCall(output=out, tokens=tokens, cost_usd=price_call(self._model, usage), raw=self._response)


@runtime_checkable
class StreamingAgentRunner(Protocol):
    """An :class:`AgentRunner` that can also stream a call's output."""

    def run_stream(
        self,
        prompt: Any,
        *,
        model: Any | None = None,
        output_type: Any | None = None,
        instructions: str | None = None,
        deps: Any = None,
        tools: Any | None = None,
        toolsets: Any | None = None,
        using: Any = None,
    ) -> AbstractAsyncContextManager[StreamHandle]:
        """Open a streaming run; the context yields a :class:`StreamHandle`."""
        ...


class DefaultAgentRunner:
    """Runs each call as a fresh bare ``pydantic_ai.Agent`` (lightweight path).

    The framework default is :class:`FireflyAgentRunner`; choose this one
    explicitly (``runner=DefaultAgentRunner()``) when you want the minimal,
    zero-coupling path with none of the FireflyAgent middleware/observability —
    e.g. as a fast ``base_runner`` for routing, or in tests.

    Each call gets an isolated agent with no shared message history (mirroring
    the context isolation of Claude's workflow sub-agents); context is passed
    only via the prompt/deps. Requires a resolvable model — passed per call to
    ``agent(...)`` or as this runner's ``default_model``.
    """

    def __init__(self, *, default_model: Any | None = None) -> None:
        self._default_model = default_model

    async def run(
        self,
        prompt: Any,
        *,
        model: Any | None = None,
        output_type: Any | None = None,
        instructions: str | None = None,
        deps: Any = None,
        tools: Any | None = None,
        toolsets: Any | None = None,
        using: Any = None,
    ) -> AgentCall:
        self._reject_using(using)
        resolved = self._resolve(model)
        ephemeral = PydanticAgent(resolved, **self._agent_kwargs(output_type, instructions, tools, toolsets, deps))
        result = await ephemeral.run(prompt, deps=deps)
        usage = resolve_run_usage(result)
        tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage is not None else 0
        return AgentCall(output=result.output, tokens=tokens, cost_usd=price_call(resolved, usage), raw=result)

    @staticmethod
    def _reject_using(using: Any) -> None:
        if using is not None:
            raise ValueError(
                "agent(..., using=) targets a configured FireflyAgent, but the active runner is "
                "DefaultAgentRunner. Run the workflow with runner=FireflyAgentRunner(...) to honour using=."
            )

    def _resolve(self, model: Any | None) -> Any:
        resolved = model or self._default_model
        if resolved is None:
            raise ValueError(
                "DefaultAgentRunner requires a model; pass model= to agent() or default_model= to the runner"
            )
        return resolved

    @staticmethod
    def _agent_kwargs(output_type: Any, instructions: Any, tools: Any, toolsets: Any, deps: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if output_type is not None:
            kwargs["output_type"] = output_type
        if instructions is not None:
            kwargs["instructions"] = instructions
        if tools:
            kwargs["tools"] = list(tools)
        if toolsets:
            kwargs["toolsets"] = list(toolsets)
        if deps is not None:
            # pydantic-ai validates deps against deps_type; infer it from the value.
            kwargs["deps_type"] = type(deps)
        return kwargs

    @asynccontextmanager
    async def run_stream(
        self,
        prompt: Any,
        *,
        model: Any | None = None,
        output_type: Any | None = None,
        instructions: str | None = None,
        deps: Any = None,
        tools: Any | None = None,
        toolsets: Any | None = None,
        using: Any = None,
    ) -> AsyncIterator[StreamHandle]:
        self._reject_using(using)
        resolved = self._resolve(model)
        ephemeral = PydanticAgent(resolved, **self._agent_kwargs(output_type, instructions, tools, toolsets, deps))
        async with ephemeral.run_stream(prompt, deps=deps) as response:
            handle = StreamHandle(response, resolved)
            yield handle
            await handle.finalize()


class FireflyAgentRunner:
    """Runs each workflow call through a :class:`FireflyAgent`.

    This is the runner that aligns Dynamic Workflows with the rest of the
    framework, and is **the default**: every sub-agent inherits the full
    :class:`FireflyAgent` stack — the middleware chain (logging, prompt/output
    guards, cost guard, caching, observability, explainability, validation,
    retry), the 429 rate-limit retry loop, the global usage tracker / budget
    gate, and model fallback — instead of a bare ``pydantic_ai.Agent``. For the
    lightweight, zero-coupling path, pass ``runner=DefaultAgentRunner()``
    explicitly.

    The ``agent`` source decides how the per-call agent is obtained:

    * ``None`` (default) — build a fresh, **isolated** ephemeral ``FireflyAgent``
      per call from ``default_model`` (or the call's ``model=``). Mirrors
      ``DefaultAgentRunner``'s no-shared-history isolation, but with middleware.
    * a :class:`FireflyAgent` instance — **reuse** it for every call (fastest;
      keeps its configured model/tools/middleware). Per-call ``output_type`` /
      ``instructions`` / ``toolsets`` / ``model`` are applied as run overrides.
    * a registry name (``str``) — resolve it from the agent registry per call.
    * a zero-arg factory — call it to build a fresh agent per call.

    A workflow can also target a specific agent for one call via
    ``agent(prompt, using=<FireflyAgent | name>)`` (multi-model sub-agents and
    per-task cost optimisation) — ``using`` overrides this runner's source for
    that call only.

    Isolation & cost: ephemeral/factory agents are built with
    ``auto_register=False`` and ``memory=None`` and never receive a
    ``conversation_id``, so they share no history and never touch the registry.
    Cost/tokens are read from the call's own ``RunUsage`` (per-run
    :class:`WorkflowBudget` ledger); ``FireflyAgent`` records the same call once
    to the *global* usage tracker — two disjoint ledgers, each written once.

    .. note::
       Per-call ``tools=`` cannot be applied to a *reused* configured agent
       (pydantic-ai has no per-call ``tools`` parameter) — it is only honoured
       on the ephemeral (``None``) path. Configure tools on the agent or pass
       ``toolsets=`` instead. A reused agent that carries a stateful
       ``ResultCache`` / memory intentionally opts into shared state across
       calls; use the ephemeral or factory form for strict per-call isolation.
    """

    def __init__(
        self,
        agent: FireflyAgent | Callable[[], FireflyAgent] | str | None = None,
        *,
        registry: AgentRegistry | None = None,
        default_model: Any | None = None,
    ) -> None:
        self._source = agent
        self._registry = registry
        self._default_model = default_model

    def _get_registry(self) -> AgentRegistry:
        if self._registry is not None:
            return self._registry
        # Lazy: importing agents at module load would drag the whole agents
        # package into every workflows import; only FireflyAgentRunner needs it.
        from fireflyframework_agentic.agents.registry import agent_registry

        return agent_registry

    def _prepare(
        self,
        *,
        model: Any,
        output_type: Any,
        instructions: Any,
        tools: Any,
        toolsets: Any,
        deps: Any,
        using: Any,
    ) -> tuple[FireflyAgent, dict[str, Any], Any]:
        """Resolve the target agent and the per-call ``run`` overrides.

        Returns ``(agent, run_kwargs, resolved_model)``. ``run_kwargs`` is empty
        for the ephemeral path (everything is baked into construction).
        """
        # Lazy (see _get_registry): keep the workflows package import agents-free.
        from fireflyframework_agentic.agents.base import FireflyAgent

        source = using if using is not None else self._source
        resolved_model = model if model is not None else self._default_model

        if source is None:
            # Ephemeral, fully isolated agent — bake every per-call option in.
            if resolved_model is None:
                raise ValueError(
                    "FireflyAgentRunner requires a model on the ephemeral path; pass model= to agent(), "
                    "default_model= to the runner, or a configured agent / using=."
                )
            ephemeral = FireflyAgent(
                "workflow-subagent",
                model=resolved_model,
                output_type=output_type if output_type is not None else str,
                instructions=instructions if instructions is not None else (),
                tools=list(tools) if tools else (),
                toolsets=list(toolsets) if toolsets else (),
                deps_type=type(deps) if deps is not None else type(None),
                auto_register=False,
                memory=None,
            )
            return ephemeral, {}, resolved_model

        fa: FireflyAgent
        if isinstance(source, str):
            fa = self._get_registry().get(source)
        elif isinstance(source, FireflyAgent):
            fa = source
        elif callable(source):
            fa = cast("FireflyAgent", source())
        else:
            raise TypeError(
                "FireflyAgentRunner agent / using must be a FireflyAgent, a registry name, a zero-arg "
                f"factory, or None; got {type(source).__name__}"
            )

        if tools:
            raise ValueError(
                "per-call tools= cannot be applied to a configured FireflyAgent (pydantic-ai has no "
                "per-call tools parameter); configure tools on the agent or pass toolsets= instead."
            )
        run_kwargs: dict[str, Any] = {}
        if output_type is not None:
            run_kwargs["output_type"] = output_type
        if instructions is not None:
            run_kwargs["instructions"] = instructions
        if toolsets:
            run_kwargs["toolsets"] = list(toolsets)
        if model is not None:
            run_kwargs["model"] = model
        return fa, run_kwargs, (model if model is not None else fa.model_identifier)

    async def run(
        self,
        prompt: Any,
        *,
        model: Any | None = None,
        output_type: Any | None = None,
        instructions: str | None = None,
        deps: Any = None,
        tools: Any | None = None,
        toolsets: Any | None = None,
        using: Any = None,
    ) -> AgentCall:
        fa, run_kwargs, resolved_model = self._prepare(
            model=model,
            output_type=output_type,
            instructions=instructions,
            tools=tools,
            toolsets=toolsets,
            deps=deps,
            using=using,
        )
        result = await fa.run(prompt, deps=deps, **run_kwargs)
        usage = resolve_run_usage(result)
        tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage is not None else 0
        return AgentCall(output=result.output, tokens=tokens, cost_usd=price_call(resolved_model, usage), raw=result)

    @asynccontextmanager
    async def run_stream(
        self,
        prompt: Any,
        *,
        model: Any | None = None,
        output_type: Any | None = None,
        instructions: str | None = None,
        deps: Any = None,
        tools: Any | None = None,
        toolsets: Any | None = None,
        using: Any = None,
    ) -> AsyncIterator[StreamHandle]:
        fa, run_kwargs, resolved_model = self._prepare(
            model=model,
            output_type=output_type,
            instructions=instructions,
            tools=tools,
            toolsets=toolsets,
            deps=deps,
            using=using,
        )
        # FireflyAgent.run_stream is an async factory returning a context manager
        # (the double-await idiom); buffered mode yields the raw pydantic-ai
        # stream that StreamHandle.text()/finalize() already target.
        stream_cm = await fa.run_stream(prompt, deps=deps, streaming_mode="buffered", **run_kwargs)
        async with stream_cm as raw_stream:
            handle = StreamHandle(raw_stream, resolved_model)
            yield handle
            await handle.finalize()
