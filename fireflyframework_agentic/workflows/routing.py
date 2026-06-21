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

"""Smart model routing for workflow agents.

A :class:`SmartRoutingRunner` is a drop-in :class:`AgentRunner` that picks the
cheapest *capable* model per call from an ordered list of tiers (cheap →
expensive), via a pluggable :class:`ModelSelectionStrategy`, and escalates up the
ladder on transient errors. Use it by passing ``runner=SmartRoutingRunner([...])``
to a workflow run, then call ``agent("...")`` with **no** explicit ``model=`` — the
runner chooses one. An explicit ``model=`` on a given ``agent()`` call always wins.

Every routing decision is emitted as a structured event (``route.select`` /
``route.escalate``) so cheap-model quality regressions are observable, not silent.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from fireflyframework_agentic.model_utils import get_model_identifier
from fireflyframework_agentic.observability.cost_resolvers import CostContext, resolve_cost
from fireflyframework_agentic.workflows.context import current_workflow
from fireflyframework_agentic.workflows.runner import AgentCall, AgentRunner, FireflyAgentRunner

logger = logging.getLogger(__name__)


def price_model(model: Any, *, input_tokens: int, output_tokens: int) -> float | None:
    """Return the USD price for ``model`` at a token shape, or ``None`` if unknown."""
    try:
        return resolve_cost(
            CostContext(
                model=get_model_identifier(model),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )
    except Exception:  # noqa: BLE001 - pricing is best-effort
        logger.debug("price_model failed for %r", model, exc_info=True)
        return None


def _estimate_input_tokens(prompt: Any) -> int:
    text = prompt if isinstance(prompt, str) else str(prompt)
    return max(1, len(text) // 4)  # ~4 chars/token


@runtime_checkable
class ModelSelectionStrategy(Protocol):
    """Picks the starting tier index (0 = cheapest) for a prompt."""

    async def select(self, prompt: Any, tiers: list[Any]) -> int:
        """Return the tier index to start at for ``prompt``."""
        raise NotImplementedError


class ComplexityHeuristicStrategy:
    """Training-free router: pick a tier from prompt length and difficulty cues.

    No extra LLM call. Short prompts route to the cheapest tier; long prompts or
    ones containing reasoning markers escalate. ``thresholds`` are character-length
    cutoffs (one per tier boundary).
    """

    def __init__(
        self,
        *,
        thresholds: tuple[int, ...] = (320, 1400),
        hard_markers: tuple[str, ...] = (
            "prove",
            "derive",
            "step by step",
            "reason",
            "analyse",
            "analyze",
            "explain why",
            "debug",
            "refactor",
            "optimize",
        ),
    ) -> None:
        self._thresholds = thresholds
        self._markers = tuple(m.lower() for m in hard_markers)

    async def select(self, prompt: Any, tiers: list[Any]) -> int:
        text = (prompt if isinstance(prompt, str) else str(prompt)).lower()
        idx = sum(1 for t in self._thresholds if len(text) >= t)
        if any(m in text for m in self._markers):
            idx += 1
        return idx


class CostFloorStrategy:
    """Always start at the cheapest tier (by genai-prices); escalation is left to
    the runner's fallback ladder. Token cost is estimated from the actual prompt
    length, so the choice is prompt-length aware."""

    def __init__(self, *, sample_output_tokens: int = 400) -> None:
        self._out = sample_output_tokens

    async def select(self, prompt: Any, tiers: list[Any]) -> int:
        est_in = _estimate_input_tokens(prompt)
        priced = [(price_model(m, input_tokens=est_in, output_tokens=self._out), i) for i, m in enumerate(tiers)]
        known = [(p, i) for p, i in priced if p is not None]
        if not known:
            logger.warning("CostFloorStrategy: no tier could be priced; defaulting to tier 0")
            return 0
        return min(known)[1]


class SmartRoutingRunner:
    """An :class:`AgentRunner` that selects a model per call and escalates on error.

    Args:
        tiers: model ids ordered cheap → expensive.
        strategy: how to pick the starting tier (default
            :class:`ComplexityHeuristicStrategy`).
        fallback: when ``True`` (default), a transient error escalates to the next
            tier up the ladder.
        base_runner: the runner that executes the chosen model (default
            :class:`FireflyAgentRunner`; pass :class:`DefaultAgentRunner` for the
            lightweight bare-pydantic-ai path).
    """

    def __init__(
        self,
        tiers: list[Any],
        *,
        strategy: ModelSelectionStrategy | None = None,
        fallback: bool = True,
        base_runner: AgentRunner | None = None,
    ) -> None:
        if not tiers:
            raise ValueError("SmartRoutingRunner requires at least one tier")
        self._tiers = list(tiers)
        self._strategy = strategy or ComplexityHeuristicStrategy()
        self._fallback = fallback
        self._base = base_runner or FireflyAgentRunner()

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
        kw: dict[str, Any] = {
            "output_type": output_type,
            "instructions": instructions,
            "deps": deps,
            "tools": tools,
            "toolsets": toolsets,
        }
        if using is not None:  # forward only when set, for base runners without the param
            kw["using"] = using
        if model is not None:  # an explicit per-call model always wins
            return await self._base.run(prompt, model=model, **kw)

        start = await self._strategy.select(prompt, self._tiers)
        start = max(0, min(start, len(self._tiers) - 1))
        _emit(
            "route.select",
            {
                "tier": start,
                "model": get_model_identifier(self._tiers[start]),
                "strategy": type(self._strategy).__name__,
            },
        )
        for j in range(start, len(self._tiers)):
            try:
                return await self._base.run(prompt, model=self._tiers[j], **kw)
            except Exception as exc:  # noqa: BLE001 - escalate or re-raise
                if not self._fallback or j == len(self._tiers) - 1:
                    raise
                _emit(
                    "route.escalate",
                    {
                        "from": get_model_identifier(self._tiers[j]),
                        "to": get_model_identifier(self._tiers[j + 1]),
                        "error": type(exc).__name__,
                    },
                )
        raise AssertionError("SmartRoutingRunner: tier loop neither returned nor raised")  # pragma: no cover


def _emit(event: str, data: dict[str, Any]) -> None:
    try:
        current_workflow().emit(event, data)
    except Exception:  # noqa: BLE001 - emit is best-effort and may run outside a ctx
        logger.debug("routing emit failed for %r", event, exc_info=True)
