# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for the state-based pipeline API (issue #147 phase 1).

Covers the canonical agentic-pipeline shape:
    * Typed shared state via a Pydantic model.
    * Reducers via ``Annotated[T, reducer_fn]``.
    * Function references as node ids.
    * Auto-entry detection.
    * ``.branch(source, router)`` with and without an explicit mapping.
    * Checkpoint + resume after failure (the software-factory scenario).
    * ``start_at`` to jump into the middle of a pipeline with explicit state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline import (
    FileCheckpointer,
    PipelineBuilder,
    StatePipeline,
    append,
)


class AgentState(BaseModel):
    messages: Annotated[list[str], append] = []
    intent: str | None = None
    answer: str | None = None


# --- linear pipeline -------------------------------------------------------


@pytest.mark.asyncio
async def test_linear_pipeline_runs_all_nodes():
    """Three nodes in sequence; each writes to state; final state has all updates."""

    async def step_a(state: AgentState) -> dict:
        return {"messages": "a"}

    async def step_b(state: AgentState) -> dict:
        return {"messages": "b"}

    async def step_c(state: AgentState) -> dict:
        return {"messages": "c", "answer": "done"}

    pipeline = (
        PipelineBuilder("linear", state=AgentState)
        .add_node(step_a)
        .add_node(step_b)
        .add_node(step_c)
        .chain(step_a, step_b, step_c)
        .build()
    )
    assert isinstance(pipeline, StatePipeline)
    result = await pipeline.invoke(AgentState(messages=["start"]))
    assert result.success
    assert result.completed_nodes == ["step_a", "step_b", "step_c"]
    assert result.state.messages == ["start", "a", "b", "c"]
    assert result.state.answer == "done"


@pytest.mark.asyncio
async def test_returning_none_or_empty_dict_keeps_state():
    """A node that returns None or {} should leave state unchanged."""

    async def noop(state: AgentState) -> None:
        return None

    async def writer(state: AgentState) -> dict:
        return {"answer": "ok"}

    pipeline = PipelineBuilder("noop", state=AgentState).add_node(noop).add_node(writer).chain(noop, writer).build()
    result = await pipeline.invoke(AgentState(messages=["x"]))
    assert result.success
    assert result.state.messages == ["x"]  # unchanged by noop
    assert result.state.answer == "ok"


# --- branching -------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_without_mapping_router_returns_node_id():
    """Router returns the target node id directly; no mapping needed."""

    async def classify(state: AgentState) -> dict:
        return {"intent": "complaint" if "refund" in " ".join(state.messages) else "general"}

    async def answer(state: AgentState) -> dict:
        return {"answer": "Here is your answer."}

    async def escalate(state: AgentState) -> dict:
        return {"answer": "Escalated."}

    def route(state: AgentState) -> str:
        return "escalate" if state.intent == "complaint" else "answer"

    pipeline = (
        PipelineBuilder("branch", state=AgentState)
        .add_node(classify)
        .add_node(answer)
        .add_node(escalate)
        .branch(classify, route)
        .build()
    )
    complaint = await pipeline.invoke(AgentState(messages=["I want a refund"]))
    assert complaint.state.answer == "Escalated."
    assert complaint.completed_nodes == ["classify", "escalate"]

    general = await pipeline.invoke(AgentState(messages=["hello"]))
    assert general.state.answer == "Here is your answer."
    assert general.completed_nodes == ["classify", "answer"]


@pytest.mark.asyncio
async def test_branch_with_explicit_mapping_uses_abstract_labels():
    async def start(state: AgentState) -> dict:
        return {"intent": "x"}

    async def left(state: AgentState) -> dict:
        return {"answer": "L"}

    async def right(state: AgentState) -> dict:
        return {"answer": "R"}

    def route(state: AgentState) -> str:
        return "go_left" if state.intent == "x" else "go_right"

    pipeline = (
        PipelineBuilder("mapped", state=AgentState)
        .add_node(start)
        .add_node(left)
        .add_node(right)
        .branch(start, route, {"go_left": left, "go_right": right})
        .build()
    )
    result = await pipeline.invoke(AgentState())
    assert result.state.answer == "L"


@pytest.mark.asyncio
async def test_router_returning_unknown_label_raises():
    async def start(state: AgentState) -> dict:
        return {}

    async def target(state: AgentState) -> dict:
        return {"answer": "ok"}

    def bad_router(state: AgentState) -> str:
        return "nonexistent_node"

    pipeline = (
        PipelineBuilder("bad", state=AgentState).add_node(start).add_node(target).branch(start, bad_router).build()
    )
    result = await pipeline.invoke(AgentState())
    assert not result.success
    assert "nonexistent_node" in (result.error or "")


# --- reducers --------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_reducer_accumulates_across_nodes():
    """The default test schema uses append on messages; each node adds one."""

    async def a(state: AgentState) -> dict:
        return {"messages": "from_a"}

    async def b(state: AgentState) -> dict:
        return {"messages": "from_b"}

    pipeline = PipelineBuilder("acc", state=AgentState).add_node(a).add_node(b).chain(a, b).build()
    result = await pipeline.invoke(AgentState(messages=["initial"]))
    assert result.state.messages == ["initial", "from_a", "from_b"]


