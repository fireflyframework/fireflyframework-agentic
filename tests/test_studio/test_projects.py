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

"""Tests for the Project Management API (ProjectManager + REST endpoints)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from fireflyframework_genai.studio.config import StudioConfig
from fireflyframework_genai.studio.projects import ProjectInfo, ProjectManager
from fireflyframework_genai.studio.server import create_studio_app

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager(tmp_path: Path) -> ProjectManager:
    """Create a ProjectManager backed by a temporary directory."""
    return ProjectManager(tmp_path)


# ---------------------------------------------------------------------------
# ProjectManager unit tests
# ---------------------------------------------------------------------------


class TestProjectManagerCreate:
    def test_create_returns_project_info(self, manager: ProjectManager):
        info = manager.create("my-project", description="A test project")
        assert isinstance(info, ProjectInfo)
        assert info.name == "my-project"
        assert info.description == "A test project"

    def test_create_makes_project_dir(self, manager: ProjectManager):
        info = manager.create("my-project")
        assert info.path.is_dir()

    def test_create_makes_pipelines_subdir(self, manager: ProjectManager):
        info = manager.create("my-project")
        assert (info.path / "pipelines").is_dir()

    def test_create_writes_project_json(self, manager: ProjectManager):
        info = manager.create("my-project", description="desc")
        meta_path = info.path / "project.json"
        assert meta_path.is_file()
        data = json.loads(meta_path.read_text())
        assert data["name"] == "my-project"
        assert data["description"] == "desc"
        assert "created_at" in data

    def test_create_sets_created_at(self, manager: ProjectManager):
        info = manager.create("my-project")
        assert info.created_at != ""

    def test_create_duplicate_raises(self, manager: ProjectManager):
        manager.create("dup")
        with pytest.raises(ValueError, match="Project 'dup' already exists"):
            manager.create("dup")


class TestProjectManagerList:
    def test_list_empty(self, manager: ProjectManager):
        assert manager.list_all() == []

    def test_list_returns_created_projects(self, manager: ProjectManager):
        manager.create("alpha")
        manager.create("beta")
        names = [p.name for p in manager.list_all()]
        assert names == ["alpha", "beta"]

    def test_list_sorted_by_name(self, manager: ProjectManager):
        manager.create("charlie")
        manager.create("alice")
        manager.create("bob")
        names = [p.name for p in manager.list_all()]
        assert names == ["alice", "bob", "charlie"]


class TestProjectManagerDelete:
    def test_delete_removes_directory(self, manager: ProjectManager, tmp_path: Path):
        manager.create("doomed")
        assert (tmp_path / "doomed").is_dir()
        manager.delete("doomed")
        assert not (tmp_path / "doomed").exists()

    def test_delete_removes_from_listing(self, manager: ProjectManager):
        manager.create("doomed")
        manager.delete("doomed")
        assert manager.list_all() == []

    def test_delete_nonexistent_raises(self, manager: ProjectManager):
        with pytest.raises(FileNotFoundError, match="not found"):
            manager.delete("nonexistent")


class TestProjectManagerPipelines:
    def test_save_pipeline(self, manager: ProjectManager):
        manager.create("proj")
        graph = {"nodes": [{"id": "1"}], "edges": []}
        manager.save_pipeline("proj", "my-pipeline", graph)
        pipeline_path = manager._base_dir / "proj" / "pipelines" / "my-pipeline.json"
        assert pipeline_path.is_file()

    def test_load_pipeline(self, manager: ProjectManager):
        manager.create("proj")
        graph = {"nodes": [{"id": "1"}], "edges": []}
        manager.save_pipeline("proj", "my-pipeline", graph)
        loaded = manager.load_pipeline("proj", "my-pipeline")
        assert loaded == graph

    def test_load_missing_pipeline_raises(self, manager: ProjectManager):
        manager.create("proj")
        with pytest.raises(FileNotFoundError):
            manager.load_pipeline("proj", "nonexistent")

    def test_save_pipeline_nonexistent_project_raises(self, manager: ProjectManager):
        with pytest.raises(FileNotFoundError, match="not found"):
            manager.save_pipeline("nonexistent", "pipe", {"nodes": [], "edges": []})


class TestProjectManagerPathTraversal:
    def test_create_path_traversal_raises(self, manager: ProjectManager):
        with pytest.raises(ValueError, match="Invalid path component"):
            manager.create("../../etc/evil")

    def test_delete_path_traversal_raises(self, manager: ProjectManager):
        with pytest.raises(ValueError, match="Invalid path component"):
            manager.delete("../../../tmp/evil")

    def test_save_pipeline_path_traversal_raises(self, manager: ProjectManager):
        with pytest.raises(ValueError, match="Invalid path component"):
            manager.save_pipeline("../../etc", "pipe", {})


# ---------------------------------------------------------------------------
# REST API endpoint tests
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


class TestProjectsAPI:
    async def test_list_projects_empty(self, client: httpx.AsyncClient):
        resp = await client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_project(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/api/projects",
            json={"name": "test-proj", "description": "Test project"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "test-proj"
        assert body["description"] == "Test project"

    async def test_list_projects_after_create(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "proj-a"})
        await client.post("/api/projects", json={"name": "proj-b"})
        resp = await client.get("/api/projects")
        names = [p["name"] for p in resp.json()]
        assert names == ["proj-a", "proj-b"]

    async def test_create_duplicate_returns_409(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "dup"})
        resp = await client.post("/api/projects", json={"name": "dup"})
        assert resp.status_code == 409

    async def test_delete_project(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "doomed"})
        resp = await client.delete("/api/projects/doomed")
        assert resp.status_code == 200
        listing = await client.get("/api/projects")
        assert listing.json() == []

    async def test_save_pipeline(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "proj"})
        graph = {"nodes": [{"id": "n1"}], "edges": []}
        resp = await client.post(
            "/api/projects/proj/pipelines/my-pipe",
            json={"graph": graph},
        )
        assert resp.status_code == 200

    async def test_load_pipeline(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "proj"})
        graph = {"nodes": [{"id": "n1"}], "edges": []}
        await client.post(
            "/api/projects/proj/pipelines/my-pipe",
            json={"graph": graph},
        )
        resp = await client.get("/api/projects/proj/pipelines/my-pipe")
        assert resp.status_code == 200
        assert resp.json() == graph

    async def test_load_missing_pipeline_returns_404(self, client: httpx.AsyncClient):
        await client.post("/api/projects", json={"name": "proj"})
        resp = await client.get("/api/projects/proj/pipelines/nope")
        assert resp.status_code == 404

    async def test_delete_nonexistent_project_returns_404(self, client: httpx.AsyncClient):
        resp = await client.delete("/api/projects/nonexistent")
        assert resp.status_code == 404

    async def test_save_pipeline_nonexistent_project_returns_404(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/api/projects/nonexistent/pipelines/test",
            json={"graph": {"nodes": [], "edges": []}},
        )
        assert resp.status_code == 404
