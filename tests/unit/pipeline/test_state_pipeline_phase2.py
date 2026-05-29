# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Phase-2 tests: cycles + recursion_limit, Send fan-out, Mermaid export,
soft-deprecation of BranchStep / FanOutStep.
"""

from __future__ import annotations

import json
import warnings
from typing import Annotated

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.pipeline import (
    DAG,
    BranchStep,
    DAGEdge,
    DAGNode,
    FailureStrategy,
    FanOutStep,
    PipelineBuilder,
    Send,
    extend,
)
from fireflyframework_agentic.pipeline.steps import CallableStep


class LoopState(BaseModel):
    counter: int = 0
    log: Annotated[list[str], extend] = []


# --- cycles + recursion_limit ----------------------------------------------


@pytest.mark.asyncio
async def test_simple_cycle_with_exit_router():
    """A node loops back to itself N times, then a router exits to END."""

    async def step(state: LoopState) -> dict:
        return {"counter": state.counter + 1, "log": [f"step#{state.counter + 1}"]}

    async def done(state: LoopState) -> dict:
        return {"log": ["done"]}

    def route(state: LoopState) -> str:
        return "done" if state.counter >= 3 else "step"

    pipeline = PipelineBuilder("loop", state=LoopState).add_node(step).add_node(done).branch(step, route).build()
    result = await pipeline.invoke(LoopState())
    assert result.success
    assert result.state.counter == 3
    assert "done" in result.state.log
    # 3 step visits + 1 done = 4 entries before done's own log entry.
    assert result.completed_nodes == ["step", "step", "step", "done"]


@pytest.mark.asyncio
async def test_recursion_limit_aborts_infinite_loop():
    """A router that never exits triggers the recursion_limit safety net."""

    async def step(state: LoopState) -> dict:
        return {"counter": state.counter + 1}

    def never_exits(state: LoopState) -> str:
        return "step"

    pipeline = (
        PipelineBuilder("inf", state=LoopState, recursion_limit=5).add_node(step).branch(step, never_exits).build()
    )
    result = await pipeline.invoke(LoopState())
    assert not result.success
    assert "Recursion limit" in (result.error or "")
    assert result.failed_node == "step"
    # The node ran exactly recursion_limit times before the guard fired.
    assert result.state.counter == 5


# --- Send fan-out -----------------------------------------------------------


class FanOutState(BaseModel):
    items: list[str] = []
    results: Annotated[list[str], extend] = []
    item: str | None = None  # filled per-Send via payload


@pytest.mark.asyncio
async def test_send_fans_out_to_multiple_workers_and_merges_results():
    """Router returns list[Send]; workers run concurrently; reducer merges."""

    async def planner(state: FanOutState) -> dict:
        return {}  # passthrough; could populate items if not preset

    async def worker(state: FanOutState) -> dict:
        # Each worker sees its own copy of state with the Send payload applied.
        assert state.item is not None
        return {"results": [f"processed:{state.item}"]}

    async def collect(state: FanOutState) -> dict:
        return {"results": ["collected"]}

    def dispatch(state: FanOutState) -> list[Send]:
        return [Send("worker", {"item": x}) for x in state.items]

    pipeline = (
        PipelineBuilder("mapreduce", state=FanOutState)
        .add_node(planner)
        .add_node(worker)
        .add_node(collect)
        .add_edge(worker, collect)
        .branch(planner, dispatch)
        .build()
    )
    result = await pipeline.invoke(FanOutState(items=["a", "b", "c"]))
    assert result.success
    processed = sorted(r for r in result.state.results if r.startswith("processed:"))
    assert processed == ["processed:a", "processed:b", "processed:c"]
    assert "collected" in result.state.results
    # Each worker counts as a completed node visit; planner once, three workers, then collect.
    assert result.completed_nodes.count("worker") == 3
    assert result.completed_nodes[-1] == "collect"


@pytest.mark.asyncio
async def test_send_to_unknown_target_fails_cleanly():
    async def planner(state: FanOutState) -> dict:
        return {}

    async def worker(state: FanOutState) -> dict:
        return {}

    def bad_dispatch(state: FanOutState) -> list[Send]:
        return [Send("ghost", {})]

    pipeline = (
        PipelineBuilder("bad", state=FanOutState)
        .add_node(planner)
        .add_node(worker)
        .branch(planner, bad_dispatch)
        .build()
    )
    result = await pipeline.invoke(FanOutState())
    assert not result.success
    assert "ghost" in (result.error or "")


# --- Mermaid + JSON export --------------------------------------------------


def test_dag_to_mermaid_renders_topology():
    dag = DAG(name="example")
    dag.add_node(DAGNode(node_id="a", step=CallableStep(_noop_async)))
    dag.add_node(DAGNode(node_id="b", step=CallableStep(_noop_async)))
    dag.add_edge(DAGEdge(source="a", target="b"))
    out = dag.to_mermaid()
    assert out.startswith("flowchart TD")
    assert "a[a]" in out
    assert "b[b]" in out
    assert "a --> b" in out


def test_dag_to_json_round_trips_via_pydantic():
    dag = DAG(name="example")
    dag.add_node(DAGNode(node_id="a", step=CallableStep(_noop_async)))
    dag.add_node(DAGNode(node_id="b", step=CallableStep(_noop_async), failure_strategy=FailureStrategy.FAIL_PIPELINE))
    dag.add_edge(DAGEdge(source="a", target="b", input_key="payload"))
    doc = json.loads(dag.to_json())
    assert doc["name"] == "example"
    assert doc["nodes"] == ["a", "b"]
    assert doc["edges"] == [{"source": "a", "target": "b", "output_key": "output", "input_key": "payload"}]


def test_state_pipeline_to_mermaid_labels_branch_edges():
    async def start(state: LoopState) -> dict:
        return {}

    async def left(state: LoopState) -> dict:
        return {}

    async def right(state: LoopState) -> dict:
        return {}

    def route(state: LoopState) -> str:
        return "left_path"

    pipeline = (
        PipelineBuilder("branched", state=LoopState)
        .add_node(start)
        .add_node(left)
        .add_node(right)
        .branch(start, route, {"left_path": left, "right_path": right})
        .build()
    )
    mermaid = pipeline.to_mermaid()
    assert "start -->|left_path| left" in mermaid
    assert "start -->|right_path| right" in mermaid


# --- soft-deprecation ------------------------------------------------------


def test_branch_step_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        BranchStep(router=lambda _: "x")
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert any("branch(" in str(w.message) for w in caught)


def test_fan_out_step_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FanOutStep(split_fn=lambda x: [x])
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert any("Send" in str(w.message) for w in caught)


# --- helpers ---------------------------------------------------------------


async def _noop_async(ctx, inputs):
    return None
