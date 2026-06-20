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

"""Tests for smart routing, model cascade, judge panel, cost/wall budgets (no LLM)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from fireflyframework_agentic.exceptions import WorkflowBudgetError
from fireflyframework_agentic.workflows import (
    AgentCall,
    ComplexityHeuristicStrategy,
    SmartRoutingRunner,
    WorkflowBudget,
    agent,
    cascade,
    judge_panel,
    map_agents,
    parallel,
    workflow,
    workflow_registry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    workflow_registry.clear()
    yield
    workflow_registry.clear()


class CostFakeRunner:
    """Fake runner that records the model used and can return cost / fail per model."""

    def __init__(self, responder=None, *, tokens: int = 1, cost: float = 0.0, fail_models=()) -> None:
        self._responder = responder or (lambda prompt, model: f"{model}:{prompt}")
        self._tokens = tokens
        self._cost = cost
        self._fail = set(fail_models)
        self.models: list[Any] = []

    async def run(
        self, prompt, *, model=None, output_type=None, instructions=None, deps=None, tools=None, toolsets=None
    ):
        self.models.append(model)
        if model in self._fail:
            raise RuntimeError(f"transient error on {model}")
        return AgentCall(output=self._responder(prompt, model), tokens=self._tokens, cost_usd=self._cost)


# -- #0 budget propagation through parallel ----------------------------------


@pytest.mark.asyncio
async def test_budget_error_propagates_through_parallel():
    @workflow(register=False)
    async def wf(args, ctx):
        return await parallel([(lambda i=i: agent(str(i))) for i in range(6)])

    with pytest.raises(WorkflowBudgetError):
        await wf.run(None, runner=CostFakeRunner(), budget=WorkflowBudget(max_agents_total=2))


# -- #4 USD cost budget + wall-clock -----------------------------------------


@pytest.mark.asyncio
async def test_cost_budget_raises():
    @workflow(register=False)
    async def wf(args, ctx):
        for i in range(5):
            await agent(str(i))

    runner = CostFakeRunner(cost=0.003)
    with pytest.raises(WorkflowBudgetError):
        await wf.run(None, runner=runner, budget=WorkflowBudget(max_cost_usd=0.005))


@pytest.mark.asyncio
async def test_cost_is_recorded_on_context():
    captured = {}

    @workflow(register=False)
    async def wf(args, ctx):
        await agent("a")
        await agent("b")
        captured["cost"] = ctx.cost_spent_usd

    await wf.run(None, runner=CostFakeRunner(cost=0.01))
    assert abs(captured["cost"] - 0.02) < 1e-9


@pytest.mark.asyncio
async def test_wall_clock_budget_raises():
    @workflow(register=False)
    async def wf(args, ctx):
        await asyncio.sleep(0.5)
        return "done"

    with pytest.raises(WorkflowBudgetError):
        await wf.run(None, runner=CostFakeRunner(), budget=WorkflowBudget(max_wall_seconds=0.05))


# -- #1 SmartRoutingRunner ---------------------------------------------------


@pytest.mark.asyncio
async def test_complexity_heuristic_routes_short_to_cheap_long_to_expensive():
    base = CostFakeRunner()
    runner = SmartRoutingRunner(
        ["cheap", "mid", "expensive"],
        strategy=ComplexityHeuristicStrategy(thresholds=(20, 60)),
        base_runner=base,
    )

    @workflow(register=False)
    async def wf(args, ctx):
        await agent("hi")  # short -> tier 0
        await agent("x" * 80)  # long -> tier 2

    await wf.run(None, runner=runner)
    assert base.models == ["cheap", "expensive"]


@pytest.mark.asyncio
async def test_smart_routing_escalates_on_error():
    base = CostFakeRunner(fail_models=["cheap"])
    runner = SmartRoutingRunner(["cheap", "expensive"], base_runner=base)

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("hello")

    out = await wf.run(None, runner=runner)
    assert base.models == ["cheap", "expensive"]  # tried cheap, escalated
    assert out == "expensive:hello"


@pytest.mark.asyncio
async def test_explicit_model_overrides_router():
    base = CostFakeRunner()
    runner = SmartRoutingRunner(["cheap", "expensive"], base_runner=base)

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("hello", model="forced")

    await wf.run(None, runner=runner)
    assert base.models == ["forced"]


# -- #2 cascade --------------------------------------------------------------


@pytest.mark.asyncio
async def test_cascade_accepts_cheap_when_confident():
    base = CostFakeRunner()

    @workflow(register=False)
    async def wf(args, ctx):
        return await cascade("q", tiers=["cheap", "expensive"], confidence=lambda out: _const(0.9), threshold=0.7)

    res = await wf.run(None, runner=base)
    assert res.tier == 0 and res.model == "cheap" and base.models == ["cheap"]


@pytest.mark.asyncio
async def test_cascade_escalates_when_unconfident():
    base = CostFakeRunner()
    scores = iter([0.2, 0.95])

    @workflow(register=False)
    async def wf(args, ctx):
        return await cascade("q", tiers=["cheap", "expensive"], confidence=lambda out: _next(scores), threshold=0.7)

    res = await wf.run(None, runner=base)
    assert res.tier == 1 and res.model == "expensive"
    assert base.models == ["cheap", "expensive"]


# -- #5 judge_panel ----------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_panel_majority():
    # two judges say YES, one says NO -> support 2/3 -> survives at threshold 0.5
    def responder(prompt, model):
        return "NO" if model == "skeptic" else "YES"

    @workflow(register=False)
    async def wf(args, ctx):
        return await judge_panel("the sky is blue", judges=["a", "b", "skeptic"], threshold=0.5)

    verdict = await wf.run(None, runner=CostFakeRunner(responder))
    assert verdict.survived is True
    assert abs(verdict.support - 2 / 3) < 1e-9
    assert len(verdict.votes) == 3


# -- #3 map_agents -----------------------------------------------------------


@pytest.mark.asyncio
async def test_map_agents():
    @workflow(register=False)
    async def wf(args, ctx):
        return await map_agents(["a", "b", "c"], lambda x: agent(x))

    out = await wf.run(None, runner=CostFakeRunner(lambda p, m: p.upper()))
    assert out == ["A", "B", "C"]


async def _const(v):
    return v


async def _next(it):
    return next(it)
