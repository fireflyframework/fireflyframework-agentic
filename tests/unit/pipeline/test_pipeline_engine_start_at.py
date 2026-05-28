"""Layer 6 of the unification (#245): start_at kwarg for mid-pipeline entry.

PipelineEngine.run() accepts ``start_at=`` (string node id or callable
reference). Execution begins at the named node; everything not reachable
from it is treated as pre-completed and skipped. This is the unified
equivalent of StatePipeline.invoke(state=..., start_at=...).
"""

from __future__ import annotations

import pytest

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine


class _Counting:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0

    async def execute(self, ctx, inputs):
        self.calls += 1
        return self.name


def _chain(*ids: str) -> tuple[DAG, dict[str, _Counting]]:
    dag = DAG("chain")
    steps: dict[str, _Counting] = {}
    for nid in ids:
        s = _Counting(nid)
        steps[nid] = s
        dag.add_node(DAGNode(node_id=nid, step=s))
    for i in range(len(ids) - 1):
        dag.add_edge(DAGEdge(source=ids[i], target=ids[i + 1]))
    return dag, steps


# ---- baseline -------------------------------------------------------------


async def test_no_start_at_runs_every_node():
    dag, steps = _chain("a", "b", "c")
    result = await PipelineEngine(dag).run(inputs="x")
    assert result.success
    assert all(s.calls == 1 for s in steps.values())


# ---- start_at: skip upstream ----------------------------------------------


async def test_start_at_skips_upstream_nodes():
    dag, steps = _chain("a", "b", "c", "d")
    result = await PipelineEngine(dag).run(inputs="x", start_at="c")
    assert result.success
    assert steps["a"].calls == 0
    assert steps["b"].calls == 0
    assert steps["c"].calls == 1
    assert steps["d"].calls == 1


async def test_start_at_first_node_is_like_no_start_at():
    dag, steps = _chain("a", "b", "c")
    result = await PipelineEngine(dag).run(inputs="x", start_at="a")
    assert result.success
    assert all(s.calls == 1 for s in steps.values())


async def test_start_at_terminal_runs_only_that_node():
    dag, steps = _chain("a", "b", "c")
    result = await PipelineEngine(dag).run(inputs="x", start_at="c")
    assert result.success
    assert steps["a"].calls == 0
    assert steps["b"].calls == 0
    assert steps["c"].calls == 1


# ---- start_at via callable ------------------------------------------------


async def test_start_at_accepts_callable_reference():
    async def deploy(ctx, inputs):
        return "deployed"

    from fireflyframework_agentic.pipeline.steps import CallableStep

    dag = DAG("callable")
    dag.add_node(DAGNode(node_id="build", step=_Counting("build")))
    dag.add_node(DAGNode(node_id="deploy", step=CallableStep(deploy)))
    dag.add_edge(DAGEdge(source="build", target="deploy"))
    result = await PipelineEngine(dag).run(inputs="x", start_at=deploy)
    assert result.success
    # Resolves deploy.__name__ -> 'deploy' -> only deploy ran.
    assert result.outputs["deploy"].output == "deployed"


# ---- invalid start_at -----------------------------------------------------


async def test_unknown_start_at_raises():
    dag, _ = _chain("a", "b")
    with pytest.raises(PipelineError, match="start_at"):
        await PipelineEngine(dag).run(inputs="x", start_at="ghost")


# ---- branching dag --------------------------------------------------------


async def test_start_at_in_branching_dag():
    """In a branching DAG, start_at picks one branch; the other is skipped entirely."""
    dag = DAG("branchy")
    for nid in ("root", "left", "right", "leftchild"):
        dag.add_node(DAGNode(node_id=nid, step=_Counting(nid)))
    dag.add_edge(DAGEdge(source="root", target="left"))
    dag.add_edge(DAGEdge(source="root", target="right"))
    dag.add_edge(DAGEdge(source="left", target="leftchild"))
    result = await PipelineEngine(dag).run(inputs="x", start_at="left")
    assert result.success
    # 'right' is not downstream of 'left' — it should not run.
    assert "right" not in result.outputs or result.outputs["right"].skipped
    # 'leftchild' is reachable from 'left'.
    assert result.outputs["leftchild"].success
