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

"""Tests for the Studio FastAPI server."""

from __future__ import annotations

import importlib.metadata

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
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    async def test_health_returns_200(self, client: httpx.AsyncClient):
        resp = await client.get("/api/health")
        assert resp.status_code == 200

    async def test_health_returns_status_ok(self, client: httpx.AsyncClient):
        resp = await client.get("/api/health")
        body = resp.json()
        assert body["status"] == "ok"

    async def test_health_returns_version(self, client: httpx.AsyncClient):
        resp = await client.get("/api/health")
        body = resp.json()
        expected_version = importlib.metadata.version("fireflyframework-genai")
        assert body["version"] == expected_version


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------


class TestCORSMiddleware:
    async def test_cors_allows_localhost_5173(self, client: httpx.AsyncClient):
        resp = await client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    async def test_cors_allows_localhost_4173(self, client: httpx.AsyncClient):
        resp = await client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:4173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:4173"

    async def test_cors_allows_tauri_localhost(self, client: httpx.AsyncClient):
        resp = await client.options(
            "/api/health",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "tauri://localhost"

    async def test_cors_rejects_unknown_origin(self, client: httpx.AsyncClient):
        resp = await client.options(
            "/api/health",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") is None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


class TestAppFactory:
    def test_create_studio_app_returns_fastapi(self):
        from fastapi import FastAPI

        app = create_studio_app()
        assert isinstance(app, FastAPI)

    def test_create_studio_app_has_correct_title(self):
        app = create_studio_app()
        assert app.title == "Firefly Studio"

    def test_create_studio_app_has_package_version(self):
        app = create_studio_app()
        expected_version = importlib.metadata.version("fireflyframework-genai")
        assert app.version == expected_version

    def test_create_studio_app_accepts_custom_config(self):
        from fireflyframework_genai.studio.config import StudioConfig

        config = StudioConfig(_env_file=None, port=9999)
        app = create_studio_app(config=config)
        assert app is not None
