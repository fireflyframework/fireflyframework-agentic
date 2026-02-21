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

"""Tests for per-project auto-generated API endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

import httpx

from fireflyframework_genai.studio.config import StudioConfig
from fireflyframework_genai.studio.server import create_studio_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path: Path):
    """Create a Studio app with projects_dir pointing to tmp_path."""
    cfg = StudioConfig(_env_file=None, projects_dir=tmp_path)
    return create_studio_app(config=cfg)


@pytest.fixture()
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Runtime status / start / stop
# ---------------------------------------------------------------------------


class TestProjectRuntimeAPI:
    async def test_runtime_status_returns_stopped(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "test-rt"})
        resp = await client.get("/api/projects/test-rt/runtime/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "stopped"

    async def test_runtime_status_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.get("/api/projects/nonexistent/runtime/status")
        assert resp.status_code == 404

    async def test_runtime_stop_when_not_running(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "test-stop"})
        resp = await client.post("/api/projects/test-stop/runtime/stop")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "stopped"

    async def test_runtime_stop_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.post("/api/projects/nonexistent/runtime/stop")
        assert resp.status_code == 404

    async def test_runtime_start_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.post("/api/projects/nonexistent/runtime/start")
        assert resp.status_code == 404

    async def test_runtime_start_returns_error_when_no_pipeline(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "test-start"})
        resp = await client.post("/api/projects/test-start/runtime/start")
        # No pipeline saved yet, so it should fail
        assert resp.status_code == 404

    async def test_runtime_executions_empty(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "test-exec"})
        resp = await client.get("/api/projects/test-exec/runtime/executions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["executions"] == []

    async def test_runtime_executions_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.get("/api/projects/nonexistent/runtime/executions")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Schema endpoint
# ---------------------------------------------------------------------------


class TestProjectSchemaAPI:
    async def test_project_schema_returns_empty_for_no_pipeline(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "test-schema"})
        resp = await client.get("/api/projects/test-schema/schema")
        assert resp.status_code == 200
        body = resp.json()
        assert body["trigger_type"] is None
        assert body["input_schema"] is None
        assert body["output_schema"] is None

    async def test_project_schema_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.get("/api/projects/nonexistent/schema")
        assert resp.status_code == 404

    async def test_project_schema_extracts_input_node(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "test-io-schema"})
        graph = {
            "nodes": [
                {
                    "id": "input-1",
                    "type": "input",
                    "label": "Input",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "trigger_type": "http",
                        "schema": {"type": "object", "properties": {"query": {"type": "string"}}},
                    },
                },
                {
                    "id": "output-1",
                    "type": "output",
                    "label": "Output",
                    "position": {"x": 300, "y": 0},
                    "data": {
                        "destination_type": "response",
                        "response_schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
                    },
                },
            ],
            "edges": [{"id": "e1", "source": "input-1", "target": "output-1"}],
        }
        await client.post(
            "/api/projects/test-io-schema/pipelines/main",
            json={"graph": graph},
        )
        resp = await client.get("/api/projects/test-io-schema/schema")
        assert resp.status_code == 200
        body = resp.json()
        assert body["trigger_type"] == "http"
        assert body["input_schema"]["properties"]["query"]["type"] == "string"
        assert body["output_schema"]["properties"]["answer"]["type"] == "string"


# ---------------------------------------------------------------------------
# Run endpoint
# ---------------------------------------------------------------------------


class TestProjectRunAPI:
    async def test_run_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/api/projects/nonexistent/run",
            json={"input": "hello"},
        )
        assert resp.status_code == 404

    async def test_run_returns_error_when_no_pipeline(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "test-run"})
        resp = await client.post(
            "/api/projects/test-run/run",
            json={"input": "hello"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Async run / poll endpoints
# ---------------------------------------------------------------------------


class TestProjectAsyncRunAPI:
    async def test_async_run_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/api/projects/nonexistent/run/async",
            json={"input": "hello"},
        )
        assert resp.status_code == 404

    async def test_poll_execution_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.get(
            "/api/projects/nonexistent/runs/some-id",
        )
        assert resp.status_code == 404

    async def test_poll_execution_404_for_missing_execution(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "test-poll"})
        resp = await client.get(
            "/api/projects/test-poll/runs/nonexistent-id",
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------


class TestProjectUploadAPI:
    async def test_upload_404_for_missing_project(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/api/projects/nonexistent/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 404
