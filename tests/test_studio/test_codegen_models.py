"""Tests for studio code-generation graph IR models."""

from __future__ import annotations

from fireflyframework_genai.studio.codegen.models import (
    GraphEdge,
    GraphModel,
    GraphNode,
    NodeType,
)

# ---------------------------------------------------------------------------
# NodeType enum
# ---------------------------------------------------------------------------


class TestNodeType:
    def test_has_exactly_ten_members(self) -> None:
        assert len(NodeType) == 10

    def test_expected_members(self) -> None:
        expected = {
            "agent",
            "tool",
            "reasoning",
            "pipeline_step",
            "fan_out",
            "fan_in",
            "condition",
            "memory",
            "validator",
            "custom_code",
        }
        assert {m.value for m in NodeType} == expected

    def test_is_str_enum(self) -> None:
        # StrEnum members should be usable directly as strings.
        assert NodeType.AGENT == "agent"
        assert isinstance(NodeType.TOOL, str)


# ---------------------------------------------------------------------------
# GraphNode
# ---------------------------------------------------------------------------


class TestGraphNode:
    def test_creation_with_all_fields(self) -> None:
        node = GraphNode(
            id="node-1",
            type=NodeType.AGENT,
            label="My Agent",
            position={"x": 100.0, "y": 200.0},
            data={"model": "gpt-4"},
            width=200.0,
            height=80.0,
        )
        assert node.id == "node-1"
        assert node.type is NodeType.AGENT
        assert node.label == "My Agent"
        assert node.position == {"x": 100.0, "y": 200.0}
        assert node.data == {"model": "gpt-4"}
        assert node.width == 200.0
        assert node.height == 80.0

    def test_width_and_height_default_to_none(self) -> None:
        node = GraphNode(
            id="node-2",
            type=NodeType.TOOL,
            label="Search",
            position={"x": 0, "y": 0},
            data={},
        )
        assert node.width is None
        assert node.height is None

    def test_type_accepts_string_value(self) -> None:
        """NodeType should be coerced from its string value."""
        node = GraphNode(
            id="node-3",
            type="reasoning",
            label="Thinker",
            position={"x": 50, "y": 50},
            data={"depth": 3},
        )
        assert node.type is NodeType.REASONING


# ---------------------------------------------------------------------------
# GraphEdge
# ---------------------------------------------------------------------------


class TestGraphEdge:
    def test_creation_with_defaults(self) -> None:
        edge = GraphEdge(id="edge-1", source="node-1", target="node-2")
        assert edge.id == "edge-1"
        assert edge.source == "node-1"
        assert edge.target == "node-2"
        assert edge.source_handle == "output"
        assert edge.target_handle == "input"
        assert edge.label is None

    def test_creation_with_all_fields(self) -> None:
        edge = GraphEdge(
            id="edge-2",
            source="a",
            target="b",
            source_handle="out_1",
            target_handle="in_1",
            label="on_success",
        )
        assert edge.source_handle == "out_1"
        assert edge.target_handle == "in_1"
        assert edge.label == "on_success"


# ---------------------------------------------------------------------------
# GraphModel
# ---------------------------------------------------------------------------


class TestGraphModel:
    def test_empty_graph(self) -> None:
        graph = GraphModel()
        assert graph.nodes == []
        assert graph.edges == []
        assert graph.metadata == {}

    def test_serialization_round_trip(self) -> None:
        node = GraphNode(
            id="n1",
            type=NodeType.PIPELINE_STEP,
            label="Step 1",
            position={"x": 10, "y": 20},
            data={"timeout": 30},
        )
        edge = GraphEdge(id="e1", source="n1", target="n2")
        graph = GraphModel(
            nodes=[node],
            edges=[edge],
            metadata={"version": "1.0"},
        )

        dumped = graph.model_dump()
        restored = GraphModel.model_validate(dumped)

        assert restored == graph
        assert restored.nodes[0].type is NodeType.PIPELINE_STEP
        assert restored.metadata["version"] == "1.0"

    def test_multiple_nodes_and_edges(self) -> None:
        nodes = [
            GraphNode(
                id="a",
                type=NodeType.AGENT,
                label="Agent A",
                position={"x": 0, "y": 0},
                data={},
            ),
            GraphNode(
                id="b",
                type=NodeType.TOOL,
                label="Tool B",
                position={"x": 100, "y": 0},
                data={"name": "search"},
            ),
            GraphNode(
                id="c",
                type=NodeType.CONDITION,
                label="Check",
                position={"x": 200, "y": 0},
                data={"expr": "result.ok"},
            ),
        ]
        edges = [
            GraphEdge(id="e1", source="a", target="b"),
            GraphEdge(id="e2", source="b", target="c", label="next"),
        ]
        graph = GraphModel(nodes=nodes, edges=edges)

        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2
        assert graph.edges[1].label == "next"

    def test_json_round_trip(self) -> None:
        """model_dump_json / model_validate_json should also round-trip."""
        graph = GraphModel(
            nodes=[
                GraphNode(
                    id="x",
                    type=NodeType.FAN_OUT,
                    label="Scatter",
                    position={"x": 5, "y": 5},
                    data={"parallelism": 4},
                    width=120,
                    height=60,
                ),
            ],
            edges=[],
            metadata={"author": "test"},
        )

        json_str = graph.model_dump_json()
        restored = GraphModel.model_validate_json(json_str)

        assert restored == graph
        assert restored.nodes[0].width == 120
