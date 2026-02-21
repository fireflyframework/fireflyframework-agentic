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

"""Tests for the GraphQL API endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest

strawberry = pytest.importorskip("strawberry", reason="strawberry-graphql not installed")
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
    """Provide an async httpx client bound to the test app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestGraphQLQueries:
    async def test_graphql_projects_query_empty(self, client: httpx.AsyncClient):
        """Querying projects on a fresh instance returns an empty list."""
        resp = await client.post(
            "/api/graphql",
            json={"query": "{ projects { name description createdAt } }"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["projects"] == []

    async def test_graphql_projects_query_after_create(self, client: httpx.AsyncClient):
        """Creating a project via REST and querying via GraphQL returns it."""
        # Create a project via the REST API
        create_resp = await client.post(
            "/api/projects", json={"name": "gql-test", "description": "GraphQL test"}
        )
        assert create_resp.status_code == 200

        resp = await client.post(
            "/api/graphql",
            json={"query": "{ projects { name description } }"},
        )
        assert resp.status_code == 200
        body = resp.json()
        projects = body["data"]["projects"]
        assert len(projects) == 1
        assert projects[0]["name"] == "gql-test"
        assert projects[0]["description"] == "GraphQL test"

    async def test_graphql_project_by_name(self, client: httpx.AsyncClient):
        """Querying a single project by name returns it."""
        await client.post(
            "/api/projects", json={"name": "single-test", "description": "Single"}
        )

        resp = await client.post(
            "/api/graphql",
            json={
                "query": '{ project(name: "single-test") { name description } }'
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["project"]["name"] == "single-test"

    async def test_graphql_project_not_found(self, client: httpx.AsyncClient):
        """Querying a non-existent project returns null."""
        resp = await client.post(
            "/api/graphql",
            json={
                "query": '{ project(name: "nonexistent") { name } }'
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["project"] is None

    async def test_graphql_runtime_status_stopped(self, client: httpx.AsyncClient):
        """Runtime status for a project with no active runtime is 'stopped'."""
        resp = await client.post(
            "/api/graphql",
            json={
                "query": '{ runtimeStatus(project: "any-project") { project status consumers schedulerActive } }'
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        status = body["data"]["runtimeStatus"]
        assert status["project"] == "any-project"
        assert status["status"] == "stopped"
        assert status["consumers"] == 0
        assert status["schedulerActive"] is False


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


class TestGraphQLIntrospection:
    async def test_graphql_introspection(self, client: httpx.AsyncClient):
        """Introspection query returns type information."""
        resp = await client.post(
            "/api/graphql",
            json={"query": "{ __schema { types { name } } }"},
        )
        assert resp.status_code == 200
        body = resp.json()
        type_names = [t["name"] for t in body["data"]["__schema"]["types"]]
        assert "Project" in type_names
        assert "RuntimeStatus" in type_names
        assert "ExecutionResult" in type_names

    async def test_graphql_query_type_fields(self, client: httpx.AsyncClient):
        """The Query type exposes expected field names."""
        resp = await client.post(
            "/api/graphql",
            json={
                "query": '{ __type(name: "Query") { fields { name } } }'
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        field_names = [f["name"] for f in body["data"]["__type"]["fields"]]
        assert "projects" in field_names
        assert "project" in field_names
        assert "runtimeStatus" in field_names


# ---------------------------------------------------------------------------
# Mutation tests
# ---------------------------------------------------------------------------


class TestGraphQLMutations:
    async def test_run_pipeline_missing_project(self, client: httpx.AsyncClient):
        """Running a pipeline for a non-existent project returns error status."""
        resp = await client.post(
            "/api/graphql",
            json={
                "query": 'mutation { runPipeline(project: "nope", input: "hello") { executionId status result } }'
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body["data"]["runPipeline"]
        assert result["status"] == "error"
        assert "not found" in result["result"].lower()

    async def test_run_pipeline_no_pipeline_saved(self, client: httpx.AsyncClient):
        """Running a pipeline when no pipeline JSON exists returns error."""
        await client.post(
            "/api/projects", json={"name": "empty-proj"}
        )
        resp = await client.post(
            "/api/graphql",
            json={
                "query": 'mutation { runPipeline(project: "empty-proj", input: "test") { executionId status result } }'
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body["data"]["runPipeline"]
        assert result["status"] == "error"
        assert result["executionId"] is not None


# ---------------------------------------------------------------------------
# Fallback when strawberry is missing
# ---------------------------------------------------------------------------


class TestGraphQLFallback:
    def test_fallback_router_created_when_strawberry_missing(self, monkeypatch: pytest.MonkeyPatch):
        """When strawberry import fails, a fallback APIRouter is returned."""
        import builtins

        original_import = builtins.__import__

        def _mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "strawberry" or name.startswith("strawberry."):
                raise ImportError("mocked: no strawberry")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        # Need to reimport to trigger the fallback path
        from importlib import reload

        import fireflyframework_genai.studio.api.graphql_api as gql_mod

        reload(gql_mod)

        from fireflyframework_genai.studio.projects import ProjectManager
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            pm = ProjectManager(Path(td))
            router = gql_mod.create_graphql_router(pm)

        # Restore the module
        reload(gql_mod)

        from fastapi import APIRouter

        assert isinstance(router, APIRouter)
