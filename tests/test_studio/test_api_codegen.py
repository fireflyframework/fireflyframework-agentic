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

"""Tests for the Studio code generation API endpoints."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

import httpx

from fireflyframework_genai.studio.server import create_studio_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a Studio app for testing."""
    return create_studio_app()


@pytest.fixture()
async def client(app):
    """Provide an async httpx client bound to the test app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Helper graph payloads
# ---------------------------------------------------------------------------

SINGLE_AGENT_GRAPH = {
    "nodes": [
        {
            "id": "agent_1",
            "type": "agent",
            "label": "My Agent",
            "position": {"x": 100, "y": 200},
            "data": {"model": "openai:gpt-4o", "instructions": "Be helpful."},
        },
    ],
    "edges": [],
}

TWO_NODES_WITH_EDGE_GRAPH = {
    "nodes": [
        {
            "id": "agent_1",
            "type": "agent",
            "label": "Agent One",
            "position": {"x": 0, "y": 0},
            "data": {"model": "openai:gpt-4o", "instructions": "First agent."},
        },
        {
            "id": "agent_2",
            "type": "agent",
            "label": "Agent Two",
            "position": {"x": 200, "y": 0},
            "data": {"model": "openai:gpt-4o", "instructions": "Second agent."},
        },
    ],
    "edges": [
        {
            "id": "edge_1",
            "source": "agent_1",
            "target": "agent_2",
        },
    ],
}

INVALID_GRAPH = {
    "nodes": [
        {
            "id": "bad_node",
            "type": "nonexistent_type",
            "label": "Bad",
            "position": {"x": 0, "y": 0},
            "data": {},
        },
    ],
    "edges": [],
}


# ---------------------------------------------------------------------------
# POST /api/codegen/to-code
# ---------------------------------------------------------------------------


class TestCodegenToCode:
    """Tests for the POST /api/codegen/to-code endpoint."""

    async def test_single_agent_node_returns_firefly_agent(self, client: httpx.AsyncClient):
        """A single agent node should generate code containing FireflyAgent."""
        resp = await client.post("/api/codegen/to-code", json={"graph": SINGLE_AGENT_GRAPH})
        assert resp.status_code == 200
        body = resp.json()
        assert "code" in body
        assert "FireflyAgent" in body["code"]

    async def test_two_nodes_with_edge_returns_pipeline_builder(self, client: httpx.AsyncClient):
        """Two nodes connected by an edge should generate PipelineBuilder code."""
        resp = await client.post("/api/codegen/to-code", json={"graph": TWO_NODES_WITH_EDGE_GRAPH})
        assert resp.status_code == 200
        body = resp.json()
        assert "code" in body
        assert "PipelineBuilder" in body["code"]

    async def test_invalid_graph_returns_error(self, client: httpx.AsyncClient):
        """An invalid graph (bad node type) should return 422."""
        resp = await client.post("/api/codegen/to-code", json={"graph": INVALID_GRAPH})
        assert resp.status_code == 422

    async def test_response_has_code_key(self, client: httpx.AsyncClient):
        """The response should always have a 'code' key on success."""
        resp = await client.post("/api/codegen/to-code", json={"graph": SINGLE_AGENT_GRAPH})
        assert resp.status_code == 200
        body = resp.json()
        assert "code" in body
        assert isinstance(body["code"], str)
        assert len(body["code"]) > 0

    async def test_empty_graph_returns_code(self, client: httpx.AsyncClient):
        """An empty graph (no nodes, no edges) should still return valid code."""
        resp = await client.post(
            "/api/codegen/to-code",
            json={"graph": {"nodes": [], "edges": []}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "code" in body
        assert isinstance(body["code"], str)

    async def test_missing_graph_key_returns_422(self, client: httpx.AsyncClient):
        """A request missing the 'graph' key should return 422."""
        resp = await client.post("/api/codegen/to-code", json={})
        assert resp.status_code == 422
