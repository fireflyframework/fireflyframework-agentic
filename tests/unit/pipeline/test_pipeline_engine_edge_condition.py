"""Layer 2 of the unification (#245): branching as DAGEdge.condition.

DAGEdge now carries an optional predicate that gates traversal. When a
source completes, each outgoing edge's condition is evaluated against the
current PipelineContext. Targets whose incoming edges all evaluate False
are marked skipped (no execution, no result, transitive downstream cascade
via SKIP_DOWNSTREAM).

This unifies the legacy ``BranchStep`` + ``DAGNode.condition`` machinery
into a single property of the DAG. ``.branch(source, router, mapping)`` —
which today lives in StatePipeline — will be reframed as sugar that adds
conditional edges in a later layer.
"""

from __future__ import annotations

from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine


class _Echo:
    """Step that returns its input verbatim, tagged with a node prefix."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self.calls = 0

    async def execute(self, ctx, inputs):
        self.calls += 1
        return f"{self.prefix}{inputs.get('input', '')}"


# ---- baseline: edge without condition is unchanged ------------------------


async def test_edge_without_condition_is_unchanged():
    a, b = _Echo("a:"), _Echo("b:")
    dag = DAG("plain")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(DAGEdge(source="a", target="b"))
    result = await PipelineEngine(dag).run(inputs="x")
    assert result.success
    assert a.calls == 1 and b.calls == 1


# ---- single conditional edge ----------------------------------------------


async def test_true_condition_lets_target_run():
    a, b = _Echo("a:"), _Echo("b:")
    dag = DAG("true-cond")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(DAGEdge(source="a", target="b", condition=lambda ctx: True))
    result = await PipelineEngine(dag).run(inputs="x")
    assert result.success
    assert b.calls == 1


async def test_false_condition_skips_target():
    a, b = _Echo("a:"), _Echo("b:")
    dag = DAG("false-cond")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(DAGEdge(source="a", target="b", condition=lambda ctx: False))
    result = await PipelineEngine(dag).run(inputs="x")
    assert result.success  # the pipeline as a whole still succeeds
    assert a.calls == 1
    assert b.calls == 0
    assert result.outputs["b"].skipped


# ---- branching: one source, two conditional targets -----------------------


async def test_branch_chooses_one_of_two_targets():
    """Classic if/else branching via two conditional edges from the same source."""
    a = _Echo("a:")
    yes, no = _Echo("yes:"), _Echo("no:")
    dag = DAG("if-else")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="yes", step=yes))
    dag.add_node(DAGNode(node_id="no", step=no))
    dag.add_edge(
        DAGEdge(
            source="a",
            target="yes",
            condition=lambda ctx: "good" in str(ctx.get_node_result("a").output),
        )
    )
    dag.add_edge(
        DAGEdge(
            source="a",
            target="no",
            condition=lambda ctx: "good" not in str(ctx.get_node_result("a").output),
        )
    )
    result = await PipelineEngine(dag).run(inputs="good run")
    assert result.success
    assert yes.calls == 1
    assert no.calls == 0
    assert result.outputs["no"].skipped


# ---- cascading skip --------------------------------------------------------


async def test_skipped_target_cascades_to_its_downstream():
    a, b, c = _Echo("a:"), _Echo("b:"), _Echo("c:")
    dag = DAG("cascade")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_node(DAGNode(node_id="c", step=c))
    dag.add_edge(DAGEdge(source="a", target="b", condition=lambda ctx: False))
    dag.add_edge(DAGEdge(source="b", target="c"))
    result = await PipelineEngine(dag).run(inputs="x")
    assert result.success
    assert a.calls == 1
    assert b.calls == 0
    assert c.calls == 0
    assert result.outputs["b"].skipped
    assert result.outputs["c"].skipped


# ---- fan-in with mixed conditions: OR semantics ---------------------------


async def test_fanin_runs_if_any_incoming_edge_alive():
    """Two upstreams, one edge False, one edge True → target runs."""
    a, b, c = _Echo("a:"), _Echo("b:"), _Echo("c:")
    dag = DAG("fanin")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_node(DAGNode(node_id="c", step=c))
    dag.add_edge(DAGEdge(source="a", target="c", condition=lambda ctx: False))
    dag.add_edge(DAGEdge(source="b", target="c", condition=lambda ctx: True))
    result = await PipelineEngine(dag).run(inputs="x")
    assert result.success
    assert c.calls == 1
    assert not result.outputs["c"].skipped


async def test_fanin_skipped_when_all_incoming_edges_dead():
    a, b, c = _Echo("a:"), _Echo("b:"), _Echo("c:")
    dag = DAG("fanin-dead")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_node(DAGNode(node_id="c", step=c))
    dag.add_edge(DAGEdge(source="a", target="c", condition=lambda ctx: False))
    dag.add_edge(DAGEdge(source="b", target="c", condition=lambda ctx: False))
    result = await PipelineEngine(dag).run(inputs="x")
    assert result.success
    assert c.calls == 0
    assert result.outputs["c"].skipped


# ---- condition can read upstream output -----------------------------------


async def test_condition_sees_completed_upstream_output():
    """The condition gets a PipelineContext and can inspect prior node results."""

    class _Number:
        async def execute(self, ctx, inputs):
            return 42

    a = _Number()
    b = _Echo("big:")
    dag = DAG("cond-reads-upstream")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))
    dag.add_edge(
        DAGEdge(
            source="a",
            target="b",
            condition=lambda ctx: ctx.get_node_result("a").output > 10,
        )
    )
    result = await PipelineEngine(dag).run(inputs="")
    assert result.success
    assert b.calls == 1


# ---- condition exception is treated as False ------------------------------


async def test_raising_condition_treated_as_false():
    """If the condition itself raises, the edge is dead — fail closed."""
    a, b = _Echo("a:"), _Echo("b:")
    dag = DAG("raising-cond")
    dag.add_node(DAGNode(node_id="a", step=a))
    dag.add_node(DAGNode(node_id="b", step=b))

    def raiser(ctx):
        raise RuntimeError("oops")

    dag.add_edge(DAGEdge(source="a", target="b", condition=raiser))
    result = await PipelineEngine(dag).run(inputs="x")
    assert result.success
    assert b.calls == 0
    assert result.outputs["b"].skipped


# ---- to_mermaid renders conditional edges ---------------------------------


def test_mermaid_marks_conditional_edges():
    dag = DAG("viz")
    dag.add_node(DAGNode(node_id="a", step=_Echo()))
    dag.add_node(DAGNode(node_id="b", step=_Echo()))
    dag.add_node(DAGNode(node_id="c", step=_Echo()))
    dag.add_edge(DAGEdge(source="a", target="b"))
    dag.add_edge(DAGEdge(source="a", target="c", condition=lambda ctx: True))
    mermaid = dag.to_mermaid()
    # Unconditional edge: plain arrow.
    assert "a --> b" in mermaid
    # Conditional edge: labelled distinctively (we use "if?").
    assert "a -->|if?| c" in mermaid or "a -.->|if?| c" in mermaid
