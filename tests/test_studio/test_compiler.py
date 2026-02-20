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

"""Comprehensive tests for the Studio graph-to-engine compiler."""

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
# Helpers
# ---------------------------------------------------------------------------

_POS = {"x": 0.0, "y": 0.0}


def _make_graph(
    nodes: list[GraphNode],
    edges: list[GraphEdge] | None = None,
    metadata: dict | None = None,
) -> GraphModel:
    return GraphModel(
        nodes=nodes,
        edges=edges or [],
        metadata=metadata or {},
    )


def _make_node(
    node_id: str,
    node_type: NodeType,
    label: str = "test-node",
    data: dict | None = None,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,
        label=label,
        position=_POS,
        data=data or {},
    )


def _mock_agent(name: str = "mock-agent") -> MagicMock:
    """Create a mock agent that satisfies the AgentLike protocol."""
    agent = MagicMock()
    agent.name = name
    mock_result = MagicMock()
    mock_result.output = f"output from {name}"
    agent.run = AsyncMock(return_value=mock_result)
    return agent


def _mock_tool(name: str = "mock-tool") -> MagicMock:
    """Create a mock tool that satisfies the ToolProtocol."""
    tool = MagicMock()
    tool.name = name
    tool.description = f"Mock {name}"
    tool.execute = AsyncMock(return_value=f"result from {name}")
    return tool


def _mock_pattern(name: str = "mock-pattern") -> MagicMock:
    """Create a mock reasoning pattern."""
    pattern = MagicMock()
    mock_result = MagicMock()
    mock_result.output = f"reasoning output from {name}"
    pattern.execute = AsyncMock(return_value=mock_result)
    return pattern


# ---------------------------------------------------------------------------
# CompilationError on empty / invalid graphs
# ---------------------------------------------------------------------------


class TestCompilationErrorCases:
    def test_empty_graph_raises(self):
        graph = GraphModel(nodes=[], edges=[])
        with pytest.raises(CompilationError, match="no nodes"):
            compile_graph(graph)

    def test_unsupported_node_type_raises(self):
        """A node whose type is absent from the dispatch table raises."""
        node = _make_node("n1", NodeType.AGENT, data={})
        graph = _make_graph([node])

        # Temporarily replace the dispatch table to simulate an unsupported type
        with (
            patch(
                "fireflyframework_genai.studio.execution.compiler._NODE_COMPILERS",
                {},
            ),
            pytest.raises(CompilationError, match="Unsupported node type"),
        ):
            compile_graph(graph)


# ---------------------------------------------------------------------------
# AGENT node compilation
# ---------------------------------------------------------------------------


class TestCompileAgentNode:
    def test_agent_from_registry(self):
        """When the agent is already registered, use the registered instance."""
        mock = _mock_agent("my-agent")
        agent_registry._agents["my-agent"] = mock

        node = _make_node("a1", NodeType.AGENT, label="my-agent", data={"agent_name": "my-agent"})
        graph = _make_graph([node])
        engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        # The DAG node's step should be an AgentStep wrapping our mock
        dag_node = engine._dag.nodes["a1"]
        assert isinstance(dag_node.step, AgentStep)

    def test_agent_created_dynamically_with_model(self):
        """When the agent is not registered, a dynamic FireflyAgent is created."""
        node = _make_node(
            "a2",
            NodeType.AGENT,
            label="Dynamic Agent",
            data={"model": "openai:gpt-4o", "instructions": "Be concise."},
        )
        graph = _make_graph([node])

        with patch(
            "fireflyframework_genai.agents.base.FireflyAgent",
        ) as mock_firefly_agent:
            mock_instance = MagicMock()
            mock_firefly_agent.return_value = mock_instance
            engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        mock_firefly_agent.assert_called_once_with(
            name="Dynamic Agent",
            model="openai:gpt-4o",
            instructions="Be concise.",
            auto_register=False,
        )

    def test_agent_without_model_or_registry_raises(self):
        """AGENT node without a 'model' and not in registry raises."""
        node = _make_node("a3", NodeType.AGENT, label="nomodel", data={})
        graph = _make_graph([node])

        with pytest.raises(CompilationError, match="requires a 'model'"):
            compile_graph(graph)

    def test_agent_name_falls_back_to_label(self):
        """When 'agent_name' is absent from data, the node label is used."""
        node = _make_node(
            "a4",
            NodeType.AGENT,
            label="Agent Label",
            data={"model": "openai:gpt-4o"},
        )
        graph = _make_graph([node])

        with patch(
            "fireflyframework_genai.agents.base.FireflyAgent",
        ) as mock_firefly_agent:
            mock_firefly_agent.return_value = MagicMock()
            compile_graph(graph)

        mock_firefly_agent.assert_called_once_with(
            name="Agent Label",
            model="openai:gpt-4o",
            instructions="",
            auto_register=False,
        )


