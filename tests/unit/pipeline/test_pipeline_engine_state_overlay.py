"""Layer 3 of the unification (#245): state as optional overlay on PipelineEngine.

PipelineEngine now accepts ``state_schema=`` and ``state=`` arguments. When
configured, nodes that return a dict have it merged into a shared Pydantic
state object via reducers (replace, append, extend, merge_dict). Non-dict
returns continue to flow as port outputs — both modes coexist on the same
node.

This reclaims parallelism for state-aware pipelines: nodes that write
disjoint state fields can run concurrently via the existing topological
scheduler. Concurrent writes to the same field are merged by the reducer
declared on that field (commutative reducers like ``append`` are safe;
``replace`` is last-write-wins).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from fireflyframework_agentic.pipeline.audit import FileAuditLog
from fireflyframework_agentic.pipeline.checkpoint import FileCheckpointer
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine
from fireflyframework_agentic.pipeline.reducers import append, extend, merge_dict

# ---- Schemas ---------------------------------------------------------------


class _SimpleState(BaseModel):
    counter: int = 0
    note: str = ""


class _ListState(BaseModel):
    items: Annotated[list[str], append] = []
    batch: Annotated[list[str], extend] = []


class _MergeState(BaseModel):
    bag: Annotated[dict[str, int], merge_dict] = {}


# ---- Step helpers ----------------------------------------------------------


def _step_returns(value):
    """Build a step whose execute() always returns `value`."""

    class _Step:
        async def execute(self, ctx, inputs):
            return value

    return _Step()


def _step_reads_state(field: str):
    """Build a step that returns the current state's `field` as a port output."""

    class _Step:
        async def execute(self, ctx, inputs):
            return getattr(ctx.state, field)

    return _Step()


# ---- baseline: no state_schema = unchanged --------------------------------


async def test_engine_without_state_schema_is_unchanged():
    dag = DAG("plain")
    dag.add_node(DAGNode(node_id="a", step=_step_returns("port-value")))
    engine = PipelineEngine(dag)  # no state_schema
    result = await engine.run(inputs="x")
    assert result.success
    assert result.final_state is None
    assert result.outputs["a"].output == "port-value"


# ---- engine instantiates state from defaults when none passed -------------


async def test_state_schema_with_defaults_is_auto_instantiated():
    dag = DAG("auto-state")
    dag.add_node(DAGNode(node_id="a", step=_step_returns(None)))
    engine = PipelineEngine(dag, state_schema=_SimpleState)
    result = await engine.run(inputs="x")
    assert result.success
    assert isinstance(result.final_state, _SimpleState)
    assert result.final_state.counter == 0


# ---- explicit state passed via run() --------------------------------------


async def test_state_arg_is_used_when_passed():
    dag = DAG("explicit-state")
    dag.add_node(DAGNode(node_id="a", step=_step_returns(None)))
    engine = PipelineEngine(dag, state_schema=_SimpleState)
    result = await engine.run(inputs="x", state=_SimpleState(counter=42, note="hi"))
    assert result.success
    assert result.final_state.counter == 42
    assert result.final_state.note == "hi"


# ---- node returning dict merges into state via reducer --------------------


async def test_dict_return_is_state_update_under_replace():
    dag = DAG("dict-replace")
    dag.add_node(DAGNode(node_id="a", step=_step_returns({"counter": 7})))
    engine = PipelineEngine(dag, state_schema=_SimpleState)
    result = await engine.run(inputs="x")
    assert result.success
    assert result.final_state.counter == 7


async def test_append_reducer_accumulates_across_nodes():
    a, b = _step_returns({"items": "first"}), _step_returns({"items": "second"})
    dag = DAG("appender")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(DAGEdge(source="a", target="b"))
    engine = PipelineEngine(dag, state_schema=_ListState)
    result = await engine.run(inputs="x")
    assert result.success
    assert result.final_state.items == ["first", "second"]


async def test_extend_reducer_concatenates():
    a, b = _step_returns({"batch": ["x", "y"]}), _step_returns({"batch": ["z"]})
    dag = DAG("extender")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(DAGEdge(source="a", target="b"))
    engine = PipelineEngine(dag, state_schema=_ListState)
    result = await engine.run(inputs="x")
    assert result.success
    assert result.final_state.batch == ["x", "y", "z"]


