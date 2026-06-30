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

"""Tests for the dynamic-workflow engine (SP-7)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.exceptions import (
    WorkflowBudgetError,
    WorkflowContextError,
    WorkflowNotFoundError,
)
from fireflyframework_agentic.workflows import (
    AgentCall,
    Journal,
    WorkflowBudget,
    adversarial_verify,
    agent,
    current_workflow,
    loop_until_dry,
    parallel,
    phase,
    pipeline,
    run_workflow,
    workflow,
    workflow_registry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    workflow_registry.clear()
    yield
    workflow_registry.clear()


class FakeRunner:
    """Deterministic in-memory agent runner (no LLM)."""

    def __init__(self, responder=None, *, tokens: int = 1, delay: float = 0.0) -> None:
        self._responder = responder or (lambda p: f"echo:{p}")
        self._tokens = tokens
        self._delay = delay
        self.calls: list[Any] = []
        self.kwargs: list[dict] = []
        self.active = 0
        self.max_active = 0

    async def run(
        self, prompt, *, model=None, output_type=None, instructions=None, deps=None, tools=None, toolsets=None
    ) -> AgentCall:
        self.calls.append(prompt)
        self.kwargs.append(
            {"model": model, "output_type": output_type, "deps": deps, "tools": tools, "toolsets": toolsets}
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            out = self._responder(prompt)
        finally:
            self.active -= 1
        return AgentCall(output=out, tokens=self._tokens)


# -- agent() -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_runs_and_returns_output():
    runner = FakeRunner(lambda p: p.upper())

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("hello")

    assert await wf.run(None, runner=runner) == "HELLO"
    assert runner.calls == ["hello"]


@pytest.mark.asyncio
async def test_agent_records_tokens_and_count():
    captured: dict[str, int] = {}

    @workflow(register=False)
    async def wf(args, ctx):
        await agent("a")
        await agent("b")
        captured["agents"] = ctx.agents_started
        captured["tokens"] = ctx.tokens_spent

    await wf.run(None, runner=FakeRunner(tokens=5))
    assert captured == {"agents": 2, "tokens": 10}


@pytest.mark.asyncio
async def test_primitive_outside_context_raises():
    with pytest.raises(WorkflowContextError):
        await agent("hi")


@pytest.mark.asyncio
async def test_agent_forwards_tools_toolsets_and_deps():
    runner = FakeRunner()
    tools = [object()]
    toolsets = [object()]

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("hi", tools=tools, toolsets=toolsets, deps={"k": 1})

    await wf.run(None, runner=runner)
    assert runner.kwargs[0]["tools"] is tools
    assert runner.kwargs[0]["toolsets"] is toolsets
    assert runner.kwargs[0]["deps"] == {"k": 1}


# -- parallel() --------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_runs_all_and_isolates_failures():
    @workflow(register=False)
    async def wf(args, ctx):
        async def good(x):
            return await agent(x)

        async def bad():
            raise ValueError("boom")

        return await parallel([lambda: good("a"), bad, lambda: good("b")])

    res = await wf.run(None, runner=FakeRunner(lambda p: p))
    assert res == ["a", None, "b"]


@pytest.mark.asyncio
async def test_parallel_respects_concurrency_limit():
    runner = FakeRunner(lambda p: p, delay=0.02)

    @workflow(register=False)
    async def wf(args, ctx):
        return await parallel([lambda i=i: agent(str(i)) for i in range(10)])

    await wf.run(None, runner=runner, budget=WorkflowBudget(max_concurrent_agents=3, max_agents_total=100))
    assert 1 <= runner.max_active <= 3


# -- pipeline() --------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_stages_and_arity():
    @workflow(register=False)
    async def wf(args, ctx):
        async def s1(prev):  # 1-arg stage
            return prev * 2

        async def s2(prev, item, index):  # 3-arg stage
            return f"{prev}-{item}-{index}"

        return await pipeline([1, 2, 3], s1, s2)

    assert await wf.run(None, runner=FakeRunner()) == ["2-1-0", "4-2-1", "6-3-2"]


@pytest.mark.asyncio
async def test_pipeline_stage_failure_drops_item_only():
    @workflow(register=False)
    async def wf(args, ctx):
        async def s1(prev):
            if prev == 2:
                raise ValueError("nope")
            return prev + 10

        return await pipeline([1, 2, 3], s1)

    assert await wf.run(None, runner=FakeRunner()) == [11, None, 13]


# -- budgets -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_max_agents_total():
    @workflow(register=False)
    async def wf(args, ctx):
        for i in range(5):
            await agent(str(i))

    with pytest.raises(WorkflowBudgetError):
        await wf.run(None, runner=FakeRunner(), budget=WorkflowBudget(max_agents_total=3))


@pytest.mark.asyncio
async def test_budget_max_tokens():
    @workflow(register=False)
    async def wf(args, ctx):
        for i in range(10):
            await agent(str(i))

    with pytest.raises(WorkflowBudgetError):
        await wf.run(None, runner=FakeRunner(tokens=10), budget=WorkflowBudget(max_tokens=15))


# -- journal / resume --------------------------------------------------------


@pytest.mark.asyncio
async def test_journal_resume_serves_from_cache():
    runner = FakeRunner(lambda p: f"out:{p}")
    journal = Journal()

    @workflow(register=False)
    async def wf(args, ctx):
        return [await agent("one"), await agent("two")]

    assert await wf.run(None, runner=runner, journal=journal) == ["out:one", "out:two"]
    assert runner.calls == ["one", "two"]
    assert len(journal) == 2

    # Resume with the same journal: cached outputs, runner untouched.
    runner2 = FakeRunner(lambda p: "SHOULD_NOT_RUN")
    assert await wf.run(None, runner=runner2, journal=journal) == ["out:one", "out:two"]
    assert runner2.calls == []


# -- registry / decorator ----------------------------------------------------


@pytest.mark.asyncio
async def test_registry_and_run_workflow_by_name():
    @workflow(name="registered_wf")
    async def wf(args, ctx):
        return await agent(args["q"])

    assert workflow_registry.has("registered_wf")
    assert "registered_wf" in workflow_registry.list_workflows()
    out = await run_workflow("registered_wf", {"q": "hi"}, runner=FakeRunner(lambda p: p))
    assert out == "hi"


@pytest.mark.asyncio
async def test_run_workflow_unknown_name_raises():
    with pytest.raises(WorkflowNotFoundError):
        await run_workflow("does_not_exist_xyz")


@pytest.mark.asyncio
async def test_args_schema_validation():
    class Args(BaseModel):
        n: int

    @workflow(register=False, args_schema=Args)
    async def wf(args, ctx):
        return args.n * 2

    assert await wf.run({"n": 5}, runner=FakeRunner()) == 10


# -- phase / telemetry -------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_tracks_current_phase_and_emits_events():
    events: list[tuple[str, dict]] = []

    @workflow(register=False)
    async def wf(args, ctx):
        seen = []
        with phase("alpha"):
            seen.append(current_workflow().current_phase)
            await agent("x")
        seen.append(current_workflow().current_phase)
        return seen

    seen = await wf.run(None, runner=FakeRunner(), events=lambda e, d: events.append((e, d)))
    assert seen == ["alpha", None]
    names = {e for e, _ in events}
    assert {"workflow.start", "workflow.end", "phase.start", "phase.end", "agent.start", "agent.end"} <= names


# -- verify combinators ------------------------------------------------------


@pytest.mark.asyncio
async def test_adversarial_verify_refuted_does_not_survive():
    @workflow(register=False)
    async def wf(args, ctx):
        return await adversarial_verify("the sky is green", n=3)

    assert await wf.run(None, runner=FakeRunner(lambda p: "REFUTED")) is False


@pytest.mark.asyncio
async def test_adversarial_verify_supported_survives():
    @workflow(register=False)
    async def wf(args, ctx):
        return await adversarial_verify("water is wet", n=3)

    assert await wf.run(None, runner=FakeRunner(lambda p: "SUPPORTED")) is True


@pytest.mark.asyncio
async def test_loop_until_dry_dedupes_and_stops():
    rounds = {"i": 0}

    async def produce():
        rounds["i"] += 1
        if rounds["i"] == 1:
            return [1, 2]
        if rounds["i"] == 2:
            return [2, 3]  # 2 is a duplicate
        return []

    @workflow(register=False)
    async def wf(args, ctx):
        return await loop_until_dry(produce, dry_rounds=2, max_rounds=10)

    res = await wf.run(None, runner=FakeRunner())
    assert sorted(res) == [1, 2, 3]
    assert rounds["i"] == 4  # 2 productive + 2 dry rounds


# -- end-to-end --------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_research_style_workflow():
    """A realistic fan-out -> reduce-in-python -> pipeline -> synthesize flow."""

    class ResearchArgs(BaseModel):
        queries: list[str]

    @workflow(name="deep_research_demo", args_schema=ResearchArgs)
    async def deep_research(args, ctx):
        with phase("search"):
            hits = await parallel([lambda q=q: agent(f"search: {q}") for q in args.queries])
        candidates = sorted({h for h in hits if h is not None})  # reduce in plain python

        with phase("verify"):

            async def keep(prev):
                return prev

            verified = await pipeline(candidates, keep)

        with phase("synthesize"):
            return await agent(f"report over {len(verified)} items")

    runner = FakeRunner(lambda p: p.replace("search: ", "hit:"))
    out = await run_workflow(
        "deep_research_demo",
        {"queries": ["a", "b", "a"]},
        runner=runner,
        budget=WorkflowBudget(max_concurrent_agents=4),
    )
    assert out == "report over 2 items"  # "a" and "b" deduped to 2 candidates
