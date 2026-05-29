"""Layer 4 of the unification (#245): cycle-aware scheduler.

PipelineEngine accepts ``recursion_limit=`` and, when the DAG is cyclic
(allow_cycles=True and a cycle is actually present), switches to a
sequential frontier-following scheduler. Each node visit increments a
per-node counter; exceeding ``recursion_limit`` halts the run with an
explanatory failure.

This also patches the silent-corruption hazard in :meth:`DAG.topological_sort`
and :meth:`DAG.execution_levels` — both now raise on cyclic DAGs instead
of producing partial / wrong output.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine
from fireflyframework_agentic.pipeline.reducers import append

# ---- topology-API safety ---------------------------------------------------


def test_topological_sort_raises_on_cyclic_dag():
    dag = DAG("cyclic", allow_cycles=True)
    dag.add_node(DAGNode(node_id="a", step=None))
    dag.add_node(DAGNode(node_id="b", step=None))
    dag.add_edge(DAGEdge(source="a", target="b"))
    dag.add_edge(DAGEdge(source="b", target="a"))
    with pytest.raises(PipelineError, match="cyclic"):
        dag.topological_sort()


def test_execution_levels_raises_on_cyclic_dag():
    dag = DAG("cyclic-lev", allow_cycles=True)
    dag.add_node(DAGNode(node_id="a", step=None))
    dag.add_node(DAGNode(node_id="b", step=None))
    dag.add_edge(DAGEdge(source="a", target="b"))
    dag.add_edge(DAGEdge(source="b", target="a"))
    with pytest.raises(PipelineError, match="cyclic"):
        dag.execution_levels()


# ---- cyclic execution ------------------------------------------------------


class _CounterState(BaseModel):
    counter: int = 0
    log: Annotated[list[str], append] = []


def _bump(label: str, by: int = 1):
    """Return a step that records its label and bumps counter by `by`."""

    class _Step:
        def __init__(self):
            self.calls = 0

        async def execute(self, ctx, inputs):
            self.calls += 1
            return {"counter": ctx.state.counter + by, "log": label}

    return _Step()


async def test_cyclic_dag_loops_until_condition_fails():
    """Loop: incrementer -> guard. Guard's outgoing edge back to incrementer
    is alive while counter < 3. Loop exits when guard's continue edge dies."""
    inc = _bump("inc", by=1)
    # guard is a no-op pass-through.

    class _Pass:
        calls = 0

        async def execute(self, ctx, inputs):
            self.calls += 1
            return None

    guard = _Pass()
    dag = DAG("loop", allow_cycles=True)
    dag.add_node(DAGNode(node_id="inc", step=inc))
    dag.add_node(DAGNode(node_id="guard", step=guard))
    dag.add_edge(DAGEdge(source="inc", target="guard"))
    # Continue edge: re-enter inc while counter < 3.
    dag.add_edge(DAGEdge(source="guard", target="inc", condition=lambda ctx: ctx.state.counter < 3))
    engine = PipelineEngine(dag, state_schema=_CounterState, recursion_limit=10)
    result = await engine.run(inputs="")
    assert result.success
    assert result.final_state.counter == 3
    assert inc.calls == 3
    # guard runs after each inc.
    assert guard.calls == 3


async def test_recursion_limit_halts_runaway_cycle():
    inc = _bump("inc")

    class _Pass:
        async def execute(self, ctx, inputs):
            return None

    dag = DAG("infinite", allow_cycles=True)
    dag.add_node(DAGNode(node_id="inc", step=inc))
    dag.add_node(DAGNode(node_id="guard", step=_Pass()))
    dag.add_edge(DAGEdge(source="inc", target="guard"))
    dag.add_edge(DAGEdge(source="guard", target="inc"))  # always alive — runaway
    engine = PipelineEngine(dag, state_schema=_CounterState, recursion_limit=5)
    result = await engine.run(inputs="")
    assert not result.success
    assert (
        "recursion" in (result.outputs.get("inc") and result.outputs["inc"].error or "").lower()
        or "recursion" in (result.outputs.get("guard") and result.outputs["guard"].error or "").lower()
    )


async def test_recursion_limit_default_is_25():
    """The engine's default recursion_limit matches StatePipeline's (25)."""
    engine = PipelineEngine(DAG("x"))
    assert engine._recursion_limit == 25  # noqa: SLF001


async def test_audit_records_visit_per_iteration(tmp_path):
    """Each iteration of a cycle gets its own audit entry with incrementing visit."""
    from fireflyframework_agentic.pipeline.audit import FileAuditLog

    inc = _bump("inc")

    class _Pass:
        async def execute(self, ctx, inputs):
            return None

    dag = DAG("audited-loop", allow_cycles=True)
    dag.add_node(DAGNode(node_id="inc", step=inc))
    dag.add_node(DAGNode(node_id="guard", step=_Pass()))
    dag.add_edge(DAGEdge(source="inc", target="guard"))
    dag.add_edge(DAGEdge(source="guard", target="inc", condition=lambda ctx: ctx.state.counter < 2))
    al = FileAuditLog(tmp_path)
    engine = PipelineEngine(dag, state_schema=_CounterState, audit_log=al, recursion_limit=10)
    result = await engine.run(inputs="")
    assert result.success
    entries = al.list_entries("audited-loop", result.run_id)
    inc_visits = sorted([e.visit for e in entries if e.node_id == "inc"])
    assert inc_visits == [1, 2]


# ---- acyclic still works ---------------------------------------------------


async def test_acyclic_dag_with_allow_cycles_true_runs_normally():
    """allow_cycles=True doesn't force cyclic mode if there are no cycles."""
    a = _bump("a")
    b = _bump("b")
    dag = DAG("ac", allow_cycles=True)
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(DAGEdge(source="a", target="b"))
    engine = PipelineEngine(dag, state_schema=_CounterState)
    result = await engine.run(inputs="")
    assert result.success
    assert result.final_state.counter == 2
    assert a.calls == 1
    assert b.calls == 1