async def test_merge_dict_reducer_merges():
    a, b = _step_returns({"bag": {"k1": 1}}), _step_returns({"bag": {"k2": 2}})
    dag = DAG("merger")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(DAGEdge(source="a", target="b"))
    engine = PipelineEngine(dag, state_schema=_MergeState)
    result = await engine.run(inputs="x")
    assert result.success
    assert result.final_state.bag == {"k1": 1, "k2": 2}


# ---- non-dict return still flows as a port output -------------------------


async def test_non_dict_return_is_still_a_port_output():
    """A node can write state OR emit a port value — its return type decides."""
    a = _step_returns("port-value")  # str, not dict → port output
    b = _step_reads_state("note")
    dag = DAG("mixed")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(DAGEdge(source="a", target="b"))
    engine = PipelineEngine(dag, state_schema=_SimpleState)
    result = await engine.run(inputs="x")
    assert result.success
    assert result.outputs["a"].output == "port-value"  # port preserved
    assert result.final_state.note == ""  # state untouched by 'a'


# ---- conditions can read state --------------------------------------------


async def test_edge_condition_reads_ctx_state():
    a = _step_returns({"counter": 5})
    b = _step_returns(None)
    dag = DAG("cond-on-state")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(
        DAGEdge(
            source="a",
            target="b",
            condition=lambda ctx: ctx.state.counter > 3,
        )
    )
    engine = PipelineEngine(dag, state_schema=_SimpleState)
    result = await engine.run(inputs="x")
    assert result.success
    assert not result.outputs["b"].skipped


# ---- parallelism: disjoint fields, commutative reducer ---------------------


async def test_parallel_nodes_with_commutative_reducer_accumulate():
    """Two nodes at the same level both append to items; both contributions land."""
    a = _step_returns({"items": "from-a"})
    b = _step_returns({"items": "from-b"})
    c = _step_returns(None)
    dag = DAG("parallel-append")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_node(DAGNode(node_id="c", step=c))
    dag.add_edge(DAGEdge(source="a", target="c"))
    dag.add_edge(DAGEdge(source="b", target="c"))
    engine = PipelineEngine(dag, state_schema=_ListState)
    result = await engine.run(inputs="x")
    assert result.success
    assert sorted(result.final_state.items) == ["from-a", "from-b"]


# ---- checkpoint + resume restores state -----------------------------------


async def test_resume_restores_shared_state(tmp_path):
    """Run with state, fail mid-pipeline, resume — state survives."""

    class _FailOnce:
        def __init__(self):
            self.calls = 0

        async def execute(self, ctx, inputs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("flake")
            return {"counter": ctx.state.counter + 100}

    from fireflyframework_agentic.pipeline.dag import FailureStrategy

    a = _step_returns({"counter": 1, "note": "from-a"})
    b = _FailOnce()
    dag = DAG("resume-state")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b, failure_strategy=FailureStrategy.FAIL_PIPELINE))
    dag.add_edge(DAGEdge(source="a", target="b"))
    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, checkpointer=cp, state_schema=_SimpleState)
    r1 = await engine.run(inputs="x")
    assert not r1.success
    # After 'a' succeeds, the checkpoint should contain state.counter=1.
    assert r1.final_state.counter == 1

    r2 = await engine.run(run_id=r1.run_id)
    assert r2.success
    # On resume: state.counter restored to 1, then b adds 100.
    assert r2.final_state.counter == 101
    assert r2.final_state.note == "from-a"  # state preserved


# ---- audit log works alongside state --------------------------------------


async def test_audit_records_under_state_overlay(tmp_path):
    dag = DAG("audit-state")
    dag.add_node(DAGNode(node_id="a", step=_step_returns({"counter": 3})))
    al = FileAuditLog(tmp_path)
    engine = PipelineEngine(dag, audit_log=al, state_schema=_SimpleState)
    result = await engine.run(inputs="x")
    entries = al.list_entries("audit-state", result.run_id)
    assert len(entries) == 1
    assert entries[0].status == "success"
