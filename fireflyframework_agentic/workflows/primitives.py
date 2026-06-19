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
from collections.abc import Awaitable, Callable, Iterable, Iterator
from typing import Any

from fireflyframework_agentic.workflows.context import current_workflow

logger = logging.getLogger(__name__)


async def agent(
    prompt: Any,
    *,
    label: str | None = None,
    model: Any | None = None,
    output_type: Any | None = None,
    instructions: str | None = None,
    deps: Any = None,
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
        deps: Dependency object passed to the underlying agent.

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
    async with ctx.semaphore:
        call = await ctx.runner.run(prompt, model=model, output_type=output_type, instructions=instructions, deps=deps)
    ctx.record_tokens(call.tokens)
    ctx.journal.record(seq, call.output)
    ctx.emit(
        "agent.end",
        {"label": display, "phase": ctx.current_phase, "seq": seq, "tokens": call.tokens},
    )
    return call.output


async def parallel(thunks: Iterable[Callable[[], Awaitable[Any]]]) -> list[Any]:
    """Run zero-arg async ``thunks`` concurrently and return their results.

    This is a barrier — it awaits every thunk before returning. A thunk that
    raises resolves to ``None`` (the call never propagates the exception), so
    callers can ``[r for r in results if r is not None]``.
    """

    async def _safe(thunk: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await thunk()
        except Exception:  # noqa: BLE001 - isolate one branch's failure
            logger.debug("workflow parallel thunk failed", exc_info=True)
            return None

    return await asyncio.gather(*[_safe(t) for t in thunks])


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
