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
inject a deterministic fake; production uses :class:`DefaultAgentRunner`, which
runs each call as an ephemeral ``pydantic_ai.Agent`` (mirroring the structured
run path in :mod:`fireflyframework_agentic.reasoning.base`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic_ai import Agent as PydanticAgent

from fireflyframework_agentic.model_utils import get_model_identifier
from fireflyframework_agentic.observability.cost_resolvers import CostContext, resolve_cost
from fireflyframework_agentic.observability.usage import resolve_run_usage

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
    ) -> AgentCall:
        """Execute one workflow agent call and return its result."""
        raise NotImplementedError


class StreamHandle:
    """Yielded by a streaming agent call. Iterate :meth:`text` for token deltas;
    after the stream context exits, read :attr:`output` / :attr:`call`."""

    def __init__(self, response: Any, model: Any) -> None:
        self._response = response
        self._model = model
        self.call: AgentCall | None = None

    async def text(self) -> AsyncIterator[str]:
        """Yield text deltas as the model produces them."""
        async for delta in self._response.stream_text(delta=True):
            yield delta

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
    ) -> AbstractAsyncContextManager[StreamHandle]:
        """Open a streaming run; the context yields a :class:`StreamHandle`."""
        ...


class DefaultAgentRunner:
    """Runs each call as a fresh ``pydantic_ai.Agent``.

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
    ) -> AgentCall:
        resolved = self._resolve(model)
        ephemeral = PydanticAgent(resolved, **self._agent_kwargs(output_type, instructions, tools, toolsets, deps))
        result = await ephemeral.run(prompt, deps=deps)
        usage = resolve_run_usage(result)
        tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage is not None else 0
        return AgentCall(output=result.output, tokens=tokens, cost_usd=price_call(resolved, usage), raw=result)

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
    ) -> AsyncIterator[StreamHandle]:
        resolved = self._resolve(model)
        ephemeral = PydanticAgent(resolved, **self._agent_kwargs(output_type, instructions, tools, toolsets, deps))
        async with ephemeral.run_stream(prompt, deps=deps) as response:
            handle = StreamHandle(response, resolved)
            yield handle
            await handle.finalize()
