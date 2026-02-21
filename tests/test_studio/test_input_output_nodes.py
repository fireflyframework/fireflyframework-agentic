"""Tests for Input and Output boundary nodes."""

from __future__ import annotations

import pytest

from fireflyframework_genai.studio.codegen.models import GraphNode, NodeType


class TestInputOutputNodeTypes:
    def test_input_node_type_exists(self):
        assert NodeType.INPUT == "input"

    def test_output_node_type_exists(self):
        assert NodeType.OUTPUT == "output"

    def test_input_node_creation(self):
        node = GraphNode(
            id="input_1",
            type=NodeType.INPUT,
            label="HTTP Input",
            position={"x": 0, "y": 200},
            data={"trigger_type": "http"},
        )
        assert node.type == "input"
        assert node.data["trigger_type"] == "http"

    def test_output_node_creation(self):
        node = GraphNode(
            id="output_1",
            type=NodeType.OUTPUT,
            label="API Response",
            position={"x": 600, "y": 200},
            data={"destination_type": "response"},
        )
        assert node.type == "output"
        assert node.data["destination_type"] == "response"
