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

"""Integration tests for the REST exposure layer.

Tests the full FastAPI app factory, agent router, health endpoints,
and middleware wiring using ``httpx.AsyncClient`` with ``ASGITransport``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

import httpx

from fireflyframework_agentic.exposure.rest.app import create_agentic_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(**kwargs):
    """Create a test app with lifespan disabled."""
    from fastapi import FastAPI

    from fireflyframework_agentic.exposure.rest.health import create_health_router
    from fireflyframework_agentic.exposure.rest.router import create_agent_router

    app = FastAPI(title="test")
    app.include_router(create_health_router())
    app.include_router(create_agent_router())
    return app


@pytest.fixture()
def app():
    """Provide a minimal test application."""
    return _make_app()


@pytest.fixture()
async def client(app):
    """Provide an async httpx client bound to the test app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    async def test_health(self, client: httpx.AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "agents" in body

    async def test_readiness(self, client: httpx.AsyncClient):
        resp = await client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    async def test_liveness(self, client: httpx.AsyncClient):
        resp = await client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"


# ---------------------------------------------------------------------------
# Agent router
# ---------------------------------------------------------------------------


class TestAgentRouter:
    async def test_list_agents(self, client: httpx.AsyncClient):
        resp = await client.get("/agents/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_run_missing_agent_returns_404(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/agents/nonexistent/run",
            json={"prompt": "hello"},
        )
        assert resp.status_code == 404

    async def test_stream_missing_agent_returns_404(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/agents/nonexistent/stream",
            json={"prompt": "hello"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Conversation endpoints
# ---------------------------------------------------------------------------


class TestConversationEndpoints:
    async def test_create_conversation(self, client: httpx.AsyncClient):
        resp = await client.post("/agents/conversations")
        assert resp.status_code == 200
        body = resp.json()
        assert "conversation_id" in body

    async def test_get_conversation(self, client: httpx.AsyncClient):
        # First create one
        create_resp = await client.post("/agents/conversations")
        cid = create_resp.json()["conversation_id"]

        resp = await client.get(f"/agents/conversations/{cid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation_id"] == cid
        assert body["message_count"] == 0

    async def test_delete_conversation(self, client: httpx.AsyncClient):
        create_resp = await client.post("/agents/conversations")
        cid = create_resp.json()["conversation_id"]

        resp = await client.delete(f"/agents/conversations/{cid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cleared"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


class TestAppFactory:
    def test_create_agentic_app_returns_fastapi(self):
        """Verify the factory produces a FastAPI instance with expected routes."""
        from fastapi import FastAPI

        app = create_agentic_app(cors=False, request_id=False)
        assert isinstance(app, FastAPI)

        # Should have health and agent routes
        paths = {r.path for r in app.routes}
        assert "/health" in paths
        assert "/agents/" in paths

    def test_create_agentic_app_rate_limit(self):
        """Verify rate-limit middleware wiring doesn't crash."""
        app = create_agentic_app(rate_limit=True, cors=False, request_id=False)
        assert app is not None

    def test_create_agentic_app_rate_limit_custom(self):
        """Verify custom rate-limit config dict is accepted."""
        app = create_agentic_app(
            rate_limit={"max_requests": 10, "window_seconds": 30},
            cors=False,
            request_id=False,
        )
        assert app is not None
