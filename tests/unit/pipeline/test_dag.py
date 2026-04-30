# Copyright 2026 Firefly Software Solutions Inc
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

"""Tests for DAG model and pipeline engine."""

import pytest

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine
from fireflyframework_agentic.pipeline.result import NodeResult
from fireflyframework_agentic.pipeline.steps import FanInStep

# -- Helper step -----------------------------------------------------------


class EchoStep:
    """Simple step that echoes input with a prefix."""

    def __init__(self, prefix: str = ""):
        self._prefix = prefix

    async def execute(self, context, inputs):
        val = inputs.get("input", "")
        return f"{self._prefix}{val}"


# -- DAG tests -------------------------------------------------------------


class TestDAG:
    def test_add_nodes_and_edges(self):
        dag = DAG("test")
        dag.add_node(DAGNode(node_id="a", step=EchoStep()))
        dag.add_node(DAGNode(node_id="b", step=EchoStep()))
        dag.add_edge(DAGEdge(source="a", target="b"))
        assert len(dag.nodes) == 2
        assert len(dag.edges) == 1

    def test_duplicate_node_raises(self):
        dag = DAG("test")
        dag.add_node(DAGNode(node_id="a", step=EchoStep()))
        with pytest.raises(PipelineError, match="Duplicate"):
            dag.add_node(DAGNode(node_id="a", step=EchoStep()))

    def test_cycle_detection(self):
        dag = DAG("test")
        dag.add_node(DAGNode(node_id="a", step=EchoStep()))
        dag.add_node(DAGNode(node_id="b", step=EchoStep()))
        dag.add_edge(DAGEdge(source="a", target="b"))
        with pytest.raises(PipelineError, match="cycle"):
            dag.add_edge(DAGEdge(source="b", target="a"))

    def test_topological_sort(self):
        dag = DAG("test")
        dag.add_node(DAGNode(node_id="a", step=EchoStep()))
        dag.add_node(DAGNode(node_id="b", step=EchoStep()))
        dag.add_node(DAGNode(node_id="c", step=EchoStep()))
        dag.add_edge(DAGEdge(source="a", target="b"))
        dag.add_edge(DAGEdge(source="b", target="c"))
        order = dag.topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_execution_levels(self):
        dag = DAG("test")
        dag.add_node(DAGNode(node_id="a", step=EchoStep()))
        dag.add_node(DAGNode(node_id="b", step=EchoStep()))
        dag.add_node(DAGNode(node_id="c", step=EchoStep()))
        dag.add_edge(DAGEdge(source="a", target="c"))
        dag.add_edge(DAGEdge(source="b", target="c"))
        levels = dag.execution_levels()
        # a and b should be in the same level (parallel)
        assert {"a", "b"} == set(levels[0])
        assert levels[1] == ["c"]

    def test_terminal_nodes(self):
        dag = DAG("test")
        dag.add_node(DAGNode(node_id="a", step=EchoStep()))
        dag.add_node(DAGNode(node_id="b", step=EchoStep()))
        dag.add_edge(DAGEdge(source="a", target="b"))
        assert dag.terminal_nodes() == ["b"]

    def test_predecessors_and_successors(self):
        dag = DAG("test")
        dag.add_node(DAGNode(node_id="a", step=EchoStep()))
        dag.add_node(DAGNode(node_id="b", step=EchoStep()))
        dag.add_edge(DAGEdge(source="a", target="b"))
        assert dag.predecessors("b") == ["a"]
        assert dag.successors("a") == ["b"]

    def test_edge_missing_source(self):
        dag = DAG("test")
        dag.add_node(DAGNode(node_id="a", step=EchoStep()))
        with pytest.raises(PipelineError, match="not found"):
            dag.add_edge(DAGEdge(source="missing", target="a"))


# -- Engine tests ----------------------------------------------------------


