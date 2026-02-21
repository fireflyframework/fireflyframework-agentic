"""Tests for Input/Output node compilation."""

from __future__ import annotations

import pytest

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


def _input_node(trigger_type: str = "manual", **extra: object) -> GraphNode:
    return GraphNode(
        id="input_1",
        type=NodeType.INPUT,
        label="Input",
        position={"x": 0, "y": 200},
        data={"trigger_type": trigger_type, **extra},
    )


def _output_node(destination_type: str = "response", **extra: object) -> GraphNode:
    return GraphNode(
        id="output_1",
        type=NodeType.OUTPUT,
        label="Output",
        position={"x": 900, "y": 200},
        data={"destination_type": destination_type, **extra},
    )


def _step_node(node_id: str = "step_1") -> GraphNode:
    """A simple PIPELINE_STEP node that requires no external dependencies."""
    return GraphNode(
        id=node_id,
        type=NodeType.PIPELINE_STEP,
        label="Step",
        position={"x": 300, "y": 200},
        data={},
    )


class TestInputOutputCompilation:
    def test_input_to_step_to_output_compiles(self):
        graph = GraphModel(
            nodes=[_input_node(), _step_node(), _output_node()],
            edges=[
                GraphEdge(id="e1", source="input_1", target="step_1"),
                GraphEdge(id="e2", source="step_1", target="output_1"),
            ],
        )
        engine = compile_graph(graph)
        assert engine is not None

    def test_multiple_input_nodes_raises(self):
        graph = GraphModel(
            nodes=[
                _input_node(),
                GraphNode(id="input_2", type=NodeType.INPUT, label="Input 2",
                          position={"x": 0, "y": 400}, data={"trigger_type": "http"}),
                _step_node(),
                _output_node(),
            ],
            edges=[
                GraphEdge(id="e1", source="input_1", target="step_1"),
                GraphEdge(id="e2", source="input_2", target="step_1"),
                GraphEdge(id="e3", source="step_1", target="output_1"),
            ],
        )
        with pytest.raises(CompilationError, match="exactly one Input node"):
            compile_graph(graph)

    def test_no_output_node_raises(self):
        graph = GraphModel(
            nodes=[_input_node(), _step_node()],
            edges=[GraphEdge(id="e1", source="input_1", target="step_1")],
        )
        with pytest.raises(CompilationError, match="at least one Output node"):
            compile_graph(graph)

    def test_input_node_with_schema_validates(self):
        graph = GraphModel(
            nodes=[
                _input_node(schema={"type": "object", "properties": {"text": {"type": "string"}}}),
                _step_node(),
                _output_node(),
            ],
            edges=[
                GraphEdge(id="e1", source="input_1", target="step_1"),
                GraphEdge(id="e2", source="step_1", target="output_1"),
            ],
        )
        engine = compile_graph(graph)
        assert engine is not None

    def test_pipeline_without_io_nodes_still_works(self):
        """Backward compatibility: pipelines without IO nodes should still compile."""
        graph = GraphModel(
            nodes=[_step_node("s1"), GraphNode(
                id="s2", type=NodeType.PIPELINE_STEP, label="Step 2",
                position={"x": 300, "y": 200},
                data={},
            )],
            edges=[GraphEdge(id="e1", source="s1", target="s2")],
        )
        engine = compile_graph(graph)
        assert engine is not None
