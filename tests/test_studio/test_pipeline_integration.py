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

"""Integration tests proving realistic pipelines compile and execute.

These tests exercise the same graph shapes that The Architect produces
via its ``add_node`` / ``connect_nodes`` tools, verifying the full
canvas -> compiler -> engine -> execution loop.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_genai.agents.registry import agent_registry
from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.pipeline.engine import PipelineEngine
from fireflyframework_genai.pipeline.steps import (
    AgentStep,
    BranchStep,
    CallableStep,
    FanInStep,
    FanOutStep,
    ReasoningStep,
)
from fireflyframework_genai.reasoning.registry import reasoning_registry
from fireflyframework_genai.studio.codegen.models import (
    GraphEdge,
    GraphModel,
    GraphNode,
    NodeType,
)
from fireflyframework_genai.studio.execution.compiler import (
    CompilationError,
    compile_graph,
)
from fireflyframework_genai.tools.registry import tool_registry

# ---------------------------------------------------------------------------
# Helpers (same patterns as test_compiler.py)
# ---------------------------------------------------------------------------

_POS = {"x": 0.0, "y": 0.0}


def _make_graph(
    nodes: list[GraphNode],
    edges: list[GraphEdge] | None = None,
    metadata: dict | None = None,
) -> GraphModel:
    return GraphModel(nodes=nodes, edges=edges or [], metadata=metadata or {})


def _make_node(
    node_id: str,
    node_type: NodeType,
    label: str = "test-node",
    data: dict | None = None,
) -> GraphNode:
    return GraphNode(
        id=node_id, type=node_type, label=label, position=_POS, data=data or {}
    )


def _mock_agent(name: str = "mock-agent") -> MagicMock:
    agent = MagicMock()
    agent.name = name
    mock_result = MagicMock()
    mock_result.output = f"output from {name}"
    agent.run = AsyncMock(return_value=mock_result)
    return agent


def _mock_tool(name: str = "mock-tool") -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"Mock {name}"
    tool.execute = AsyncMock(return_value=f"result from {name}")
    return tool


def _mock_pattern(name: str = "mock-pattern") -> MagicMock:
    pattern = MagicMock()
    mock_result = MagicMock()
    mock_result.output = f"reasoning output from {name}"
    pattern.execute = AsyncMock(return_value=mock_result)
    return pattern


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class TestSimpleQAPipeline:
    """Single agent node with model + instructions compiles and produces AgentStep."""

    def test_compiles_to_agent_step(self):
        node = _make_node(
            "agent_1",
            NodeType.AGENT,
            label="QA Agent",
            data={
                "model": "openai:gpt-4o",
                "instructions": "Answer questions concisely.",
                "description": "A simple Q&A agent",
            },
        )
        graph = _make_graph([node])

        with patch("fireflyframework_genai.agents.base.FireflyAgent") as mock_cls:
            mock_cls.return_value = MagicMock()
            engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        dag_node = engine._dag.nodes["agent_1"]
        assert isinstance(dag_node.step, AgentStep)

    async def test_executes_with_mocked_agent(self):
        mock = _mock_agent("qa-agent")
        agent_registry._agents["qa-agent"] = mock

        node = _make_node(
            "agent_1",
            NodeType.AGENT,
            label="qa-agent",
            data={"agent_name": "qa-agent"},
        )
        graph = _make_graph([node])
        engine = compile_graph(graph)

        result = await engine.run(inputs="What is 2+2?")
        assert result.success is True
        assert result.outputs["agent_1"].output == "output from qa-agent"


class TestAgentWithToolPipeline:
    """Agent -> Tool -> Agent chain compiles with correct edges."""

    def test_compiles_three_node_chain(self):
        mock_agent = _mock_agent("chain-agent")
        mock_tool = _mock_tool("search")
        agent_registry._agents["chain-agent"] = mock_agent
        tool_registry._tools["search"] = mock_tool

        nodes = [
            _make_node("a1", NodeType.AGENT, label="chain-agent", data={"agent_name": "chain-agent"}),
            _make_node("t1", NodeType.TOOL, data={"tool_name": "search"}),
            _make_node("a2", NodeType.AGENT, label="chain-agent", data={"agent_name": "chain-agent"}),
        ]
        edges = [
            GraphEdge(id="e1", source="a1", target="t1"),
            GraphEdge(id="e2", source="t1", target="a2"),
        ]
        graph = _make_graph(nodes, edges)
        engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        dag = engine._dag
        assert len(dag.nodes) == 3
        assert len(dag.edges) == 2

        assert isinstance(dag.nodes["a1"].step, AgentStep)
        assert isinstance(dag.nodes["t1"].step, CallableStep)
        assert isinstance(dag.nodes["a2"].step, AgentStep)

        topo = dag.topological_sort()
        assert topo.index("a1") < topo.index("t1") < topo.index("a2")


class TestConditionalRoutingPipeline:
    """Agent -> Condition -> two branch agents verifies BranchStep."""

    def test_compiles_conditional_graph(self):
        mock = _mock_agent("router")
        agent_registry._agents["router"] = mock
        agent_registry._agents["handler-a"] = _mock_agent("handler-a")
        agent_registry._agents["handler-b"] = _mock_agent("handler-b")

        nodes = [
            _make_node("router", NodeType.AGENT, label="router", data={"agent_name": "router"}),
            _make_node(
                "cond",
                NodeType.CONDITION,
                data={
                    "condition": "category",
                    "branches": {"support": "handler_a", "sales": "handler_b"},
                },
            ),
            _make_node("handler_a", NodeType.AGENT, label="handler-a", data={"agent_name": "handler-a"}),
            _make_node("handler_b", NodeType.AGENT, label="handler-b", data={"agent_name": "handler-b"}),
        ]
        edges = [
            GraphEdge(id="e1", source="router", target="cond"),
            GraphEdge(id="e2", source="cond", target="handler_a"),
            GraphEdge(id="e3", source="cond", target="handler_b"),
        ]
        graph = _make_graph(nodes, edges)
        engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["cond"].step, BranchStep)

    async def test_condition_routes_correctly(self):
        """Verify the condition step returns the right branch label."""
        nodes = [
            _make_node(
                "cond",
                NodeType.CONDITION,
                data={
                    "condition": "type",
                    "branches": {"question": "qa_path", "complaint": "complaint_path"},
                },
            ),
        ]
        graph = _make_graph(nodes)
        engine = compile_graph(graph)
        step = engine._dag.nodes["cond"].step
        ctx = PipelineContext(inputs=None)

        assert await step.execute(ctx, {"type": "question"}) == "qa_path"
        assert await step.execute(ctx, {"type": "complaint"}) == "complaint_path"
        # Unknown value falls back to first branch
        assert await step.execute(ctx, {"type": "unknown"}) == "qa_path"


class TestReasoningPipeline:
    """Agent + reasoning node with ReAct pattern verifies ReasoningStep."""

    def test_compiles_reasoning_step(self):
        mock_agent = _mock_agent("thinker")
        mock_pattern = _mock_pattern("react")
        agent_registry._agents["thinker"] = mock_agent
        reasoning_registry._patterns["react"] = mock_pattern

        nodes = [
            _make_node("a1", NodeType.AGENT, label="thinker", data={"agent_name": "thinker"}),
            _make_node(
                "r1",
                NodeType.REASONING,
                data={"pattern_name": "react", "agent_name": "thinker"},
            ),
        ]
        edges = [GraphEdge(id="e1", source="a1", target="r1")]
        graph = _make_graph(nodes, edges)
        engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["r1"].step, ReasoningStep)


class TestFanOutFanInPipeline:
    """Fan-out -> multiple agents -> Fan-in verifies parallel execution structure."""

    def test_compiles_fan_structure(self):
        agent_registry._agents["worker"] = _mock_agent("worker")

        nodes = [
            _make_node("scatter", NodeType.FAN_OUT, data={"split_expression": "items"}),
            _make_node("w1", NodeType.AGENT, label="worker", data={"agent_name": "worker"}),
            _make_node("w2", NodeType.AGENT, label="worker", data={"agent_name": "worker"}),
            _make_node("gather", NodeType.FAN_IN, data={"merge_expression": "collect"}),
        ]
        edges = [
            GraphEdge(id="e1", source="scatter", target="w1"),
            GraphEdge(id="e2", source="scatter", target="w2"),
            GraphEdge(id="e3", source="w1", target="gather"),
            GraphEdge(id="e4", source="w2", target="gather"),
        ]
        graph = _make_graph(nodes, edges)
        engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["scatter"].step, FanOutStep)
        assert isinstance(engine._dag.nodes["gather"].step, FanInStep)

        topo = engine._dag.topological_sort()
        assert topo.index("scatter") < topo.index("w1")
        assert topo.index("scatter") < topo.index("w2")
        assert topo.index("w1") < topo.index("gather")
        assert topo.index("w2") < topo.index("gather")


class TestFullPipelineExecution:
    """Build an agent -> tool graph, run with mocks, verify events fire."""

    async def test_agent_tool_execution_flow(self):
        mock_agent = _mock_agent("exec-agent")
        mock_tool = _mock_tool("calculator")
        agent_registry._agents["exec-agent"] = mock_agent
        tool_registry._tools["calculator"] = mock_tool

        nodes = [
            _make_node("a1", NodeType.AGENT, label="exec-agent", data={"agent_name": "exec-agent"}),
            _make_node("t1", NodeType.TOOL, data={"tool_name": "calculator"}),
        ]
        edges = [GraphEdge(id="e1", source="a1", target="t1")]
        graph = _make_graph(nodes, edges)

        from fireflyframework_genai.studio.execution.runner import StudioEventHandler

        handler = StudioEventHandler()
        engine = compile_graph(graph, event_handler=handler)
        result = await engine.run(inputs="compute something")

        assert result.success is True
        assert result.outputs["a1"].success is True
        assert result.outputs["t1"].success is True

        events = handler.drain_events()
        event_types = [e["type"] for e in events]
        assert "node_start" in event_types
        assert "node_complete" in event_types
        assert "pipeline_complete" in event_types

    async def test_single_custom_code_execution(self):
        """A single custom code node runs end-to-end."""
        code = "async def execute(context, inputs):\n    val = inputs.get('input', '')\n    return val.upper() if isinstance(val, str) else val\n"
        node = _make_node("upper", NodeType.CUSTOM_CODE, data={"code": code})
        graph = _make_graph([node])
        engine = compile_graph(graph)

        result = await engine.run(inputs="hello world")
        assert result.success is True
        assert result.outputs["upper"].output == "HELLO WORLD"


class TestArchitectStyleGraphCompiles:
    """Use a GraphModel mirroring what The Architect's tools produce."""

    def test_architect_graph_compiles(self):
        """Simulate The Architect adding nodes and connecting them."""
        agent_registry._agents["classifier"] = _mock_agent("classifier")
        agent_registry._agents["responder"] = _mock_agent("responder")
        tool_registry._tools["search"] = _mock_tool("search")

        # This mirrors what add_node + connect_nodes produce
        nodes = [
            _make_node(
                "agent_1",
                NodeType.AGENT,
                label="classifier",
                data={"agent_name": "classifier", "model": "openai:gpt-4o", "instructions": "Classify the input."},
            ),
            _make_node(
                "condition_2",
                NodeType.CONDITION,
                data={"condition": "category", "branches": {"tech": "tool_3", "general": "agent_4"}},
            ),
            _make_node("tool_3", NodeType.TOOL, data={"tool_name": "search"}),
            _make_node(
                "agent_4",
                NodeType.AGENT,
                label="responder",
                data={"agent_name": "responder"},
            ),
        ]
        edges = [
            GraphEdge(id="edge_5", source="agent_1", target="condition_2"),
            GraphEdge(id="edge_6", source="condition_2", target="tool_3"),
            GraphEdge(id="edge_7", source="condition_2", target="agent_4"),
        ]
        graph = _make_graph(nodes, edges, metadata={"name": "architect-pipeline"})
        engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        assert engine._dag.name == "architect-pipeline"
        assert len(engine._dag.nodes) == 4
        assert len(engine._dag.edges) == 3


class TestMultimodalAgentNodeCompiles:
    """Agent node with multimodal config in data dict compiles (forwards unknown data keys)."""

    def test_multimodal_config_does_not_block_compilation(self):
        node = _make_node(
            "mm_agent",
            NodeType.AGENT,
            label="Vision Agent",
            data={
                "model": "openai:gpt-4o",
                "instructions": "Analyze images.",
                "multimodal": {
                    "vision_enabled": True,
                    "supported_file_types": ["image/png", "image/jpeg"],
                    "max_file_size_mb": 10,
                    "image_detail": "auto",
                },
            },
        )
        graph = _make_graph([node])

        with patch("fireflyframework_genai.agents.base.FireflyAgent") as mock_cls:
            mock_cls.return_value = MagicMock()
            engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["mm_agent"].step, AgentStep)
