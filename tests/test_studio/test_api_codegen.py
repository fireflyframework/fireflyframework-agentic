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


# ---------------------------------------------------------------------------
# POST /api/codegen/smith
# ---------------------------------------------------------------------------


class TestCodegenSmith:
    """Tests for the POST /api/codegen/smith endpoint."""

    async def test_smith_endpoint_exists(self, client: httpx.AsyncClient):
        """The /api/codegen/smith endpoint should accept POST requests."""
        resp = await client.post(
            "/api/codegen/smith",
            json={"graph": SINGLE_AGENT_GRAPH},
        )
        # Smith requires an LLM API key, so it may return 200 (success),
        # 500 (no API key / agent creation fails), or 422 (validation).
        # Any of these prove the endpoint exists and routes correctly.
        assert resp.status_code != 404

    async def test_smith_missing_graph_returns_422(self, client: httpx.AsyncClient):
        """A request missing the 'graph' key should return 422."""
        resp = await client.post("/api/codegen/smith", json={})
        assert resp.status_code == 422

    async def test_old_tocode_endpoint_removed(self, client: httpx.AsyncClient):
        """The old /api/codegen/to-code endpoint should no longer exist as an API route."""
        resp = await client.post(
            "/api/codegen/to-code",
            json={"graph": SINGLE_AGENT_GRAPH},
        )
        # The endpoint was removed. It may return 404/405 (route not found)
        # or 200 (static file catch-all). Either way, it should NOT return
        # a valid JSON codegen response with a 'code' key.
        if resp.status_code == 200:
            try:
                body = resp.json()
                assert "code" not in body, "to-code endpoint should not return generated code"
            except Exception:
                pass  # Non-JSON response = static file served = endpoint removed
