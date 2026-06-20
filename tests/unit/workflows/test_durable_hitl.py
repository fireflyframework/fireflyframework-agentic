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

"""Tests for sub-workflows, durable JournalBackend resume, and human() HITL (no LLM)."""

from __future__ import annotations

from typing import Any

import pytest

from fireflyframework_agentic.exceptions import WorkflowBudgetError, WorkflowInterrupt
from fireflyframework_agentic.workflows import (
    AgentCall,
    FileJournalBackend,
    Journal,
    WorkflowBudget,
    agent,
    human,
    parallel,
    subworkflow,
    workflow,
    workflow_registry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    workflow_registry.clear()
    yield
    workflow_registry.clear()


class FakeRunner:
    def __init__(self, responder=None) -> None:
        self._responder = responder or (lambda p: f"echo:{p}")
        self.calls: list[Any] = []

    async def run(
        self, prompt, *, model=None, output_type=None, instructions=None, deps=None, tools=None, toolsets=None
    ):
        self.calls.append(prompt)
        return AgentCall(output=self._responder(prompt), tokens=1)


# -- sub-workflows -----------------------------------------------------------


@pytest.mark.asyncio
async def test_subworkflow_inherits_context():
    @workflow(register=False)
    async def child(args, ctx):
        return await agent("child")

    captured = {}

    @workflow(register=False)
    async def parent(args, ctx):
        a = await agent("parent")
        b = await subworkflow(child)
        captured["agents"] = ctx.agents_started  # both calls counted on the parent
        return [a, b]

    runner = FakeRunner()
    out = await parent.run(None, runner=runner)
    assert out == ["echo:parent", "echo:child"]
    assert runner.calls == ["parent", "child"]
    assert captured["agents"] == 2


@pytest.mark.asyncio
async def test_subworkflow_shares_parent_budget():
    @workflow(register=False)
    async def child(args, ctx):
        return await agent("c")

    @workflow(register=False)
    async def parent(args, ctx):
        await agent("p")
        await subworkflow(child)  # trips the inherited budget

    with pytest.raises(WorkflowBudgetError):
        await parent.run(None, runner=FakeRunner(), budget=WorkflowBudget(max_agents_total=1))


@pytest.mark.asyncio
async def test_subworkflow_by_name():
    @workflow(name="child_wf")
    async def child(args, ctx):
        return await agent("named-child")

    @workflow(register=False)
    async def parent(args, ctx):
        return await subworkflow("child_wf")

    assert await parent.run(None, runner=FakeRunner()) == "echo:named-child"


# -- durable JournalBackend --------------------------------------------------


def test_file_journal_backend_roundtrip(tmp_path):
    backend = FileJournalBackend(tmp_path)
    assert backend.load("missing") == {}
    backend.save("k1", {0: "a", 1: {"nested": [1, 2]}})
    assert backend.load("k1") == {0: "a", 1: {"nested": [1, 2]}}


@pytest.mark.asyncio
async def test_durable_resume_across_processes(tmp_path):
    backend = FileJournalBackend(tmp_path)

    @workflow(register=False)
    async def wf(args, ctx):
        return [await agent("one"), await agent("two")]

    runner = FakeRunner(lambda p: f"out:{p}")
    journal = Journal(backend=backend, run_key="job-1")
    assert await wf.run(None, runner=runner, journal=journal) == ["out:one", "out:two"]
    assert runner.calls == ["one", "two"]

    # Simulate a fresh process: a new journal loads the persisted state from disk.
    runner2 = FakeRunner(lambda p: "SHOULD_NOT_RUN")
    resumed = Journal(backend=backend, run_key="job-1")
    assert len(resumed) == 2
    assert await wf.run(None, runner=runner2, journal=resumed) == ["out:one", "out:two"]
    assert runner2.calls == []  # everything served from the durable journal


# -- human-in-the-loop -------------------------------------------------------


@pytest.mark.asyncio
async def test_human_interrupt_then_resume():
    @workflow(register=False)
    async def wf(args, ctx):
        name = await human("What is your name?")
        return f"hello {name}"

    journal = Journal()
    with pytest.raises(WorkflowInterrupt) as ei:
        await wf.run(None, runner=FakeRunner(), journal=journal)
    assert "name" in ei.value.prompt

    ei.value.provide("Ada")  # record the human's answer
    result = await wf.run(None, runner=FakeRunner(), journal=journal)  # resume
    assert result == "hello Ada"


@pytest.mark.asyncio
async def test_human_interrupt_propagates_through_parallel():
    @workflow(register=False)
    async def wf(args, ctx):
        return await parallel([lambda: human("approve?")])

    with pytest.raises(WorkflowInterrupt):
        await wf.run(None, runner=FakeRunner(), journal=Journal())
