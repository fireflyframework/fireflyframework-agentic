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

"""Tests for the tunnel API endpoints."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

import httpx

from fireflyframework_genai.studio.server import create_studio_app


@pytest.fixture()
def app():
    return create_studio_app()


@pytest.fixture()
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Tunnel API
# ---------------------------------------------------------------------------


class TestTunnelAPI:
    async def test_tunnel_status_initial(self, client):
        resp = await client.get("/api/tunnel/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["active"] is False
        assert body["url"] is None

    async def test_tunnel_stop_when_not_running(self, client):
        resp = await client.post("/api/tunnel/stop")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "stopped"


# ---------------------------------------------------------------------------
# Expose CLI subcommand
# ---------------------------------------------------------------------------


class TestExposeCLI:
    def test_expose_parser(self):
        from fireflyframework_genai.studio.cli import parse_args

        args = parse_args(["expose", "--port", "9000"])
        assert args.command == "expose"
        assert args.port == 9000

    def test_expose_parser_default_port(self):
        from fireflyframework_genai.studio.cli import parse_args

        args = parse_args(["expose"])
        assert args.command == "expose"
        assert args.port == 8470
