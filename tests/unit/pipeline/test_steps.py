"""Tests for pipeline steps — BranchStep."""

from __future__ import annotations

from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine
from fireflyframework_agentic.pipeline.steps import BranchStep


class _EchoStep:
    def __init__(self, prefix: str = ""):
        self._prefix = prefix

    async def execute(self, context, inputs):
        val = inputs.get("input", "")
        return f"{self._prefix}{val}"


class TestBranchStep:
    async def test_branch_routes_positive(self):
        def router(inputs):
            text = inputs.get("input", "")
            return "positive" if "good" in text else "negative"

        step = BranchStep(router=router)
        ctx = PipelineContext(inputs="")
        result = await step.execute(ctx, {"input": "this is good"})
        assert result == "positive"

    async def test_branch_routes_negative(self):
        step = BranchStep(router=lambda inp: "a" if inp.get("x") else "b")
        ctx = PipelineContext(inputs="")
        result = await step.execute(ctx, {"x": ""})
        assert result == "b"

    async def test_branch_in_pipeline(self):
        """BranchStep integrated in a real DAG with conditional downstream nodes."""
        dag = DAG("branch-dag")
        dag.add_node(
            DAGNode(
                node_id="branch",
                step=BranchStep(router=lambda inp: "left" if "left" in inp.get("input", "") else "right"),
            )
        )
        dag.add_node(
            DAGNode(
                node_id="left_node",
                step=_EchoStep("L:"),
                condition=lambda ctx: ctx.get_node_result("branch").output == "left",
            )
        )
        dag.add_node(
            DAGNode(
                node_id="right_node",
                step=_EchoStep("R:"),
                condition=lambda ctx: ctx.get_node_result("branch").output == "right",
            )
        )
        dag.add_edge(DAGEdge(source="branch", target="left_node"))
        dag.add_edge(DAGEdge(source="branch", target="right_node"))
        engine = PipelineEngine(dag)

        result = await engine.run(inputs="go left")
        assert result.success is True
        assert result.outputs["left_node"].success is True
        assert result.outputs["right_node"].skipped is True

    def test_branch_step_import_from_package(self):
        from fireflyframework_agentic.pipeline import BranchStep as BranchStepAlias

        assert BranchStepAlias is BranchStep
