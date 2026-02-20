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

"""Tests for the Studio execution event handler and WebSocket API."""

from __future__ import annotations

import asyncio

import pytest

from fireflyframework_genai.pipeline.engine import PipelineEventHandler
from fireflyframework_genai.studio.execution.runner import StudioEventHandler

pytest.importorskip("fastapi", reason="fastapi not installed")


# ---------------------------------------------------------------------------
# StudioEventHandler — Protocol compliance
# ---------------------------------------------------------------------------


class TestStudioEventHandlerProtocol:
    def test_implements_pipeline_event_handler(self):
        handler = StudioEventHandler()
        assert isinstance(handler, PipelineEventHandler)

    def test_has_on_node_start(self):
        handler = StudioEventHandler()
        assert callable(getattr(handler, "on_node_start", None))

    def test_has_on_node_complete(self):
        handler = StudioEventHandler()
        assert callable(getattr(handler, "on_node_complete", None))

    def test_has_on_node_error(self):
        handler = StudioEventHandler()
        assert callable(getattr(handler, "on_node_error", None))

    def test_has_on_node_skip(self):
        handler = StudioEventHandler()
        assert callable(getattr(handler, "on_node_skip", None))

    def test_has_on_pipeline_complete(self):
        handler = StudioEventHandler()
        assert callable(getattr(handler, "on_pipeline_complete", None))


# ---------------------------------------------------------------------------
# StudioEventHandler — Event collection
# ---------------------------------------------------------------------------


class TestStudioEventHandlerCollection:
    async def test_on_node_start_collects_event(self):
        handler = StudioEventHandler()
        await handler.on_node_start("node_1", "my_pipeline")

        events = handler.drain_events()
        assert len(events) == 1
        assert events[0]["type"] == "node_start"
        assert events[0]["node_id"] == "node_1"
        assert events[0]["pipeline_name"] == "my_pipeline"

    async def test_on_node_complete_collects_event(self):
        handler = StudioEventHandler()
        await handler.on_node_complete("node_1", "my_pipeline", 42.5)

        events = handler.drain_events()
        assert len(events) == 1
        assert events[0]["type"] == "node_complete"
        assert events[0]["node_id"] == "node_1"
        assert events[0]["pipeline_name"] == "my_pipeline"
        assert events[0]["latency_ms"] == 42.5

    async def test_on_node_error_collects_event(self):
        handler = StudioEventHandler()
        await handler.on_node_error("node_1", "my_pipeline", "something broke")

        events = handler.drain_events()
        assert len(events) == 1
        assert events[0]["type"] == "node_error"
        assert events[0]["node_id"] == "node_1"
        assert events[0]["pipeline_name"] == "my_pipeline"
        assert events[0]["error"] == "something broke"

    async def test_on_node_skip_collects_event(self):
        handler = StudioEventHandler()
        await handler.on_node_skip("node_1", "my_pipeline", "upstream failed")

        events = handler.drain_events()
        assert len(events) == 1
        assert events[0]["type"] == "node_skip"
        assert events[0]["node_id"] == "node_1"
        assert events[0]["pipeline_name"] == "my_pipeline"
        assert events[0]["reason"] == "upstream failed"

    async def test_on_pipeline_complete_collects_event(self):
        handler = StudioEventHandler()
        await handler.on_pipeline_complete("my_pipeline", True, 1234.5)

        events = handler.drain_events()
        assert len(events) == 1
        assert events[0]["type"] == "pipeline_complete"
        assert events[0]["pipeline_name"] == "my_pipeline"
        assert events[0]["success"] is True
        assert events[0]["duration_ms"] == 1234.5

    async def test_multiple_events_collected_in_order(self):
        handler = StudioEventHandler()
        await handler.on_node_start("a", "pipe")
        await handler.on_node_complete("a", "pipe", 10.0)
        await handler.on_node_start("b", "pipe")
        await handler.on_node_error("b", "pipe", "fail")

        events = handler.drain_events()
        assert len(events) == 4
        assert events[0]["type"] == "node_start"
        assert events[0]["node_id"] == "a"
        assert events[1]["type"] == "node_complete"
        assert events[1]["node_id"] == "a"
        assert events[2]["type"] == "node_start"
        assert events[2]["node_id"] == "b"
        assert events[3]["type"] == "node_error"
        assert events[3]["node_id"] == "b"


# ---------------------------------------------------------------------------
# StudioEventHandler — drain_events
# ---------------------------------------------------------------------------


class TestStudioEventHandlerDrain:
    async def test_drain_returns_empty_list_when_no_events(self):
        handler = StudioEventHandler()
        events = handler.drain_events()
        assert events == []

    async def test_drain_clears_queue(self):
        handler = StudioEventHandler()
        await handler.on_node_start("node_1", "pipe")

        first_drain = handler.drain_events()
        assert len(first_drain) == 1

        second_drain = handler.drain_events()
        assert second_drain == []

    async def test_drain_returns_new_events_after_clear(self):
        handler = StudioEventHandler()
        await handler.on_node_start("a", "pipe")
        handler.drain_events()

        await handler.on_node_start("b", "pipe")
        events = handler.drain_events()
        assert len(events) == 1
        assert events[0]["node_id"] == "b"


# ---------------------------------------------------------------------------
# StudioEventHandler — wait_for_event
# ---------------------------------------------------------------------------


class TestStudioEventHandlerWait:
    async def test_wait_returns_when_event_available(self):
        handler = StudioEventHandler()

        async def _produce():
            await asyncio.sleep(0.05)
            await handler.on_node_start("x", "pipe")

        asyncio.create_task(_produce())
        await handler.wait_for_event(timeout=2.0)
        events = handler.drain_events()
        assert len(events) == 1

    async def test_wait_times_out_when_no_event(self):
        handler = StudioEventHandler()
        # Should not raise, just return after timeout
        await handler.wait_for_event(timeout=0.05)
        events = handler.drain_events()
        assert events == []


# ---------------------------------------------------------------------------
# WebSocket endpoint — integration test
# ---------------------------------------------------------------------------


class TestExecutionWebSocket:
    @pytest.fixture()
    def app(self):
        from fireflyframework_genai.studio.server import create_studio_app

        return create_studio_app()

    async def test_websocket_run_with_graph(self, app):
        """Test that the WebSocket endpoint compiles and runs a graph,
        returning execution events and a pipeline_result."""
        from starlette.testclient import TestClient

        graph = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "pipeline_step",
                    "label": "Step 1",
                    "position": {"x": 0, "y": 0},
                    "data": {},
                }
            ],
            "edges": [],
            "metadata": {"name": "test-pipeline"},
        }
        client = TestClient(app)
        with client.websocket_connect("/ws/execution") as ws:
            ws.send_json({"action": "run", "graph": graph, "inputs": "hello"})
            # Collect messages until pipeline_result
            messages = []
            for _ in range(20):
                msg = ws.receive_json()
                messages.append(msg)
                if msg["type"] == "pipeline_result":
                    break
            result = messages[-1]
            assert result["type"] == "pipeline_result"
            assert result["success"] is True

    async def test_websocket_run_missing_graph(self, app):
        """Test that a run action without a graph returns an error."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        with client.websocket_connect("/ws/execution") as ws:
            ws.send_json({"action": "run"})
            data = ws.receive_json()
            assert data["type"] == "error"

    async def test_websocket_unknown_action(self, app):
        """Test that unknown actions get an error response."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        with client.websocket_connect("/ws/execution") as ws:
            ws.send_json({"action": "unknown_action"})
            data = ws.receive_json()
            assert data["type"] == "error"