# ---------------------------------------------------------------------------
# TOOL node compilation
# ---------------------------------------------------------------------------


class TestCompileToolNode:
    def test_tool_from_registry(self):
        mock = _mock_tool("search")
        tool_registry._tools["search"] = mock

        node = _make_node("t1", NodeType.TOOL, data={"tool_name": "search"})
        graph = _make_graph([node])
        engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        dag_node = engine._dag.nodes["t1"]
        assert isinstance(dag_node.step, CallableStep)

    def test_tool_missing_tool_name_raises(self):
        node = _make_node("t2", NodeType.TOOL, data={})
        graph = _make_graph([node])

        with pytest.raises(CompilationError, match="requires 'tool_name'"):
            compile_graph(graph)

    def test_tool_not_registered_raises(self):
        node = _make_node("t3", NodeType.TOOL, data={"tool_name": "nonexistent"})
        graph = _make_graph([node])

        with pytest.raises(CompilationError, match="is not registered"):
            compile_graph(graph)

    async def test_tool_step_calls_tool_execute(self):
        """The compiled TOOL step delegates to tool.execute with inputs."""
        mock = _mock_tool("calc")
        tool_registry._tools["calc"] = mock

        node = _make_node("t4", NodeType.TOOL, data={"tool_name": "calc"})
        graph = _make_graph([node])
        engine = compile_graph(graph)

        step = engine._dag.nodes["t4"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"x": 1, "y": 2})

        mock.execute.assert_awaited_once_with(x=1, y=2)
        assert result == "result from calc"


# ---------------------------------------------------------------------------
# REASONING node compilation
# ---------------------------------------------------------------------------


class TestCompileReasoningNode:
    def test_reasoning_from_registries(self):
        mock_agent = _mock_agent("reasoner")
        mock_pattern = _mock_pattern("chain_of_thought")
        agent_registry._agents["reasoner"] = mock_agent
        reasoning_registry._patterns["chain_of_thought"] = mock_pattern

        node = _make_node(
            "r1",
            NodeType.REASONING,
            data={"pattern_name": "chain_of_thought", "agent_name": "reasoner"},
        )
        graph = _make_graph([node])
        engine = compile_graph(graph)

        assert isinstance(engine, PipelineEngine)
        dag_node = engine._dag.nodes["r1"]
        assert isinstance(dag_node.step, ReasoningStep)

    def test_reasoning_missing_pattern_name_raises(self):
        node = _make_node("r2", NodeType.REASONING, data={"agent_name": "a"})
        graph = _make_graph([node])

        with pytest.raises(CompilationError, match="requires 'pattern_name'"):
            compile_graph(graph)

    def test_reasoning_missing_agent_name_raises(self):
        node = _make_node("r3", NodeType.REASONING, data={"pattern_name": "cot"})
        graph = _make_graph([node])

        with pytest.raises(CompilationError, match="requires 'agent_name'"):
            compile_graph(graph)

    def test_reasoning_unregistered_pattern_raises(self):
        node = _make_node(
            "r4",
            NodeType.REASONING,
            data={"pattern_name": "missing", "agent_name": "a"},
        )
        graph = _make_graph([node])

        with pytest.raises(CompilationError, match="is not registered"):
            compile_graph(graph)

    def test_reasoning_unregistered_agent_raises(self):
        # Register pattern but not agent
        reasoning_registry._patterns["cot"] = _mock_pattern("cot")

        node = _make_node(
            "r5",
            NodeType.REASONING,
            data={"pattern_name": "cot", "agent_name": "missing_agent"},
        )
        graph = _make_graph([node])

        with pytest.raises(CompilationError, match="is not registered"):
            compile_graph(graph)


# ---------------------------------------------------------------------------
# PIPELINE_STEP node compilation
# ---------------------------------------------------------------------------