@pytest.mark.asyncio
async def test_replace_reducer_is_default_for_unannotated_field():
    async def a(state: AgentState) -> dict:
        return {"answer": "first"}

    async def b(state: AgentState) -> dict:
        return {"answer": "second"}

    pipeline = PipelineBuilder("rep", state=AgentState).add_node(a).add_node(b).chain(a, b).build()
    result = await pipeline.invoke(AgentState())
    assert result.state.answer == "second"


# --- checkpoint + resume ---------------------------------------------------


class BuildState(BaseModel):
    """Software-factory scenario state."""

    requirements: str
    spec: str | None = None
    code: str | None = None
    deploy_url: str | None = None
    evaluation: str | None = None


@pytest.mark.asyncio
async def test_checkpoint_resume_after_failure(tmp_path: Path):
    """Run a 4-step agent factory; deployer fails the first time; resume succeeds."""

    failed_once = {"deploy": False}

    async def architect(state: BuildState) -> dict:
        return {"spec": "architecture spec for: " + state.requirements}

    async def python_dev(state: BuildState) -> dict:
        return {"code": f"# code implementing {state.spec}"}

    async def deployer(state: BuildState) -> dict:
        if not failed_once["deploy"]:
            failed_once["deploy"] = True
            raise RuntimeError("network glitch")
        return {"deploy_url": "https://app.example.com"}

    async def evaluator(state: BuildState) -> dict:
        return {"evaluation": f"PASS: {state.deploy_url}"}

    ckpt = FileCheckpointer(tmp_path / "ckpt")
    pipeline = (
        PipelineBuilder("software-factory", state=BuildState, checkpointer=ckpt)
        .add_node(architect)
        .add_node(python_dev)
        .add_node(deployer)
        .add_node(evaluator)
        .chain(architect, python_dev, deployer, evaluator)
        .build()
    )

    # First run: deployer fails.
    first = await pipeline.invoke(BuildState(requirements="user-mgmt service"))
    assert not first.success
    assert first.failed_node == "deployer"
    assert first.completed_nodes == ["architect", "python_dev"]
    assert first.state.code is not None  # python_dev did persist

    # Resume: should skip architect/python_dev, retry deployer, then evaluator.
    second = await pipeline.invoke(run_id=first.run_id)
    assert second.success
    assert second.completed_nodes == ["architect", "python_dev", "deployer", "evaluator"]
    assert second.state.evaluation == "PASS: https://app.example.com"


@pytest.mark.asyncio
async def test_start_at_jumps_to_middle_with_explicit_state(tmp_path: Path):
    """Caller supplies state + start_at to run only from deployer onwards."""

    async def architect(state: BuildState) -> dict:
        raise AssertionError("should not run")

    async def python_dev(state: BuildState) -> dict:
        raise AssertionError("should not run")

    async def deployer(state: BuildState) -> dict:
        return {"deploy_url": "https://app.example.com"}

    async def evaluator(state: BuildState) -> dict:
        return {"evaluation": "PASS"}

    pipeline = (
        PipelineBuilder("factory", state=BuildState)
        .add_node(architect)
        .add_node(python_dev)
        .add_node(deployer)
        .add_node(evaluator)
        .chain(architect, python_dev, deployer, evaluator)
        .build()
    )
    pre_built = BuildState(requirements="x", spec="precomputed", code="precomputed code")
    result = await pipeline.invoke(pre_built, start_at=deployer)
    assert result.success
    assert result.completed_nodes == ["deployer", "evaluator"]
    assert result.state.deploy_url == "https://app.example.com"


@pytest.mark.asyncio
async def test_resume_without_checkpointer_raises():
    async def a(state: AgentState) -> dict:
        return {}

    pipeline = PipelineBuilder("nockpt", state=AgentState).add_node(a).build()
    with pytest.raises(PipelineError, match="no checkpointer"):
        await pipeline.invoke(run_id="anything")


# --- validation / errors ---------------------------------------------------


@pytest.mark.asyncio
async def test_default_entry_is_first_node_added():
    """When no inbound edges disambiguate, the first add_node call is the entry."""

    async def first_one(state: AgentState) -> dict:
        return {"answer": "first ran"}

    async def second_one(state: AgentState) -> dict:
        raise AssertionError("not reached without an edge")

    pipeline = PipelineBuilder("order", state=AgentState).add_node(first_one).add_node(second_one).build()
    result = await pipeline.invoke(AgentState())
    assert result.completed_nodes == ["first_one"]
    assert result.state.answer == "first ran"


def test_function_ref_without_state_raises():
    async def step(state):
        return {}

    with pytest.raises(PipelineError, match="state=..."):
        PipelineBuilder("nostate").add_node(step)


def test_branch_without_state_raises():
    builder = PipelineBuilder("nostate")
    with pytest.raises(PipelineError, match="state=..."):
        builder.branch("x", lambda s: "y")


# --- agent-shape adapter ---------------------------------------------------


@pytest.mark.asyncio
async def test_agent_like_object_adapts_via_run_method():
    """Object exposing async run(state) is accepted as a node."""

    class MockAgent:
        __name__ = "mock_agent"  # required for function-ref node id derivation

        async def run(self, state: AgentState) -> dict:
            return {"answer": "from mock agent"}

    pipeline = PipelineBuilder("agent", state=AgentState).add_node("mock_agent", MockAgent()).build()
    result = await pipeline.invoke(AgentState())
    assert result.success
    assert result.state.answer == "from mock agent"
