"""Layer 5 of the unification (#245): Pause and Send in PipelineEngine.

PipelineEngine recognizes the same control sentinels that StatePipeline
uses today:

- A node returning :class:`Pause` halts the pipeline cleanly; the run
  resumes with ``engine.run(run_id=..., approve_pause=True)``.
- A node returning :class:`Send` or ``list[Send]`` triggers a parallel
  fan-out where each Send's target runs concurrently with the supplied
  payload merged into a per-worker state copy. Reducers merge worker
  outputs back into shared state.

Both sentinels work in the acyclic and cyclic schedulers.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.checkpoint import FileCheckpointer
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode

# Pause and Send live in pipeline.engine now (moved from state_pipeline in
# this layer); the public re-export from pipeline/__init__.py is unchanged.
from fireflyframework_agentic.pipeline.engine import Pause, PipelineEngine, Send
from fireflyframework_agentic.pipeline.reducers import extend

# ---- shared state ---------------------------------------------------------


class _LoopState(BaseModel):
    items: Annotated[list[str], extend] = []
    approved: bool = False
    deployed_to: str = ""


# ---- Pause ----------------------------------------------------------------


def _step_pause(reason: str = "human gate"):
    class _Step:
        async def execute(self, ctx, inputs):
            return Pause(reason=reason)

    return _Step()


def _step_record(label: str):
    class _Step:
        async def execute(self, ctx, inputs):
            return {"items": [label]}

    return _Step()


async def test_pause_halts_pipeline_and_records_state(tmp_path):
    """A node returning Pause halts: result.paused=True, success=False, checkpoint with paused=True."""
    build = _step_record("build")
    gate = _step_pause("awaiting approval")
    deploy = _step_record("deploy")
    dag = DAG("hitl")
    dag.add_node(DAGNode(node_id="build", step=build))
    dag.add_node(DAGNode(node_id="gate", step=gate))
    dag.add_node(DAGNode(node_id="deploy", step=deploy))
    dag.add_edge(DAGEdge(source="build", target="gate"))
    dag.add_edge(DAGEdge(source="gate", target="deploy"))
    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, state_schema=_LoopState, checkpointer=cp)
    result = await engine.run(inputs="")
    assert result.paused is True
    assert result.paused_node == "gate"
    assert result.pause_reason == "awaiting approval"
    assert not result.success
    # State so far: only 'build' contributed.
    assert result.final_state.items == ["build"]
    # Checkpoint reflects the paused state.
    record = cp.load_latest("hitl", result.run_id)
    assert record is not None
    assert record.paused is True
    assert record.pause_reason == "awaiting approval"


async def test_resume_paused_run_requires_approve_pause(tmp_path):
    build = _step_record("build")
    gate = _step_pause("awaiting approval")
    dag = DAG("needs-approve")
    dag.add_node(DAGNode(node_id="build", step=build))
    dag.add_node(DAGNode(node_id="gate", step=gate))
    dag.add_edge(DAGEdge(source="build", target="gate"))
    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, state_schema=_LoopState, checkpointer=cp)
    paused = await engine.run(inputs="")
    assert paused.paused is True
    # Without approve_pause: error.
    with pytest.raises(PipelineError, match="paused"):
        await engine.run(run_id=paused.run_id)


async def test_resume_with_approve_pause_continues_from_successor(tmp_path):
    build = _step_record("build")
    gate = _step_pause("awaiting approval")
    deploy = _step_record("deploy")
    dag = DAG("approved")
    dag.add_node(DAGNode(node_id="build", step=build))
    dag.add_node(DAGNode(node_id="gate", step=gate))
    dag.add_node(DAGNode(node_id="deploy", step=deploy))
    dag.add_edge(DAGEdge(source="build", target="gate"))
    dag.add_edge(DAGEdge(source="gate", target="deploy"))
    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, state_schema=_LoopState, checkpointer=cp)
    paused = await engine.run(inputs="")
    assert paused.paused is True
    resumed = await engine.run(run_id=paused.run_id, approve_pause=True)
    assert resumed.success
    # 'gate' is NOT re-executed; only 'deploy' adds to items.
    assert resumed.final_state.items == ["build", "deploy"]


# ---- Send ------------------------------------------------------------------


def _step_emit_sends(targets: list[str]):
    class _Step:
        async def execute(self, ctx, inputs):
            return [Send(target=t, payload={"items": [f"sent-{t}"]}) for t in targets]

    return _Step()


def _step_consume_payload(suffix: str):
    """A worker that turns its inbound items into a state update."""

    class _Step:
        async def execute(self, ctx, inputs):
            seen = list(ctx.state.items)
            return {"items": [f"{s}+{suffix}" for s in seen]}

    return _Step()


async def test_send_dispatches_workers_concurrently():
    """One node returns list[Send]; targets run concurrently and their outputs merge."""
    planner = _step_emit_sends(["a", "b"])
    worker_a = _step_consume_payload("A")
    worker_b = _step_consume_payload("B")
    dag = DAG("fanout")
    dag.add_node(DAGNode(node_id="planner", step=planner))
    dag.add_node(DAGNode(node_id="a", step=worker_a))
    dag.add_node(DAGNode(node_id="b", step=worker_b))
    dag.add_edge(DAGEdge(source="planner", target="a"))
    dag.add_edge(DAGEdge(source="planner", target="b"))
    engine = PipelineEngine(dag, state_schema=_LoopState)
    result = await engine.run(inputs="")
    assert result.success
    # Each worker sees its own payload (a sees "sent-a", b sees "sent-b").
    assert sorted(result.final_state.items) == sorted(["sent-a+A", "sent-b+B"])


async def test_single_send_is_treated_as_list_of_one():
    planner = _step_emit_sends(["a"])
    # Override to emit a single Send (not a list).

    class _Solo:
        async def execute(self, ctx, inputs):
            return Send(target="a", payload={"items": ["just-a"]})

    worker_a = _step_consume_payload("X")
    dag = DAG("solo")
    dag.add_node(DAGNode(node_id="planner", step=_Solo()))
    dag.add_node(DAGNode(node_id="a", step=worker_a))
    dag.add_edge(DAGEdge(source="planner", target="a"))
    engine = PipelineEngine(dag, state_schema=_LoopState)
    result = await engine.run(inputs="")
    assert result.success
    assert result.final_state.items == ["just-a+X"]


async def test_send_to_unknown_target_raises():
    class _Bad:
        async def execute(self, ctx, inputs):
            return [Send(target="ghost", payload={})]

    dag = DAG("unknown-send")
    dag.add_node(DAGNode(node_id="planner", step=_Bad()))
    engine = PipelineEngine(dag, state_schema=_LoopState)
    result = await engine.run(inputs="")
    # The fan-out fails; the pipeline reports failure.
    assert not result.success


# ---- Pause exports ---------------------------------------------------------


def test_pause_and_send_reexported_from_pipeline_package():
    from fireflyframework_agentic.pipeline import Pause as P
    from fireflyframework_agentic.pipeline import Send as S

    assert P is Pause
    assert S is Send
