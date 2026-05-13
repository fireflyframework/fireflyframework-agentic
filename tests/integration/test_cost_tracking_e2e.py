# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""End-to-end cost-tracking assertions.

Drives the real ``FireflyAgent.run`` path with pydantic-ai's ``"test"``
model (deterministic token counts, no network) through the public
:class:`UsageTracker` pipeline — resolver, sink, budget gate — and
asserts the observable cost / token / latency state.

These tests complement the small unit tests that exercise each piece in
isolation by checking that the wiring holds together when an agent runs
for real.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.exceptions import BudgetExceededError
from fireflyframework_agentic.observability.budget import (
    BudgetGate,
    BudgetMode,
    BudgetRule,
    BudgetWindow,
)
from fireflyframework_agentic.observability.cost import CostContext
from fireflyframework_agentic.observability.usage import UsageTracker

_INPUT_PRICE = 1e-4
_OUTPUT_PRICE = 5e-4


def _fixed_test_price(ctx: CostContext) -> float:
    """Price the pydantic-ai 'test' model so cost > 0 in assertions."""
    return ctx.input_tokens * _INPUT_PRICE + ctx.output_tokens * _OUTPUT_PRICE


class _CapturingSink:
    """Records everything emit() receives, in order."""

    def __init__(self) -> None:
        self.records: list = []

    def emit(self, record) -> None:
        self.records.append(record)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_multi_agent_cost_tracking_e2e():
    """Three agents run; tracker accumulates cost, tokens, latency, sink."""
    tracker = UsageTracker(resolver=_fixed_test_price)
    sink = _CapturingSink()
    tracker.add_sink(sink)

    with patch(
        "fireflyframework_agentic.agents.base.default_usage_tracker",
        tracker,
    ):
        first = FireflyAgent(name="first", model="test", auto_register=False)
        second = FireflyAgent(name="second", model="test", auto_register=False)
        third = FireflyAgent(name="third", model="test", auto_register=False)

        r1 = await first.run("question 1")
        r2 = await second.run("question 2")
        r3 = await third.run("question 3")

    assert r1.output and r2.output and r3.output

    summary = tracker.get_summary()
    assert summary.record_count == 3
    assert summary.total_input_tokens > 0
    assert summary.total_output_tokens > 0
    assert summary.total_tokens == summary.total_input_tokens + summary.total_output_tokens
    assert summary.total_requests == 3

    expected_cost = sum(r.input_tokens * _INPUT_PRICE + r.output_tokens * _OUTPUT_PRICE for r in tracker.records)
    assert summary.total_cost_usd == pytest.approx(expected_cost, rel=1e-9)
    assert summary.total_cost_usd > 0

    assert set(summary.by_agent) == {"first", "second", "third"}
    for agent_name in ("first", "second", "third"):
        assert summary.by_agent[agent_name]["cost_usd"] > 0
        assert summary.by_agent[agent_name]["total_tokens"] > 0

    assert len(sink.records) == 3
    assert [r.agent for r in sink.records] == ["first", "second", "third"]
    for record in sink.records:
        assert record.model == "test"
        assert record.latency_ms >= 0
        assert record.cost_usd > 0


@pytest.mark.asyncio
async def test_hard_budget_breach_raises_during_agent_run():
    """HARD rule trips inside agent.run() and surfaces BudgetExceededError."""
    gate = BudgetGate(
        [
            BudgetRule(
                name="e2e-hard",
                limit_usd=1e-6,
                mode=BudgetMode.HARD,
                window=BudgetWindow.LIFETIME,
            )
        ]
    )
    tracker = UsageTracker(resolver=_fixed_test_price, gate=gate)

    with patch(
        "fireflyframework_agentic.agents.base.default_usage_tracker",
        tracker,
    ):
        agent = FireflyAgent(name="over-budget", model="test", auto_register=False)

        with pytest.raises(BudgetExceededError) as exc_info:
            await agent.run("anything")

    assert exc_info.value.rule_name == "e2e-hard"
    assert exc_info.value.spend_usd > exc_info.value.limit_usd
