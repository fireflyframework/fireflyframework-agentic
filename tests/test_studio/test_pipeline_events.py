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

"""Tests for pipeline execution events and checkpoint creation.

Verifies that :class:`StudioEventHandler` collects events in correct
order during pipeline execution, and that checkpoints can be created
for debug mode.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fireflyframework_genai.studio.codegen.models import (
    GraphEdge,
    GraphModel,
    GraphNode,
    NodeType,
)
from fireflyframework_genai.studio.execution.checkpoint import CheckpointManager
from fireflyframework_genai.studio.execution.compiler import compile_graph
from fireflyframework_genai.studio.execution.runner import StudioEventHandler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_POS = {"x": 0.0, "y": 0.0}


def _make_graph(
    nodes: list[GraphNode],
    edges: list[GraphEdge] | None = None,
) -> GraphModel:
    return GraphModel(nodes=nodes, edges=edges or [])


def _make_node(
    node_id: str,
    node_type: NodeType,
    label: str = "test-node",
    data: dict | None = None,
) -> GraphNode:
    return GraphNode(id=node_id, type=node_type, label=label, position=_POS, data=data or {})


def _mock_agent(name: str = "mock-agent") -> MagicMock:
    agent = MagicMock()
    agent.name = name
    mock_result = MagicMock()
    mock_result.output = f"output from {name}"
    agent.run = AsyncMock(return_value=mock_result)
    return agent


# ---------------------------------------------------------------------------
# Event streaming tests
# ---------------------------------------------------------------------------


class TestExecutionEventsStream:
    """Run a compiled graph, verify StudioEventHandler collects events in order."""

    async def test_events_include_start_complete_and_pipeline_complete(self):
        handler = StudioEventHandler()

        # Simple two-node pipeline
        nodes = [
            _make_node("a", NodeType.PIPELINE_STEP, data={}),
            _make_node("b", NodeType.PIPELINE_STEP, data={}),
        ]
        edges = [GraphEdge(id="e1", source="a", target="b")]
        graph = _make_graph(nodes, edges)

        engine = compile_graph(graph, event_handler=handler)
        result = await engine.run(inputs="test")

        assert result.success is True

        events = handler.drain_events()
        types = [e["type"] for e in events]

        # Should have node_start and node_complete for each node, plus pipeline_complete
        assert types.count("node_start") >= 2
        assert types.count("node_complete") >= 2
        assert "pipeline_complete" in types

        # pipeline_complete should be last
        assert types[-1] == "pipeline_complete"

    async def test_event_order_matches_topology(self):
        handler = StudioEventHandler()

        nodes = [
            _make_node("first", NodeType.PIPELINE_STEP, data={}),
            _make_node("second", NodeType.PIPELINE_STEP, data={}),
            _make_node("third", NodeType.PIPELINE_STEP, data={}),
        ]
        edges = [
            GraphEdge(id="e1", source="first", target="second"),
            GraphEdge(id="e2", source="second", target="third"),
        ]
        graph = _make_graph(nodes, edges)

        engine = compile_graph(graph, event_handler=handler)
        await engine.run(inputs="chain")

        events = handler.drain_events()
        node_starts = [e["node_id"] for e in events if e["type"] == "node_start"]

        # First node should start before second, second before third
        assert node_starts.index("first") < node_starts.index("second")
        assert node_starts.index("second") < node_starts.index("third")

    async def test_pipeline_complete_event_contains_success_flag(self):
        handler = StudioEventHandler()

        node = _make_node("solo", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])

        engine = compile_graph(graph, event_handler=handler)
        await engine.run(inputs="test")

        events = handler.drain_events()
        pc = next(e for e in events if e["type"] == "pipeline_complete")
        assert pc["success"] is True
        assert "duration_ms" in pc

    async def test_node_complete_event_contains_latency(self):
        handler = StudioEventHandler()

        node = _make_node("timed", NodeType.PIPELINE_STEP, data={})
        graph = _make_graph([node])

        engine = compile_graph(graph, event_handler=handler)
        await engine.run(inputs="test")

        events = handler.drain_events()
        nc = next(e for e in events if e["type"] == "node_complete")
        assert "latency_ms" in nc
        assert nc["latency_ms"] >= 0


class TestDebugModeCheckpoints:
    """Verify CheckpointManager receives entries during debug-like execution."""

    def test_checkpoint_creation(self):
        manager = CheckpointManager()

        # Simulate creating checkpoints as would happen during debug execution
        cp1 = manager.create(
            node_id="agent_1",
            state={"output": "hello"},
            inputs={"input": "hi"},
        )
        cp2 = manager.create(
            node_id="tool_1",
            state={"output": "search result"},
            inputs={"query": "hello"},
        )

        assert len(manager.list_all()) == 2
        assert cp1.index == 0
        assert cp2.index == 1
        assert cp1.node_id == "agent_1"
        assert cp2.node_id == "tool_1"
        assert cp1.timestamp  # Non-empty timestamp

    def test_checkpoint_fork(self):
        manager = CheckpointManager()
        manager.create(node_id="n1", state={"val": 1}, inputs={"x": "a"})

        forked = manager.fork(0, modified_state={"val": 99})
        assert forked.index == 1
        assert forked.parent_index == 0
        assert forked.branch_id is not None
        assert forked.state == {"val": 99}
        assert forked.node_id == "n1"  # Inherits from parent

    def test_checkpoint_diff(self):
        manager = CheckpointManager()
        manager.create(node_id="n1", state={"a": 1, "b": 2}, inputs={})
        manager.create(node_id="n2", state={"b": 3, "c": 4}, inputs={})

        diff = manager.diff(0, 1)
        assert "c" in diff["added"]
        assert "a" in diff["removed"]
        assert "b" in diff["changed"]


class TestErrorEventOnNodeFailure:
    """Node raises exception, verify node_error event is emitted."""

    async def test_node_error_event(self):
        handler = StudioEventHandler()

        # Validator that will fail on empty input
        node = _make_node("val", NodeType.VALIDATOR, data={"validation_rule": "not_empty"})
        graph = _make_graph([node])

        engine = compile_graph(graph, event_handler=handler)
        await engine.run(inputs="")

        events = handler.drain_events()
        error_events = [e for e in events if e["type"] == "node_error"]
        assert len(error_events) >= 1
        assert error_events[0]["node_id"] == "val"
        assert "error" in error_events[0]

    async def test_error_followed_by_pipeline_complete(self):
        handler = StudioEventHandler()

        node = _make_node("bad", NodeType.VALIDATOR, data={"validation_rule": "not_empty"})
        graph = _make_graph([node])

        engine = compile_graph(graph, event_handler=handler)
        await engine.run(inputs="")

        events = handler.drain_events()
        types = [e["type"] for e in events]

        assert "node_error" in types
        assert "pipeline_complete" in types
        # pipeline_complete comes after node_error
        assert types.index("node_error") < types.index("pipeline_complete")

    async def test_custom_code_error_event(self):
        handler = StudioEventHandler()

        code = "async def execute(context, inputs):\n    raise RuntimeError('intentional failure')\n"
        node = _make_node("broken", NodeType.CUSTOM_CODE, data={"code": code})
        graph = _make_graph([node])

        engine = compile_graph(graph, event_handler=handler)
        result = await engine.run(inputs="trigger")

        assert result.outputs["broken"].success is False

        events = handler.drain_events()
        error_events = [e for e in events if e["type"] == "node_error"]
        assert len(error_events) >= 1
        assert "intentional failure" in error_events[0]["error"]