class TestCompilePipelineStepNode:
    def test_pipeline_step_compiles(self):
        node = _make_node("ps1", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["ps1"].step, CallableStep)

    async def test_pipeline_step_passthrough_with_input(self):
        """The PIPELINE_STEP pass-through returns 'input' from inputs dict."""
        node = _make_node("ps2", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["ps2"].step
        ctx = PipelineContext(inputs="fallback")
        result = await step.execute(ctx, {"input": "hello"})
        assert result == "hello"

    async def test_pipeline_step_passthrough_falls_back_to_context(self):
        """When 'input' key is absent, falls back to context.inputs."""
        node = _make_node("ps3", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["ps3"].step
        ctx = PipelineContext(inputs="ctx-fallback")
        result = await step.execute(ctx, {})
        assert result == "ctx-fallback"


# ---------------------------------------------------------------------------
# FAN_OUT node compilation
# ---------------------------------------------------------------------------


class TestCompileFanOutNode:
    def test_fan_out_compiles(self):
        node = _make_node("fo1", NodeType.FAN_OUT, data={"split_expression": "items"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["fo1"].step, FanOutStep)

    async def test_fan_out_splits_by_field(self):
        node = _make_node("fo2", NodeType.FAN_OUT, data={"split_expression": "items"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["fo2"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": {"items": [1, 2, 3]}})
        assert result == [1, 2, 3]

    async def test_fan_out_wraps_non_list_field(self):
        node = _make_node("fo3", NodeType.FAN_OUT, data={"split_expression": "key"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["fo3"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": {"key": "single"}})
        assert result == ["single"]

    async def test_fan_out_splits_list_input_no_expression(self):
        node = _make_node("fo4", NodeType.FAN_OUT, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["fo4"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": [10, 20, 30]})
        assert result == [10, 20, 30]

    async def test_fan_out_wraps_scalar_input(self):
        node = _make_node("fo5", NodeType.FAN_OUT, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["fo5"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": "scalar"})
        assert result == ["scalar"]


# ---------------------------------------------------------------------------
# FAN_IN node compilation
# ---------------------------------------------------------------------------


class TestCompileFanInNode:
    def test_fan_in_compiles(self):
        node = _make_node("fi1", NodeType.FAN_IN, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["fi1"].step, FanInStep)

    async def test_fan_in_collect_default(self):
        node = _make_node("fi2", NodeType.FAN_IN, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["fi2"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"a": 1, "b": 2, "c": 3})
        assert result == [1, 2, 3]

    async def test_fan_in_concat_flattens_lists(self):
        node = _make_node("fi3", NodeType.FAN_IN, data={"merge_expression": "concat"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["fi3"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"a": [1, 2], "b": [3, 4]})
        assert result == [1, 2, 3, 4]

    async def test_fan_in_concat_appends_non_list(self):
        node = _make_node("fi4", NodeType.FAN_IN, data={"merge_expression": "concat"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["fi4"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"a": [1], "b": "scalar"})
        assert result == [1, "scalar"]

    async def test_fan_in_explicit_collect(self):
        """Explicit 'collect' merge_expression behaves same as default."""
        node = _make_node("fi5", NodeType.FAN_IN, data={"merge_expression": "collect"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["fi5"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"x": "a", "y": "b"})
        assert result == ["a", "b"]


# ---------------------------------------------------------------------------
# CONDITION node compilation
# ---------------------------------------------------------------------------


class TestCompileConditionNode:
    def test_condition_compiles(self):
        node = _make_node(
            "c1",
            NodeType.CONDITION,
            data={
                "condition": "status",
                "branches": {"ok": "happy", "err": "sad"},
            },
        )
        graph = _make_graph([node])
        engine = compile_graph(graph)
        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["c1"].step, BranchStep)

    def test_condition_missing_branches_raises(self):
        node = _make_node("c2", NodeType.CONDITION, data={"condition": "status"})
        graph = _make_graph([node])
        with pytest.raises(CompilationError, match="requires 'branches'"):
            compile_graph(graph)

    def test_condition_empty_branches_raises(self):
        node = _make_node(
            "c3",
            NodeType.CONDITION,
            data={"condition": "status", "branches": {}},
        )
        graph = _make_graph([node])
        with pytest.raises(CompilationError, match="requires 'branches'"):
            compile_graph(graph)

    async def test_condition_routes_correctly(self):
        node = _make_node(
            "c4",
            NodeType.CONDITION,
            data={
                "condition": "status",
                "branches": {"ok": "happy_path", "err": "error_path"},
            },
        )
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["c4"].step
        ctx = PipelineContext(inputs=None)

        result = await step.execute(ctx, {"status": "ok"})
        assert result == "happy_path"

        result = await step.execute(ctx, {"status": "err"})
        assert result == "error_path"

    async def test_condition_returns_default_for_unknown_value(self):
        node = _make_node(
            "c5",
            NodeType.CONDITION,
            data={
                "condition": "status",
                "branches": {"ok": "happy_path", "err": "error_path"},
            },
        )
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["c5"].step
        ctx = PipelineContext(inputs=None)

        # Unknown value falls back to the first branch value
        result = await step.execute(ctx, {"status": "unknown"})
        assert result == "happy_path"

    async def test_condition_uses_default_condition_key(self):
        """When 'condition' is not set in data, defaults to 'input'."""
        node = _make_node(
            "c6",
            NodeType.CONDITION,
            data={"branches": {"yes": "accept", "no": "reject"}},
        )
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["c6"].step
        ctx = PipelineContext(inputs=None)

        result = await step.execute(ctx, {"input": "yes"})
        assert result == "accept"


# ---------------------------------------------------------------------------
# MEMORY node compilation
# ---------------------------------------------------------------------------


class TestCompileMemoryNode:
    def test_memory_compiles(self):
        node = _make_node("m1", NodeType.MEMORY, data={"memory_action": "store"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["m1"].step, CallableStep)

    async def test_memory_store_action(self):
        node = _make_node("m2", NodeType.MEMORY, data={"memory_action": "store"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["m2"].step

        mock_memory = MagicMock()
        ctx = PipelineContext(inputs=None, memory=mock_memory)

        result = await step.execute(ctx, {"key": "my_key", "input": "my_value"})
        assert result == "my_value"
        mock_memory.set_fact.assert_called_once_with("my_key", "my_value")

    async def test_memory_retrieve_action(self):
        node = _make_node("m3", NodeType.MEMORY, data={"memory_action": "retrieve"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["m3"].step

        mock_memory = MagicMock()
        mock_memory.get_fact.return_value = "stored_value"
        ctx = PipelineContext(inputs=None, memory=mock_memory)

        result = await step.execute(ctx, {"key": "my_key"})
        assert result == "stored_value"
        mock_memory.get_fact.assert_called_once_with("my_key")

    async def test_memory_clear_action(self):
        node = _make_node("m4", NodeType.MEMORY, data={"memory_action": "clear"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["m4"].step

        mock_memory = MagicMock()
        ctx = PipelineContext(inputs=None, memory=mock_memory)

        result = await step.execute(ctx, {"key": "my_key"})
        assert result is None
        mock_memory.working.delete.assert_called_once_with("my_key")

    async def test_memory_no_manager_returns_input(self):
        node = _make_node("m5", NodeType.MEMORY, data={"memory_action": "store"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["m5"].step

        ctx = PipelineContext(inputs=None, memory=None)
        result = await step.execute(ctx, {"input": "fallback_value"})
        assert result == "fallback_value"

    async def test_memory_default_action_is_retrieve(self):
        node = _make_node("m6", NodeType.MEMORY, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["m6"].step

        mock_memory = MagicMock()
        mock_memory.get_fact.return_value = "retrieved"
        ctx = PipelineContext(inputs=None, memory=mock_memory)

        result = await step.execute(ctx, {"key": "k"})
        assert result == "retrieved"

    async def test_memory_store_with_value_key(self):
        """The store action can also read from 'value' key when 'input' is absent."""
        node = _make_node("m7", NodeType.MEMORY, data={"memory_action": "store"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["m7"].step

        mock_memory = MagicMock()
        ctx = PipelineContext(inputs=None, memory=mock_memory)

        result = await step.execute(ctx, {"key": "k", "value": "from_value"})
        assert result == "from_value"
        mock_memory.set_fact.assert_called_once_with("k", "from_value")


# ---------------------------------------------------------------------------
# VALIDATOR node compilation
# ---------------------------------------------------------------------------


class TestCompileValidatorNode:
    def test_validator_compiles(self):
        node = _make_node("v1", NodeType.VALIDATOR, data={"validation_rule": "not_empty"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["v1"].step, CallableStep)

    async def test_validator_not_empty_passes(self):
        node = _make_node("v2", NodeType.VALIDATOR, data={"validation_rule": "not_empty"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v2"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": "something"})
        assert result == "something"

    async def test_validator_not_empty_fails(self):
        node = _make_node("v3", NodeType.VALIDATOR, data={"validation_rule": "not_empty"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v3"].step
        ctx = PipelineContext(inputs=None)
        with pytest.raises(ValueError, match="value is empty"):
            await step.execute(ctx, {"input": ""})

    async def test_validator_is_string_passes(self):
        node = _make_node("v4", NodeType.VALIDATOR, data={"validation_rule": "is_string"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v4"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": "hello"})
        assert result == "hello"

    async def test_validator_is_string_fails(self):
        node = _make_node("v5", NodeType.VALIDATOR, data={"validation_rule": "is_string"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v5"].step
        ctx = PipelineContext(inputs=None)
        with pytest.raises(TypeError, match="expected string"):
            await step.execute(ctx, {"input": 42})

    async def test_validator_is_list_passes(self):
        node = _make_node("v6", NodeType.VALIDATOR, data={"validation_rule": "is_list"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v6"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": [1, 2, 3]})
        assert result == [1, 2, 3]

    async def test_validator_is_list_fails(self):
        node = _make_node("v7", NodeType.VALIDATOR, data={"validation_rule": "is_list"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v7"].step
        ctx = PipelineContext(inputs=None)
        with pytest.raises(TypeError, match="expected list"):
            await step.execute(ctx, {"input": "not-a-list"})

    async def test_validator_is_dict_passes(self):
        node = _make_node("v8", NodeType.VALIDATOR, data={"validation_rule": "is_dict"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v8"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": {"a": 1}})
        assert result == {"a": 1}

    async def test_validator_is_dict_fails(self):
        node = _make_node("v9", NodeType.VALIDATOR, data={"validation_rule": "is_dict"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v9"].step
        ctx = PipelineContext(inputs=None)
        with pytest.raises(TypeError, match="expected dict"):
            await step.execute(ctx, {"input": "not-a-dict"})

    async def test_validator_custom_key_rule_passes(self):
        node = _make_node("v10", NodeType.VALIDATOR, data={"validation_rule": "name"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v10"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": {"name": "Alice"}})
        assert result == {"name": "Alice"}

    async def test_validator_custom_key_rule_fails(self):
        node = _make_node("v11", NodeType.VALIDATOR, data={"validation_rule": "name"})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v11"].step
        ctx = PipelineContext(inputs=None)
        with pytest.raises(KeyError, match="key 'name' missing"):
            await step.execute(ctx, {"input": {"age": 30}})

    async def test_validator_no_rule_passes_through(self):
        node = _make_node("v12", NodeType.VALIDATOR, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["v12"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": "anything"})
        assert result == "anything"


# ---------------------------------------------------------------------------
# CUSTOM_CODE node compilation
# ---------------------------------------------------------------------------


class TestCompileCustomCodeNode:
    def test_custom_code_compiles(self):
        code = "async def execute(context, inputs):\n    return inputs.get('input', 'default')\n"
        node = _make_node("cc1", NodeType.CUSTOM_CODE, data={"code": code})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        assert isinstance(engine, PipelineEngine)
        assert isinstance(engine._dag.nodes["cc1"].step, CallableStep)

    async def test_custom_code_executes_correctly(self):
        code = "async def execute(context, inputs):\n    return inputs.get('input', '') + ' processed'\n"
        node = _make_node("cc2", NodeType.CUSTOM_CODE, data={"code": code})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["cc2"].step
        ctx = PipelineContext(inputs=None)
        result = await step.execute(ctx, {"input": "data"})
        assert result == "data processed"

    def test_custom_code_missing_code_raises(self):
        node = _make_node("cc3", NodeType.CUSTOM_CODE, data={})
        graph = _make_graph([node])
        with pytest.raises(CompilationError, match="requires 'code'"):
            compile_graph(graph)

    def test_custom_code_empty_string_raises(self):
        node = _make_node("cc4", NodeType.CUSTOM_CODE, data={"code": ""})
        graph = _make_graph([node])
        with pytest.raises(CompilationError, match="requires 'code'"):
            compile_graph(graph)

    def test_custom_code_syntax_error_raises(self):
        node = _make_node("cc5", NodeType.CUSTOM_CODE, data={"code": "def bad(:"})
        graph = _make_graph([node])
        with pytest.raises(CompilationError, match="Syntax error"):
            compile_graph(graph)

    def test_custom_code_missing_execute_function_raises(self):
        code = "def helper():\n    return 42\n"
        node = _make_node("cc6", NodeType.CUSTOM_CODE, data={"code": code})
        graph = _make_graph([node])
        with pytest.raises(CompilationError, match="must define"):
            compile_graph(graph)

    def test_custom_code_non_callable_execute_raises(self):
        code = "execute = 'not a function'\n"
        node = _make_node("cc7", NodeType.CUSTOM_CODE, data={"code": code})
        graph = _make_graph([node])
        with pytest.raises(CompilationError, match="must define"):
            compile_graph(graph)

    async def test_custom_code_can_access_context(self):
        """Custom code can read context.inputs."""
        code = "async def execute(context, inputs):\n    return f'ctx={context.inputs}'\n"
        node = _make_node("cc8", NodeType.CUSTOM_CODE, data={"code": code})
        graph = _make_graph([node])
        engine = compile_graph(graph)
        step = engine._dag.nodes["cc8"].step
        ctx = PipelineContext(inputs="original")
        result = await step.execute(ctx, {})
        assert result == "ctx=original"


# ---------------------------------------------------------------------------
# Edge wiring
# ---------------------------------------------------------------------------


class TestEdgeWiring:
    def test_single_edge(self):
        n1 = _make_node("n1", NodeType.PIPELINE_STEP, data={})
        n2 = _make_node("n2", NodeType.PIPELINE_STEP, data={})
        edge = GraphEdge(id="e1", source="n1", target="n2")
        graph = _make_graph([n1, n2], [edge])

        engine = compile_graph(graph)
        dag = engine._dag
        assert len(dag.edges) == 1
        assert dag.edges[0].source == "n1"
        assert dag.edges[0].target == "n2"

    def test_multiple_edges(self):
        n1 = _make_node("n1", NodeType.PIPELINE_STEP, data={})
        n2 = _make_node("n2", NodeType.PIPELINE_STEP, data={})
        n3 = _make_node("n3", NodeType.PIPELINE_STEP, data={})
        edges = [
            GraphEdge(id="e1", source="n1", target="n2"),
            GraphEdge(id="e2", source="n1", target="n3"),
        ]
        graph = _make_graph([n1, n2, n3], edges)

        engine = compile_graph(graph)
        dag = engine._dag
        assert len(dag.edges) == 2
        assert set(dag.successors("n1")) == {"n2", "n3"}

    def test_edge_handles_passed_through(self):
        """source_handle and target_handle from GraphEdge map to DAGEdge keys."""
        n1 = _make_node("n1", NodeType.PIPELINE_STEP, data={})
        n2 = _make_node("n2", NodeType.PIPELINE_STEP, data={})
        edge = GraphEdge(
            id="e1",
            source="n1",
            target="n2",
            source_handle="result",
            target_handle="prompt",
        )
        graph = _make_graph([n1, n2], [edge])

        engine = compile_graph(graph)
        dag = engine._dag
        dag_edge = dag.edges[0]
        assert dag_edge.output_key == "result"
        assert dag_edge.input_key == "prompt"

    def test_default_edge_handles(self):
        n1 = _make_node("n1", NodeType.PIPELINE_STEP, data={})
        n2 = _make_node("n2", NodeType.PIPELINE_STEP, data={})
        edge = GraphEdge(id="e1", source="n1", target="n2")
        graph = _make_graph([n1, n2], [edge])

        engine = compile_graph(graph)
        dag = engine._dag
        dag_edge = dag.edges[0]
        assert dag_edge.output_key == "output"
        assert dag_edge.input_key == "input"

    def test_chain_of_three_nodes(self):
        nodes = [
            _make_node("a", NodeType.PIPELINE_STEP, data={}),
            _make_node("b", NodeType.PIPELINE_STEP, data={}),
            _make_node("c", NodeType.PIPELINE_STEP, data={}),
        ]
        edges = [
            GraphEdge(id="e1", source="a", target="b"),
            GraphEdge(id="e2", source="b", target="c"),
        ]
        graph = _make_graph(nodes, edges)

        engine = compile_graph(graph)
        dag = engine._dag
        topo = dag.topological_sort()
        assert topo.index("a") < topo.index("b") < topo.index("c")

    def test_diamond_topology(self):
        """A -> B, A -> C, B -> D, C -> D."""
        nodes = [
            _make_node("a", NodeType.PIPELINE_STEP, data={}),
            _make_node("b", NodeType.PIPELINE_STEP, data={}),
            _make_node("c", NodeType.PIPELINE_STEP, data={}),
            _make_node("d", NodeType.PIPELINE_STEP, data={}),
        ]
        edges = [
            GraphEdge(id="e1", source="a", target="b"),
            GraphEdge(id="e2", source="a", target="c"),
            GraphEdge(id="e3", source="b", target="d"),
            GraphEdge(id="e4", source="c", target="d"),
        ]
        graph = _make_graph(nodes, edges)

        engine = compile_graph(graph)
        dag = engine._dag
        assert len(dag.nodes) == 4
        assert len(dag.edges) == 4
        topo = dag.topological_sort()
        assert topo.index("a") < topo.index("b")
        assert topo.index("a") < topo.index("c")
        assert topo.index("b") < topo.index("d")
        assert topo.index("c") < topo.index("d")


# ---------------------------------------------------------------------------
# Graph metadata
# ---------------------------------------------------------------------------


class TestGraphMetadata:
    def test_pipeline_name_from_metadata(self):
        node = _make_node("n1", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node], metadata={"name": "my-custom-pipeline"})

        engine = compile_graph(graph)
        assert engine._dag.name == "my-custom-pipeline"

    def test_default_pipeline_name(self):
        node = _make_node("n1", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])

        engine = compile_graph(graph)
        assert engine._dag.name == "studio-pipeline"


# ---------------------------------------------------------------------------
# Event handler propagation
# ---------------------------------------------------------------------------


class TestEventHandlerPropagation:
    def test_event_handler_is_set(self):
        node = _make_node("n1", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])

        mock_handler = MagicMock()
        engine = compile_graph(graph, event_handler=mock_handler)
        assert engine._event_handler is mock_handler

    def test_no_event_handler_by_default(self):
        node = _make_node("n1", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])

        engine = compile_graph(graph)
        assert engine._event_handler is None


# ---------------------------------------------------------------------------
# Integration: compile and run graphs end-to-end
# ---------------------------------------------------------------------------


class TestIntegrationCompileAndRun:
    async def test_agent_to_pipeline_step(self):
        """End-to-end: compile a two-node graph and run it with a mocked agent."""
        mock = _mock_agent("test-agent")
        agent_registry._agents["test-agent"] = mock

        agent_node = _make_node(
            "agent1",
            NodeType.AGENT,
            label="test-agent",
            data={"agent_name": "test-agent"},
        )
        step_node = _make_node("step1", NodeType.PIPELINE_STEP, data={})
        edge = GraphEdge(id="e1", source="agent1", target="step1")
        graph = _make_graph([agent_node, step_node], [edge])

        engine = compile_graph(graph)
        result = await engine.run(inputs="hello")

        assert result.success is True
        assert "agent1" in result.outputs
        assert result.outputs["agent1"].success is True
        assert result.outputs["agent1"].output == "output from test-agent"
        assert "step1" in result.outputs
        assert result.outputs["step1"].success is True
        # step1 receives agent1's output via the edge
        assert result.outputs["step1"].output == "output from test-agent"

    async def test_single_pipeline_step(self):
        """Simplest possible pipeline: one PIPELINE_STEP node with no edges."""
        node = _make_node("solo", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])
        engine = compile_graph(graph)

        result = await engine.run(inputs="test input")
        assert result.success is True
        assert result.outputs["solo"].output == "test input"

    async def test_custom_code_end_to_end(self):
        """Compile and run a graph with a CUSTOM_CODE node."""
        code = (
            "async def execute(context, inputs):\n"
            "    val = inputs.get('input', '')\n"
            "    return val.upper() if isinstance(val, str) else val\n"
        )
        node = _make_node("upper", NodeType.CUSTOM_CODE, data={"code": code})
        graph = _make_graph([node])
        engine = compile_graph(graph)

        result = await engine.run(inputs="hello world")
        assert result.success is True
        assert result.outputs["upper"].output == "HELLO WORLD"

    async def test_fan_out_fan_in_end_to_end(self):
        """Compile a FAN_OUT -> FAN_IN pair and verify the round-trip."""
        fo_node = _make_node("scatter", NodeType.FAN_OUT, data={})
        fi_node = _make_node("gather", NodeType.FAN_IN, data={})
        edge = GraphEdge(id="e1", source="scatter", target="gather")
        graph = _make_graph([fo_node, fi_node], [edge])

        engine = compile_graph(graph)
        result = await engine.run(inputs=[1, 2, 3])

        assert result.success is True
        assert result.outputs["scatter"].output == [1, 2, 3]
        # FAN_IN collects its upstream outputs into a list
        assert result.outputs["gather"].output == [[1, 2, 3]]

    async def test_validator_passes_end_to_end(self):
        """Compile and run with a validator that should pass."""
        node = _make_node("val", NodeType.VALIDATOR, data={"validation_rule": "not_empty"})
        graph = _make_graph([node])
        engine = compile_graph(graph)

        result = await engine.run(inputs="non-empty")
        assert result.success is True
        assert result.outputs["val"].output == "non-empty"

    async def test_validator_fails_end_to_end(self):
        """Compile and run with a validator that should fail."""
        node = _make_node("val", NodeType.VALIDATOR, data={"validation_rule": "not_empty"})
        graph = _make_graph([node])
        engine = compile_graph(graph)

        result = await engine.run(inputs="")
        # The validator raises, which the engine catches as a node failure
        assert result.outputs["val"].success is False
        assert "value is empty" in result.outputs["val"].error

    async def test_pipeline_step_chain_end_to_end(self):
        """Chain three PIPELINE_STEP nodes and verify data flows through."""
        nodes = [
            _make_node("a", NodeType.PIPELINE_STEP, data={}),
            _make_node("b", NodeType.PIPELINE_STEP, data={}),
            _make_node("c", NodeType.PIPELINE_STEP, data={}),
        ]
        edges = [
            GraphEdge(id="e1", source="a", target="b"),
            GraphEdge(id="e2", source="b", target="c"),
        ]
        graph = _make_graph(nodes, edges)
        engine = compile_graph(graph)

        result = await engine.run(inputs="chain-data")
        assert result.success is True
        assert result.outputs["a"].output == "chain-data"
        assert result.outputs["b"].output == "chain-data"
        assert result.outputs["c"].output == "chain-data"


# ---------------------------------------------------------------------------
# Mixed graph: multiple node types with edges
# ---------------------------------------------------------------------------


class TestMixedGraph:
    def test_compile_graph_with_diverse_node_types(self):
        """A graph with PIPELINE_STEP, VALIDATOR, FAN_OUT, FAN_IN,
        CONDITION, MEMORY, and CUSTOM_CODE all compiled together."""
        code = "async def execute(context, inputs):\n    return inputs\n"
        nodes = [
            _make_node("ps", NodeType.PIPELINE_STEP, data={}),
            _make_node("val", NodeType.VALIDATOR, data={"validation_rule": "not_empty"}),
            _make_node("fo", NodeType.FAN_OUT, data={}),
            _make_node("fi", NodeType.FAN_IN, data={}),
            _make_node(
                "cond",
                NodeType.CONDITION,
                data={
                    "condition": "type",
                    "branches": {"a": "path_a", "b": "path_b"},
                },
            ),
            _make_node("mem", NodeType.MEMORY, data={"memory_action": "retrieve"}),
            _make_node("cc", NodeType.CUSTOM_CODE, data={"code": code}),
        ]
        edges = [
            GraphEdge(id="e1", source="ps", target="val"),
            GraphEdge(id="e2", source="val", target="fo"),
            GraphEdge(id="e3", source="fo", target="fi"),
            GraphEdge(id="e4", source="fi", target="cond"),
            GraphEdge(id="e5", source="cond", target="mem"),
            GraphEdge(id="e6", source="mem", target="cc"),
        ]
        graph = _make_graph(nodes, edges)

        engine = compile_graph(graph)
        dag = engine._dag
        assert len(dag.nodes) == 7
        assert len(dag.edges) == 6
        topo = dag.topological_sort()
        assert topo.index("ps") < topo.index("val") < topo.index("fo")
        assert topo.index("fo") < topo.index("fi") < topo.index("cond")
        assert topo.index("cond") < topo.index("mem") < topo.index("cc")
