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

"""Tests for the Studio assistant WebSocket API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

from starlette.testclient import TestClient

from fireflyframework_genai.studio.server import create_studio_app


@pytest.fixture()
def app(monkeypatch):
    # The studio assistant agent requires an LLM API key at construction
    # time.  Provide a dummy key so that agent creation succeeds in tests.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "fireflyframework_genai.studio.assistant.agent._resolve_assistant_model",
        lambda: "openai:gpt-4o",
    )
    return create_studio_app()


class TestAssistantWebSocket:
    def test_assistant_ws_accepts_connection(self, app):
        client = TestClient(app)
        with client.websocket_connect("/ws/assistant"):
            # Connection accepted -- just close cleanly
            pass

    def test_assistant_ws_invalid_json(self, app):
        client = TestClient(app)
        with client.websocket_connect("/ws/assistant") as ws:
            ws.send_text("not json")
            response = ws.receive_json()
            assert response["type"] == "error"
            assert "Invalid JSON" in response["message"]

    def test_assistant_ws_unknown_action(self, app):
        client = TestClient(app)
        with client.websocket_connect("/ws/assistant") as ws:
            ws.send_json({"action": "unknown"})
            response = ws.receive_json()
            assert response["type"] == "error"
            assert "Unknown action" in response["message"]

    def test_assistant_ws_empty_chat_message(self, app):
        client = TestClient(app)
        with client.websocket_connect("/ws/assistant") as ws:
            ws.send_json({"action": "chat", "message": ""})
            response = ws.receive_json()
            assert response["type"] == "error"
            assert "Empty message" in response["message"]

    def test_assistant_ws_clear_history(self, app):
        client = TestClient(app)
        with client.websocket_connect("/ws/assistant") as ws:
            ws.send_json({"action": "clear_history"})
            response = ws.receive_json()
            assert response["type"] == "history_cleared"

    def test_assistant_ws_chat_streams_tokens(self, app, monkeypatch):
        """Test the chat action with a mock agent that returns a response."""

        # Mock result object returned by agent.run()
        mock_result = MagicMock()
        mock_result.output = "Hello world"
        mock_result.new_messages.return_value = []

        # Mock agent whose run returns the mock result
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        # Patch create_studio_assistant in the module where it's imported
        monkeypatch.setattr(
            "fireflyframework_genai.studio.assistant.agent.create_studio_assistant",
            lambda canvas=None: mock_agent,
        )

        client = TestClient(app)
        with client.websocket_connect("/ws/assistant") as ws:
            ws.send_json({"action": "chat", "message": "Hello"})

            tokens = []
            while True:
                resp = ws.receive_json()
                if resp["type"] == "token":
                    tokens.append(resp["content"])
                elif resp["type"] == "response_complete":
                    assert resp["full_text"] == "Hello world"
                    break
                elif resp["type"] == "error":
                    pytest.fail(f"Unexpected error: {resp['message']}")

            assert tokens == ["Hello world"]

    def test_assistant_ws_chat_fallback_on_stream_error(self, app, monkeypatch):
        """Test that chat falls back to non-streaming when run_stream fails."""

        # Mock agent whose run_stream raises, but run() succeeds
        mock_result = MagicMock()
        mock_result.output = "Fallback response"
        mock_result.new_messages.return_value = [{"role": "assistant", "content": "Fallback response"}]

        mock_agent = MagicMock()
        mock_agent.run_stream = AsyncMock(side_effect=RuntimeError("No streaming"))
        mock_agent.run = AsyncMock(return_value=mock_result)

        monkeypatch.setattr(
            "fireflyframework_genai.studio.assistant.agent.create_studio_assistant",
            lambda canvas=None: mock_agent,
        )

        client = TestClient(app)
        with client.websocket_connect("/ws/assistant") as ws:
            ws.send_json({"action": "chat", "message": "Hello"})

            responses = []
            while True:
                resp = ws.receive_json()
                responses.append(resp)
                if resp["type"] == "response_complete":
                    break
                elif resp["type"] == "error":
                    pytest.fail(f"Unexpected error: {resp['message']}")

            # Should have a token with the full response and a response_complete
            token_msgs = [r for r in responses if r["type"] == "token"]
            assert len(token_msgs) == 1
            assert token_msgs[0]["content"] == "Fallback response"
            assert responses[-1]["type"] == "response_complete"
            assert responses[-1]["full_text"] == "Fallback response"
