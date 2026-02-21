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

"""Compile a Studio GraphModel into a runnable PipelineEngine.

The compiler maps each visual canvas node to the corresponding
:class:`~fireflyframework_genai.pipeline.steps.StepExecutor` and wires
the edges into a :class:`~fireflyframework_genai.pipeline.dag.DAG`.

Usage::

    from fireflyframework_genai.studio.execution.compiler import compile_graph

    engine = compile_graph(graph, event_handler=handler)
    result = await engine.run(context, inputs=user_input)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fireflyframework_genai.pipeline.builder import PipelineBuilder
from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.pipeline.engine import PipelineEngine, PipelineEventHandler
from fireflyframework_genai.pipeline.steps import (
    AgentStep,
    BranchStep,
    CallableStep,
    FanInStep,
    FanOutStep,
    ReasoningStep,
)
from fireflyframework_genai.studio.codegen.models import GraphModel, GraphNode, NodeType
from fireflyframework_genai.studio.execution.io_nodes import InputNodeConfig, OutputNodeConfig

logger = logging.getLogger(__name__)


class CompilationError(Exception):
    """Raised when a graph cannot be compiled into a pipeline."""


def compile_graph(
    graph: GraphModel,
    event_handler: PipelineEventHandler | None = None,
) -> PipelineEngine:
    """Compile a :class:`GraphModel` into a runnable :class:`PipelineEngine`.

    Parameters:
        graph: The visual graph model from the Studio canvas.
        event_handler: Optional handler for real-time execution events.

    Returns:
        A configured :class:`PipelineEngine` ready to run.

    Raises:
        CompilationError: If the graph contains invalid or incomplete nodes.
    """
    if not graph.nodes:
        raise CompilationError("Graph has no nodes")

    # Validate IO node constraints when present
    input_nodes = [n for n in graph.nodes if n.type == NodeType.INPUT]
    output_nodes = [n for n in graph.nodes if n.type == NodeType.OUTPUT]

    if input_nodes:
        if len(input_nodes) > 1:
            raise CompilationError(
                "Pipeline must have exactly one Input node, found {}.".format(len(input_nodes))
            )
        if not output_nodes:
            raise CompilationError(
                "Pipeline with an Input node must have at least one Output node."
            )

    name = graph.metadata.get("name", "studio-pipeline")
    builder = PipelineBuilder(name=name)

    for node in graph.nodes:
        step = _compile_node(node)
        builder.add_node(node.id, step)

    for edge in graph.edges:
        builder.add_edge(
            edge.source,
            edge.target,
            output_key=edge.source_handle,
            input_key=edge.target_handle,
        )

    dag = builder.build_dag()
    return PipelineEngine(dag, event_handler=event_handler)


def _compile_node(node: GraphNode) -> Any:
    """Map a single graph node to the appropriate StepExecutor."""
    compiler = _NODE_COMPILERS.get(node.type)
    if compiler is None:
        raise CompilationError(f"Unsupported node type: {node.type!r} (node {node.id!r})")
    return compiler(node)


# ---------------------------------------------------------------------------
# Node compilers — one function per NodeType
# ---------------------------------------------------------------------------


def _compile_agent(node: GraphNode) -> AgentStep:
    """Compile an AGENT node.

    Tries the global agent registry first.  If the agent is not registered,
    creates a dynamic FireflyAgent from the node's model + instructions.
    """
    from fireflyframework_genai.agents.base import FireflyAgent
    from fireflyframework_genai.agents.registry import agent_registry

    agent_name = node.data.get("agent_name", node.label)

    if agent_registry.has(agent_name):
        agent = agent_registry.get(agent_name)
        return AgentStep(agent)

    model = node.data.get("model")
    if not model:
        raise CompilationError(f"AGENT node {node.id!r} requires a 'model' in data (e.g. 'openai:gpt-4o')")

    instructions = node.data.get("instructions", "")
    agent = FireflyAgent(
        name=agent_name,
        model=model,
        instructions=instructions,
        auto_register=False,
    )
    return AgentStep(agent)


def _compile_tool(node: GraphNode) -> CallableStep:
    """Compile a TOOL node by looking up the registered tool."""
    from fireflyframework_genai.tools.registry import tool_registry

    tool_name = node.data.get("tool_name")
    if not tool_name:
        raise CompilationError(f"TOOL node {node.id!r} requires 'tool_name' in data")

    if not tool_registry.has(tool_name):
        raise CompilationError(f"Tool {tool_name!r} is not registered (node {node.id!r})")

    tool = tool_registry.get(tool_name)

    async def _execute_tool(context: PipelineContext, inputs: dict[str, Any]) -> Any:
        return await tool.execute(**inputs)

    return CallableStep(_execute_tool)


def _compile_reasoning(node: GraphNode) -> ReasoningStep:
    """Compile a REASONING node from registered pattern + agent."""
    from fireflyframework_genai.agents.registry import agent_registry
    from fireflyframework_genai.reasoning.registry import reasoning_registry

    pattern_name = node.data.get("pattern_name")
    if not pattern_name:
        raise CompilationError(f"REASONING node {node.id!r} requires 'pattern_name' in data")

    agent_name = node.data.get("agent_name")
    if not agent_name:
        raise CompilationError(f"REASONING node {node.id!r} requires 'agent_name' in data")

    if not reasoning_registry.has(pattern_name):
        raise CompilationError(f"Reasoning pattern {pattern_name!r} is not registered (node {node.id!r})")
    if not agent_registry.has(agent_name):
        raise CompilationError(f"Agent {agent_name!r} is not registered (node {node.id!r})")

    pattern = reasoning_registry.get(pattern_name)
    agent = agent_registry.get(agent_name)
    return ReasoningStep(pattern, agent)


def _compile_pipeline_step(node: GraphNode) -> CallableStep:
    """Compile a generic PIPELINE_STEP node as a pass-through."""

    async def _passthrough(context: PipelineContext, inputs: dict[str, Any]) -> Any:
        return inputs.get("input", context.inputs)

    return CallableStep(_passthrough)


def _compile_fan_out(node: GraphNode) -> FanOutStep:
    """Compile a FAN_OUT node with a split function.

    If ``split_expression`` is a dotted field path (e.g. ``"items"``),
    extracts that key from the input.  Otherwise splits the input
    into a list if it isn't one already.
    """
    field = node.data.get("split_expression", "")

    def _split(value: Any) -> list[Any]:
        if field and isinstance(value, dict):
            extracted = value.get(field, value)
            return list(extracted) if isinstance(extracted, list) else [extracted]
        if isinstance(value, list):
            return value
        return [value]

    return FanOutStep(_split)


def _compile_fan_in(node: GraphNode) -> FanInStep:
    """Compile a FAN_IN node with a merge function.

    Supported merge expressions:
    - ``"concat"``: flatten all upstream lists into one
    - ``"collect"`` (default): gather all upstream outputs as a list
    """
    merge_expr = node.data.get("merge_expression", "collect")

    if merge_expr == "concat":

        def _concat(items: list[Any]) -> Any:
            result: list[Any] = []
            for item in items:
                if isinstance(item, list):
                    result.extend(item)
                else:
                    result.append(item)
            return result

        return FanInStep(_concat)

    # Default: collect
    return FanInStep()


def _compile_condition(node: GraphNode) -> BranchStep:
    """Compile a CONDITION node into a BranchStep.

    The node's ``condition`` field is a key name to look up in the input.
    The ``branches`` dict maps possible values to branch labels.
    If no match, returns the first branch as default.
    """
    condition_key = node.data.get("condition", "input")
    branches: dict[str, str] = node.data.get("branches", {})

    if not branches:
        raise CompilationError(f"CONDITION node {node.id!r} requires 'branches' in data")

    default_branch = next(iter(branches.values()))

    def _route(inputs: dict[str, Any]) -> str:
        value = str(inputs.get(condition_key, ""))
        return branches.get(value, default_branch)

    return BranchStep(_route)


def _compile_memory(node: GraphNode) -> CallableStep:
    """Compile a MEMORY node.

    Supports actions: ``store``, ``retrieve``, ``clear``.
    Operates on the PipelineContext's memory manager if available.
    """
    action = node.data.get("memory_action", "retrieve")

    async def _memory_op(context: PipelineContext, inputs: dict[str, Any]) -> Any:
        memory = context.memory
        if memory is None:
            logger.warning("MEMORY node executed but no MemoryManager on context")
            return inputs.get("input")

        key = inputs.get("key", "default")

        if action == "store":
            value = inputs.get("input", inputs.get("value"))
            memory.set_fact(key, value)
            return value
        elif action == "clear":
            memory.working.delete(key)
            return None
        else:
            # retrieve
            return memory.get_fact(key)

    return CallableStep(_memory_op)


def _compile_validator(node: GraphNode) -> CallableStep:
    """Compile a VALIDATOR node.

    Validates input against a rule and passes through if valid,
    raises on failure.
    """
    rule = node.data.get("validation_rule", "")

    async def _validate(context: PipelineContext, inputs: dict[str, Any]) -> Any:
        value = inputs.get("input", context.inputs)

        if rule == "not_empty":
            if not value:
                raise ValueError(f"Validation failed: value is empty (node {node.id!r})")
        elif rule == "is_string":
            if not isinstance(value, str):
                raise TypeError(f"Validation failed: expected string, got {type(value).__name__} (node {node.id!r})")
        elif rule == "is_list":
            if not isinstance(value, list):
                raise TypeError(f"Validation failed: expected list, got {type(value).__name__} (node {node.id!r})")
        elif rule == "is_dict":
            if not isinstance(value, dict):
                raise TypeError(f"Validation failed: expected dict, got {type(value).__name__} (node {node.id!r})")
        elif rule and isinstance(value, dict) and rule not in value:  # custom key check
            raise KeyError(f"Validation failed: key {rule!r} missing from input (node {node.id!r})")

        return value

    return CallableStep(_validate)


def _compile_custom_code(node: GraphNode) -> CallableStep:
    """Compile a CUSTOM_CODE node.

    The ``code`` field must define an async function named ``execute``
    with signature ``async def execute(context, inputs) -> Any``.

    Security note: This executes user-authored code within the local
    Studio IDE, analogous to Jupyter notebook cell execution.
    """
    code = node.data.get("code", "")
    if not code:
        raise CompilationError(f"CUSTOM_CODE node {node.id!r} requires 'code' in data")

    # Compile the code at graph compile time so syntax errors surface early
    try:
        compiled = compile(code, f"<custom_code:{node.id}>", "exec")
    except SyntaxError as exc:
        raise CompilationError(f"Syntax error in CUSTOM_CODE node {node.id!r}: {exc}") from exc

    namespace: dict[str, Any] = {}
    exec(compiled, namespace)  # noqa: S102

    execute_fn = namespace.get("execute")
    if execute_fn is None or not callable(execute_fn):
        raise CompilationError(f"CUSTOM_CODE node {node.id!r} must define 'async def execute(context, inputs) -> Any'")

    # At this point execute_fn is a callable; capture a typed reference
    _fn: Callable[..., Any] = execute_fn

    async def _run_custom(context: PipelineContext, inputs: dict[str, Any]) -> Any:
        result = _fn(context, inputs)
        if hasattr(result, "__await__"):
            return await result
        return result

    return CallableStep(_run_custom)


def _compile_input(node: GraphNode) -> CallableStep:
    """Compile an Input boundary node.

    The Input node is a pass-through: it receives pipeline inputs and
    forwards them to downstream nodes.  Validation against the schema
    (if configured) happens at the API boundary, not here.
    """
    config = InputNodeConfig(**node.data)
    _ = config  # validation happens at construction time

    async def _input_step(context: PipelineContext, inputs: dict[str, Any]) -> Any:
        return inputs.get("input", context.inputs)

    return CallableStep(_input_step)


def _compile_output(node: GraphNode) -> CallableStep:
    """Compile an Output boundary node.

    The Output node collects the final result.  Destination routing
    (queue publish, webhook POST, etc.) is handled by the ProjectRuntime
    after pipeline execution completes, not within the step itself.
    """
    config = OutputNodeConfig(**node.data)

    async def _output_step(context: PipelineContext, inputs: dict[str, Any]) -> Any:
        context.metadata["_output_config"] = config.model_dump()
        return inputs.get("input", inputs)

    return CallableStep(_output_step)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_NODE_COMPILERS: dict[NodeType, Any] = {
    NodeType.AGENT: _compile_agent,
    NodeType.TOOL: _compile_tool,
    NodeType.REASONING: _compile_reasoning,
    NodeType.PIPELINE_STEP: _compile_pipeline_step,
    NodeType.FAN_OUT: _compile_fan_out,
    NodeType.FAN_IN: _compile_fan_in,
    NodeType.CONDITION: _compile_condition,
    NodeType.MEMORY: _compile_memory,
    NodeType.VALIDATOR: _compile_validator,
    NodeType.CUSTOM_CODE: _compile_custom_code,
    NodeType.INPUT: _compile_input,
    NodeType.OUTPUT: _compile_output,
}
