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

"""The dynamic-workflow DSL primitives: ``agent``, ``parallel``, ``pipeline``,
``phase`` and ``log``.

These mirror the primitives of Claude's Workflow tool, adapted to Python and
pydantic-ai:

* ``agent(prompt, ...)`` — run one isolated sub-agent; honours the run budget,
  the concurrency gate, and the resume journal.
* ``parallel(thunks)`` — a barrier: await all thunks; a thunk that raises
  resolves to ``None`` (the call itself never raises).
* ``pipeline(items, *stages)`` — run each item through every stage independently
  with **no barrier between stages** (item A can be in stage 3 while B is in
  stage 1). A stage that raises drops that item to ``None``.
* ``phase(title)`` — group the enclosed work for telemetry.
* ``log(message)`` — emit a narrator line to the run's event handler.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from typing import TYPE_CHECKING, Any, TypeVar, overload

from fireflyframework_agentic.exceptions import (
    WorkflowBudgetError,
    WorkflowContextError,
    WorkflowError,
    WorkflowInterrupt,
)
from fireflyframework_agentic.workflows.context import current_workflow
from fireflyframework_agentic.workflows.runner import AgentCall, StreamingAgentRunner

if TYPE_CHECKING:
    from fireflyframework_agentic.agents.base import FireflyAgent

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

# Structural / kill-switch / control-flow signals must abort the run, not be
# swallowed to ``None`` by a parallel branch or a pipeline stage.
_NEVER_SWALLOW = (WorkflowBudgetError, WorkflowContextError, WorkflowInterrupt)


@overload
async def agent(
    prompt: Any,
    *,
    label: str | None = ...,
    model: Any | None = ...,
    output_type: type[_T],
    instructions: str | None = ...,
    deps: Any = ...,
    tools: Any | None = ...,
    toolsets: Any | None = ...,
    using: FireflyAgent | str | None = ...,
) -> _T: ...


@overload
async def agent(
    prompt: Any,
    *,
    label: str | None = ...,
    model: Any | None = ...,
    output_type: None = ...,
    instructions: str | None = ...,
    deps: Any = ...,
    tools: Any | None = ...,
    toolsets: Any | None = ...,
    using: FireflyAgent | str | None = ...,
) -> Any: ...


async def agent(
    prompt: Any,
    *,
    label: str | None = None,
    model: Any | None = None,
    output_type: Any | None = None,
    instructions: str | None = None,
    deps: Any = None,
    tools: Any | None = None,
    toolsets: Any | None = None,
    using: FireflyAgent | str | None = None,
) -> Any:
    """Run one isolated sub-agent and return its output.

    The call's sequence number is assigned synchronously (before any ``await``)
    so resume keys stay deterministic in launch order. On resume, a cached call
    returns instantly and consumes neither an agent slot nor budget.

    Args:
        prompt: The user prompt for the sub-agent.
        label: Display/telemetry label (defaults to a prompt prefix).
        model: Per-call model override (else the runner's default).
        output_type: A pydantic model / type to constrain structured output.
        instructions: Per-call system instructions.
        deps: Dependency object passed to the underlying agent (also sets its deps_type).
        tools: Tool callables / ``pydantic_ai.Tool`` objects for this sub-agent.
        toolsets: Toolsets for this sub-agent (e.g. ``ToolKit.as_toolset()`` or an MCP server).
        using: Target a specific configured agent for this call — a ``FireflyAgent``
            instance or a registry name. Honoured only when the run uses a
            :class:`FireflyAgentRunner`; enables multi-model sub-agents and
            per-task cost optimisation. Ignored shape: a plain runner rejects it.

    Returns:
        The sub-agent's ``output`` (a ``str`` or a validated ``output_type``).
    """
    ctx = current_workflow()
    seq = ctx.next_call_seq()
    if ctx.journal.has(seq):
        logger.debug("workflow '%s' resume: agent call #%d served from journal", ctx.name, seq)
        return ctx.journal.get(seq)

    ctx.reserve_agent()
    display = label or (prompt[:40] if isinstance(prompt, str) else f"agent#{seq}")
    ctx.emit("agent.start", {"label": display, "phase": ctx.current_phase, "seq": seq})
    # Forward ``using`` only when set, so runners/fakes without the parameter
    # (the 6 test fakes, SmartRoutingRunner) keep their byte-identical call shape.
    extra: dict[str, Any] = {"using": using} if using is not None else {}
    async with ctx.semaphore:
        call = await ctx.runner.run(
            prompt,
            model=model,
            output_type=output_type,
            instructions=instructions,
            deps=deps,
            tools=tools,
            toolsets=toolsets,
            **extra,
        )
    ctx.record_tokens(call.tokens)
    ctx.record_cost_usd(call.cost_usd)
    ctx.journal.record(seq, call.output)
    ctx.emit(
        "agent.end",
        {
            "label": display,
            "phase": ctx.current_phase,
            "seq": seq,
            "tokens": call.tokens,
            "cost_usd": call.cost_usd,
        },
    )
    return call.output


async def human(prompt: str, *, label: str | None = None) -> Any:
    """Pause the workflow for human input (human-in-the-loop).

    On first reach this raises :class:`WorkflowInterrupt` carrying ``prompt``. The
    caller obtains the answer, calls ``interrupt.provide(answer)``, and re-runs the
    workflow with the **same journal** — this ``human()`` call then returns the
    recorded answer and execution continues past it. Like ``agent()``, the call is
    sequence-keyed, so resume is deterministic.

    Example::

        try:
            result = await wf.run(args, journal=journal)
        except WorkflowInterrupt as it:
            it.provide(input(it.prompt))          # collect the answer however you like
            result = await wf.run(args, journal=journal)   # resume
    """
    ctx = current_workflow()
    seq = ctx.next_call_seq()
    if ctx.journal.has(seq):
        return ctx.journal.get(seq)
    ctx.emit("human.pause", {"prompt": prompt, "seq": seq, "label": label, "phase": ctx.current_phase})
    raise WorkflowInterrupt(prompt, seq=seq, journal=ctx.journal)


class _CachedStream:
    """Stream handle for a journal-cached call: yields the full output once."""

    def __init__(self, output: Any) -> None:
        self._output = output
        self.call = AgentCall(output=output)

    async def text(self) -> AsyncIterator[str]:
        yield str(self._output)

    @property
    def output(self) -> Any:
        return self._output


@contextlib.asynccontextmanager
async def stream(
    prompt: Any,
    *,
    label: str | None = None,
    model: Any | None = None,
    output_type: Any | None = None,
    instructions: str | None = None,
    deps: Any = None,
    tools: Any | None = None,
    toolsets: Any | None = None,
    using: FireflyAgent | str | None = None,
) -> AsyncIterator[Any]:
    """Stream one sub-agent's output token-by-token, as a context manager.

    Iterate ``handle.text()`` for deltas; after the block, ``handle.output`` holds
    the full output. Honours the budget, concurrency gate, journal (a resumed call
    yields its cached output once) and cost accounting, exactly like ``agent()``.
    Requires the run's runner to support streaming (``DefaultAgentRunner`` does).

    Example::

        async with stream("write a cited report", model=args.model) as s:
            async for delta in s.text():
                print(delta, end="", flush=True)
        report = s.output
    """
    ctx = current_workflow()
    seq = ctx.next_call_seq()
    if ctx.journal.has(seq):
        yield _CachedStream(ctx.journal.get(seq))
        return

    runner = ctx.runner
    if not isinstance(runner, StreamingAgentRunner):
        raise WorkflowError(f"the active runner {type(runner).__name__} does not support streaming")

    ctx.reserve_agent()
    display = label or (prompt[:40] if isinstance(prompt, str) else f"stream#{seq}")
    ctx.emit("agent.start", {"label": display, "phase": ctx.current_phase, "seq": seq, "stream": True})
    extra: dict[str, Any] = {"using": using} if using is not None else {}
    async with ctx.semaphore:
        async with runner.run_stream(
            prompt,
            model=model,
            output_type=output_type,
            instructions=instructions,
            deps=deps,
            tools=tools,
            toolsets=toolsets,
            **extra,
        ) as handle:
            yield handle
        call = handle.call if handle.call is not None else AgentCall(output=handle.output)
    ctx.record_tokens(call.tokens)
    ctx.record_cost_usd(call.cost_usd)
    ctx.journal.record(seq, call.output)
    ctx.emit(
        "agent.end",
        {
            "label": display,
            "phase": ctx.current_phase,
            "seq": seq,
            "tokens": call.tokens,
            "cost_usd": call.cost_usd,
            "stream": True,
        },
    )


async def parallel(thunks: Iterable[Callable[[], Awaitable[Any]]]) -> list[Any]:
    """Run zero-arg async ``thunks`` concurrently and return their results.

    This is a barrier — it awaits every thunk before returning. A thunk that
    raises resolves to ``None`` (the call never propagates the exception), so
    callers can ``[r for r in results if r is not None]``.
    """

    async def _safe(thunk: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await thunk()
        except _NEVER_SWALLOW:
            raise
        except Exception:  # noqa: BLE001 - isolate one branch's failure
            logger.debug("workflow parallel thunk failed", exc_info=True)
            return None

    return await asyncio.gather(*[_safe(t) for t in thunks])


async def map_agents(items: Iterable[Any], fn: Callable[[Any], Awaitable[Any]], *, strict: bool = False) -> list[Any]:
    """Run ``fn(item)`` for every item concurrently — sugar over :func:`parallel`.

    Removes the late-binding ``lambda x=x:`` footgun. By default a failing item
    resolves to ``None`` (like :func:`parallel`); ``strict=True`` fails fast on the
    first exception.

    Example::

        summaries = await map_agents(urls, lambda u: agent(f"summarize {u}"))
    """
    materialised = list(items)
    if strict:
        return list(await asyncio.gather(*[fn(x) for x in materialised]))
    return await parallel([(lambda x=x: fn(x)) for x in materialised])


def _stage_arity(stage: Callable[..., Any]) -> int:
    try:
        params = inspect.signature(stage).parameters.values()
    except (TypeError, ValueError):
        return 1
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params):
        return 3
    positional = [
        p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional)


async def _call_stage(stage: Callable[..., Awaitable[Any]], prev: Any, item: Any, index: int) -> Any:
    args = (prev, item, index)[: max(1, min(3, _stage_arity(stage)))]
    return await stage(*args)


async def pipeline(items: Iterable[Any], *stages: Callable[..., Awaitable[Any]]) -> list[Any]:
    """Run every item through all ``stages`` independently (no inter-stage barrier).

    Each stage callback receives ``(prev_result, original_item, index)`` — extra
    positional parameters are supplied as the stage declares them. A stage that
    raises drops that item to ``None`` and skips its remaining stages. Wall-clock
    is the slowest single-item chain, not the sum of per-stage barriers.
    """
    materialised = list(items)

    async def _chain(item: Any, index: int) -> Any:
        prev = item
        for stage in stages:
            try:
                prev = await _call_stage(stage, prev, item, index)
            except _NEVER_SWALLOW:
                raise
            except Exception:  # noqa: BLE001 - drop just this item
                logger.debug("workflow pipeline stage failed for item %d", index, exc_info=True)
                return None
        return prev

    return await asyncio.gather(*[_chain(item, i) for i, item in enumerate(materialised)])


@contextlib.contextmanager
def phase(title: str) -> Iterator[None]:
    """Group the enclosed work under ``title`` for telemetry."""
    ctx = current_workflow()
    ctx.push_phase(title)
    try:
        yield
    finally:
        ctx.pop_phase()


def log(message: str) -> None:
    """Emit a narrator line to the run's event handler (and the logger)."""
    ctx = current_workflow()
    ctx.emit("log", {"message": message, "phase": ctx.current_phase})
    logger.info("[workflow:%s] %s", ctx.name, message)