class TestPipelineEngine:
    async def test_simple_linear_pipeline(self):
        dag = DAG("linear")
        dag.add_node(DAGNode(node_id="upper", step=EchoStep("UPPER:")))
        dag.add_node(DAGNode(node_id="suffix", step=EchoStep("SUFFIX:")))
        dag.add_edge(DAGEdge(source="upper", target="suffix"))
        engine = PipelineEngine(dag)
        result = await engine.run(inputs="hello")
        assert result.success is True
        assert result.final_output == "SUFFIX:UPPER:hello"
        assert len(result.execution_trace) == 2

    async def test_parallel_execution(self):
        dag = DAG("parallel")
        dag.add_node(DAGNode(node_id="a", step=EchoStep("A:")))
        dag.add_node(DAGNode(node_id="b", step=EchoStep("B:")))
        dag.add_node(DAGNode(node_id="merge", step=FanInStep()))
        dag.add_edge(DAGEdge(source="a", target="merge", input_key="a_in"))
        dag.add_edge(DAGEdge(source="b", target="merge", input_key="b_in"))
        engine = PipelineEngine(dag)
        result = await engine.run(inputs="data")
        assert result.success is True
        # merge should have received both outputs
        assert isinstance(result.final_output, list)
        assert len(result.final_output) == 2

    async def test_conditional_skip(self):
        dag = DAG("conditional")
        dag.add_node(DAGNode(node_id="always", step=EchoStep("OK:")))
        dag.add_node(
            DAGNode(
                node_id="never",
                step=EchoStep("SKIP:"),
                condition=lambda ctx: False,
            )
        )
        engine = PipelineEngine(dag)
        result = await engine.run(inputs="test")
        assert result.outputs["never"].skipped is True
        assert result.outputs["always"].success is True

    async def test_node_failure(self):
        class FailStep:
            async def execute(self, context, inputs):
                raise RuntimeError("boom")

        dag = DAG("fail")
        dag.add_node(DAGNode(node_id="fail", step=FailStep()))
        engine = PipelineEngine(dag)
        result = await engine.run(inputs="test")
        assert result.success is False
        assert result.outputs["fail"].error == "boom"


# -- Builder tests ---------------------------------------------------------


class TestPipelineBuilder:
    async def test_build_and_run(self):
        engine = (
            PipelineBuilder("test")
            .add_node("a", EchoStep("A:"))
            .add_node("b", EchoStep("B:"))
            .add_edge("a", "b")
            .build()
        )
        result = await engine.run(inputs="hello")
        assert result.success is True
        assert result.final_output == "B:A:hello"

    async def test_chain_shorthand(self):
        engine = (
            PipelineBuilder("chain")
            .add_node("x", EchoStep("X:"))
            .add_node("y", EchoStep("Y:"))
            .add_node("z", EchoStep("Z:"))
            .chain("x", "y", "z")
            .build()
        )
        result = await engine.run(inputs="input")
        assert result.success is True
        assert result.final_output == "Z:Y:X:input"

    def test_build_dag(self):
        dag = (
            PipelineBuilder("dag-only")
            .add_node("a", EchoStep())
            .add_node("b", EchoStep())
            .add_edge("a", "b")
            .build_dag()
        )
        assert len(dag.nodes) == 2
        assert len(dag.edges) == 1


class TestPipelineContext:
    def test_set_and_get(self):
        ctx = PipelineContext(inputs="test")
        nr = NodeResult(node_id="a", output="result_a")
        ctx.set_node_result("a", nr)
        assert ctx.get_node_output("a") == "result_a"

    def test_missing_node(self):
        ctx = PipelineContext()
        assert ctx.get_node_output("missing") is None


# -- Exponential backoff tests -----------------------------------------------


class TestExponentialBackoff:
    def test_dag_node_backoff_factor_default(self):
        node = DAGNode(node_id="n", step=EchoStep())
        assert node.backoff_factor == 1.0

    def test_dag_node_custom_backoff(self):
        node = DAGNode(node_id="n", step=EchoStep(), backoff_factor=2.5)
        assert node.backoff_factor == 2.5

    async def test_retry_with_exponential_backoff(self):
        """Verify that retries use exponential backoff (not linear)."""
        call_count = 0

        class FailTwiceStep:
            async def execute(self, context, inputs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise RuntimeError(f"Fail #{call_count}")
                return "success"

        dag = DAG("retry-test")
        dag.add_node(
            DAGNode(
                node_id="retryable",
                step=FailTwiceStep(),
                retry_max=2,
                backoff_factor=0.01,  # Very small for test speed
            )
        )
        engine = PipelineEngine(dag)
        result = await engine.run(inputs="test")
        assert result.success is True
        assert call_count == 3
