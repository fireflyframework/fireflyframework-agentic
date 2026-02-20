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

"""Tests for the Studio registry API endpoints."""

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
# GET /api/registry/agents
# ---------------------------------------------------------------------------


class TestRegistryAgents:
    async def test_agents_returns_empty_list_when_none_registered(self, client: httpx.AsyncClient):
        resp = await client.get("/api/registry/agents")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_agents_returns_agent_info_after_registration(self, client: httpx.AsyncClient):
        from pydantic_ai.models.test import TestModel

        from fireflyframework_genai.agents.base import FireflyAgent
        from fireflyframework_genai.agents.registry import agent_registry

        agent = FireflyAgent(
            "test-agent",
            model=TestModel(),
            description="A test agent",
            version="1.0.0",
            tags=["test", "demo"],
            auto_register=False,
        )
        agent_registry.register(agent)

        resp = await client.get("/api/registry/agents")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["name"] == "test-agent"
        assert body[0]["description"] == "A test agent"
        assert body[0]["version"] == "1.0.0"
        assert body[0]["tags"] == ["test", "demo"]


# ---------------------------------------------------------------------------
# GET /api/registry/tools
# ---------------------------------------------------------------------------


class TestRegistryTools:
    async def test_tools_returns_empty_list_when_none_registered(self, client: httpx.AsyncClient):
        resp = await client.get("/api/registry/tools")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_tools_returns_tool_info_after_registration(self, client: httpx.AsyncClient):
        from fireflyframework_genai.tools.base import BaseTool
        from fireflyframework_genai.tools.registry import tool_registry

        class DummyTool(BaseTool):
            async def _execute(self, **kwargs):
                return "ok"

        tool = DummyTool("dummy-tool", description="A dummy tool", tags=["test"])
        tool_registry.register(tool)

        resp = await client.get("/api/registry/tools")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["name"] == "dummy-tool"
        assert body[0]["description"] == "A dummy tool"


# ---------------------------------------------------------------------------
# GET /api/registry/patterns
# ---------------------------------------------------------------------------


class TestRegistryPatterns:
    async def test_patterns_returns_empty_list_when_none_registered(self, client: httpx.AsyncClient):
        resp = await client.get("/api/registry/patterns")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_patterns_returns_list_after_registration(self, client: httpx.AsyncClient):
        from fireflyframework_genai.reasoning.registry import reasoning_registry

        reasoning_registry.register("chain-of-thought", object())
        reasoning_registry.register("react", object())

        resp = await client.get("/api/registry/patterns")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 2
        # Patterns endpoint returns dicts with a "name" key
        names = [p["name"] for p in body]
        assert "chain-of-thought" in names
        assert "react" in names
