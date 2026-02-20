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

"""Tests for the Studio checkpoints API endpoints."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

import httpx

from fireflyframework_genai.studio.execution.checkpoint import CheckpointManager
from fireflyframework_genai.studio.server import create_studio_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a Studio app for testing."""
    return create_studio_app()


@pytest.fixture()
def checkpoint_manager(app) -> CheckpointManager:
    """Return the CheckpointManager stored on app state."""
    return app.state.checkpoint_manager


@pytest.fixture()
async def client(app):
    """Provide an async httpx client bound to the test app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/checkpoints (list)
# ---------------------------------------------------------------------------


class TestListCheckpoints:
    async def test_list_empty(self, client: httpx.AsyncClient):
        resp = await client.get("/api/checkpoints")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_after_creation(
        self,
        client: httpx.AsyncClient,
        checkpoint_manager: CheckpointManager,
    ):
        checkpoint_manager.create(node_id="agent-1", state={"key": "value"}, inputs={"prompt": "hello"})
        checkpoint_manager.create(node_id="tool-1", state={"result": 42}, inputs={"arg": "x"})

        resp = await client.get("/api/checkpoints")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert body[0]["index"] == 0
        assert body[0]["node_id"] == "agent-1"
        assert body[0]["state"] == {"key": "value"}
        assert body[1]["index"] == 1
        assert body[1]["node_id"] == "tool-1"


# ---------------------------------------------------------------------------
# GET /api/checkpoints/{index}
# ---------------------------------------------------------------------------


class TestGetCheckpoint:
    async def test_get_by_index(
        self,
        client: httpx.AsyncClient,
        checkpoint_manager: CheckpointManager,
    ):
        checkpoint_manager.create(node_id="agent-1", state={"key": "value"}, inputs={"prompt": "hello"})

        resp = await client.get("/api/checkpoints/0")
        assert resp.status_code == 200
        body = resp.json()
        assert body["index"] == 0
        assert body["node_id"] == "agent-1"
        assert body["state"] == {"key": "value"}
        assert body["inputs"] == {"prompt": "hello"}
        assert body["timestamp"] != ""
        assert body["branch_id"] is None
        assert body["parent_index"] is None

    async def test_get_out_of_range(self, client: httpx.AsyncClient):
        resp = await client.get("/api/checkpoints/99")
        assert resp.status_code == 404

    async def test_get_negative_index(self, client: httpx.AsyncClient):
        resp = await client.get("/api/checkpoints/-1")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/checkpoints/fork
# ---------------------------------------------------------------------------


class TestForkCheckpoint:
    async def test_fork_creates_new_checkpoint(
        self,
        client: httpx.AsyncClient,
        checkpoint_manager: CheckpointManager,
    ):
        checkpoint_manager.create(node_id="agent-1", state={"key": "value"}, inputs={"prompt": "hello"})

        resp = await client.post(
            "/api/checkpoints/fork",
            json={"from_index": 0, "modified_state": {"key": "modified"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["index"] == 1
        assert body["node_id"] == "agent-1"  # Inherited from parent
        assert body["state"] == {"key": "modified"}
        assert body["inputs"] == {"prompt": "hello"}  # Inherited from parent
        assert body["branch_id"] is not None
        assert body["parent_index"] == 0

    async def test_fork_invalid_index(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/api/checkpoints/fork",
            json={"from_index": 99, "modified_state": {}},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/checkpoints/diff
# ---------------------------------------------------------------------------


class TestDiffCheckpoints:
    async def test_diff_two_checkpoints(
        self,
        client: httpx.AsyncClient,
        checkpoint_manager: CheckpointManager,
    ):
        checkpoint_manager.create(
            node_id="agent-1",
            state={"a": 1, "b": 2, "c": 3},
            inputs={},
        )
        checkpoint_manager.create(
            node_id="agent-2",
            state={"b": 99, "c": 3, "d": 4},
            inputs={},
        )

        resp = await client.post(
            "/api/checkpoints/diff",
            json={"index_a": 0, "index_b": 1},
        )
        assert resp.status_code == 200
        body = resp.json()

        # "a" was removed, "d" was added, "b" changed, "c" unchanged
        assert sorted(body["added"]) == ["d"]
        assert sorted(body["removed"]) == ["a"]
        assert sorted(body["changed"]) == ["b"]

    async def test_diff_invalid_index(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/api/checkpoints/diff",
            json={"index_a": 0, "index_b": 1},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/checkpoints
# ---------------------------------------------------------------------------


class TestClearCheckpoints:
    async def test_clear_removes_all(
        self,
        client: httpx.AsyncClient,
        checkpoint_manager: CheckpointManager,
    ):
        checkpoint_manager.create(node_id="agent-1", state={"key": "value"}, inputs={})
        checkpoint_manager.create(node_id="agent-2", state={"key": "value2"}, inputs={})

        resp = await client.delete("/api/checkpoints")
        assert resp.status_code == 200
        assert resp.json() == {"status": "cleared"}

        # Confirm empty
        resp2 = await client.get("/api/checkpoints")
        assert resp2.status_code == 200
        assert resp2.json() == []
