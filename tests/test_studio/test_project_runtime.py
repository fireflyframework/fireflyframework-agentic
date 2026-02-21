"""Tests for ProjectRuntime lifecycle management."""

from __future__ import annotations

import pytest

from fireflyframework_genai.studio.codegen.models import (
    GraphEdge,
    GraphModel,
    GraphNode,
    NodeType,
)
from fireflyframework_genai.studio.runtime import ProjectRuntime


def _simple_graph() -> GraphModel:
    return GraphModel(
        nodes=[
            GraphNode(id="input_1", type=NodeType.INPUT, label="Input",
                      position={"x": 0, "y": 200}, data={"trigger_type": "manual"}),
            GraphNode(id="agent_1", type=NodeType.AGENT, label="Agent",
                      position={"x": 300, "y": 200},
                      data={"model": "openai:gpt-4o", "instructions": "Echo input."}),
            GraphNode(id="output_1", type=NodeType.OUTPUT, label="Output",
                      position={"x": 600, "y": 200}, data={"destination_type": "response"}),
        ],
        edges=[
            GraphEdge(id="e1", source="input_1", target="agent_1"),
            GraphEdge(id="e2", source="agent_1", target="output_1"),
        ],
    )


class TestProjectRuntime:
    def test_create_runtime(self):
        rt = ProjectRuntime("test-project")
        assert rt.project_name == "test-project"
        assert rt.status == "stopped"

    async def test_start_with_manual_trigger(self):
        rt = ProjectRuntime("test-project")
        await rt.start(_simple_graph())
        assert rt.status == "running"
        await rt.stop()
        assert rt.status == "stopped"

    def test_get_status(self):
        rt = ProjectRuntime("test-project")
        status = rt.get_status()
        assert status["status"] == "stopped"
        assert status["consumers"] == 0
        assert status["scheduler_active"] is False

    async def test_start_stop_idempotent(self):
        rt = ProjectRuntime("test-project")
        await rt.start(_simple_graph())
        assert rt.status == "running"
        await rt.stop()
        assert rt.status == "stopped"
        # Stopping again should be safe
        await rt.stop()
        assert rt.status == "stopped"

    async def test_execute_without_graph_raises(self):
        rt = ProjectRuntime("test-project")
        with pytest.raises(RuntimeError, match="has no graph loaded"):
            await rt.execute({"text": "hello"})
