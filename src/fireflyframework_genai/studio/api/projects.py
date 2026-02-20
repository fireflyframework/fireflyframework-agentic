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

"""Project management REST API endpoints for Firefly Studio.

Provides CRUD operations for projects and pipeline persistence so the
Studio frontend can manage user workspaces.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]
from pydantic import BaseModel  # type: ignore[import-not-found]

from fireflyframework_genai.studio.projects import ProjectManager

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    """Body for creating a new project."""

    name: str
    description: str = ""


class SavePipelineRequest(BaseModel):
    """Body for saving a pipeline graph."""

    graph: dict[str, Any]


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_projects_router(manager: ProjectManager) -> APIRouter:
    """Create an :class:`APIRouter` for project management.

    Endpoints
    ---------
    ``GET /api/projects``
        List all projects.
    ``POST /api/projects``
        Create a new project.
    ``DELETE /api/projects/{name}``
        Delete a project.
    ``POST /api/projects/{project_name}/pipelines/{pipeline_name}``
        Save a pipeline graph.
    ``GET /api/projects/{project_name}/pipelines/{pipeline_name}``
        Load a pipeline graph.
    """
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.get("")
    async def list_projects() -> list[dict[str, Any]]:
        projects = manager.list_all()
        results = []
        for p in projects:
            d = asdict(p)
            # Convert Path to string for JSON serialization
            d["path"] = str(d["path"])
            results.append(d)
        return results

    @router.post("")
    async def create_project(body: CreateProjectRequest) -> dict[str, Any]:
        try:
            info = manager.create(body.name, description=body.description)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        d = asdict(info)
        d["path"] = str(d["path"])
        return d

    @router.delete("/{name}")
    async def delete_project(name: str) -> dict[str, str]:
        try:
            manager.delete(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "deleted"}

    @router.post("/{project_name}/pipelines/{pipeline_name}")
    async def save_pipeline(project_name: str, pipeline_name: str, body: SavePipelineRequest) -> dict[str, str]:
        try:
            manager.save_pipeline(project_name, pipeline_name, body.graph)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved"}

    @router.get("/{project_name}/pipelines/{pipeline_name}")
    async def load_pipeline(project_name: str, pipeline_name: str) -> dict[str, Any]:
        try:
            return manager.load_pipeline(project_name, pipeline_name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
