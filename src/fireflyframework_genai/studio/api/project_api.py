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

"""Per-project REST API endpoints for pipeline execution and runtime management.

Provides endpoints for:
- Synchronous and asynchronous pipeline execution
- Runtime lifecycle (start / stop / status)
- Execution history and polling
- File upload triggers
- Input/output schema introspection
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile  # type: ignore[import-not-found]
from pydantic import BaseModel  # type: ignore[import-not-found]

from fireflyframework_genai.studio.projects import ProjectManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level stores for active runtimes and async execution results
# ---------------------------------------------------------------------------

_runtimes: dict[str, Any] = {}
"""Map of project name -> ProjectRuntime for active runtimes."""

_executions: dict[str, dict[str, Any]] = {}
"""Map of execution_id -> execution result dict for async runs."""

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """Body for synchronous or asynchronous pipeline execution."""

    input: Any = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_project_exists(project_manager: ProjectManager, name: str) -> None:
    """Raise 404 if the project directory does not exist on disk."""
    project_dir = project_manager._safe_path(name)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")


def _load_graph_model(project_manager: ProjectManager, name: str) -> Any:
    """Load pipeline JSON and construct a GraphModel.

    Raises HTTPException(404) if the pipeline does not exist.
    """
    from fireflyframework_genai.studio.codegen.models import GraphEdge, GraphModel, GraphNode

    try:
        graph_dict = project_manager.load_pipeline(name, "main")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Pipeline 'main' not found in project '{name}'",
        ) from exc

    nodes = [GraphNode(**n) for n in graph_dict.get("nodes", [])]
    edges = [GraphEdge(**e) for e in graph_dict.get("edges", [])]
    return GraphModel(nodes=nodes, edges=edges, metadata=graph_dict.get("metadata", {}))


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_project_api_router(project_manager: ProjectManager) -> APIRouter:
    """Create an :class:`APIRouter` for per-project runtime and execution endpoints.

    Endpoints
    ---------
    ``POST /api/projects/{name}/run``
        Synchronous pipeline execution.
    ``POST /api/projects/{name}/run/async``
        Asynchronous pipeline execution (returns immediately).
    ``GET  /api/projects/{name}/runs/{execution_id}``
        Poll an async execution for its result.
    ``POST /api/projects/{name}/upload``
        Trigger pipeline execution via file upload.
    ``GET  /api/projects/{name}/schema``
        Retrieve the project's input/output schema.
    ``POST /api/projects/{name}/runtime/start``
        Start the project runtime (queue consumers, schedulers).
    ``POST /api/projects/{name}/runtime/stop``
        Stop the project runtime.
    ``GET  /api/projects/{name}/runtime/status``
        Query the project runtime status.
    ``GET  /api/projects/{name}/runtime/executions``
        List recent executions for the project.
    """
    router = APIRouter(prefix="/api/projects", tags=["project-api"])

    # -- Synchronous execution ---------------------------------------------

    @router.post("/{name}/run")
    async def run_pipeline(name: str, body: RunRequest) -> dict[str, Any]:
        """Execute the project's main pipeline synchronously."""
        _assert_project_exists(project_manager, name)

        from fireflyframework_genai.studio.execution.compiler import compile_graph

        graph_model = _load_graph_model(project_manager, name)

        execution_id = str(uuid.uuid4())
        start_time = time.monotonic()

        try:
            engine = compile_graph(graph_model)
            result = await engine.run(body.input)
        except Exception as exc:
            logger.exception("Pipeline execution failed for project '%s'", name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        # Store in execution history
        record = {
            "execution_id": execution_id,
            "project": name,
            "status": "completed",
            "result": result,
            "duration_ms": duration_ms,
        }
        _executions[execution_id] = record

        return {
            "result": result,
            "execution_id": execution_id,
            "duration_ms": duration_ms,
        }

    # -- Asynchronous execution --------------------------------------------

    @router.post("/{name}/run/async")
    async def run_pipeline_async(name: str, body: RunRequest) -> dict[str, Any]:
        """Start pipeline execution asynchronously; returns immediately."""
        _assert_project_exists(project_manager, name)

        from fireflyframework_genai.studio.execution.compiler import compile_graph

        graph_model = _load_graph_model(project_manager, name)

        execution_id = str(uuid.uuid4())
        _executions[execution_id] = {
            "execution_id": execution_id,
            "project": name,
            "status": "running",
            "result": None,
            "duration_ms": None,
        }

        async def _run_in_background() -> None:
            start_time = time.monotonic()
            try:
                engine = compile_graph(graph_model)
                result = await engine.run(body.input)
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                _executions[execution_id].update({
                    "status": "completed",
                    "result": result,
                    "duration_ms": duration_ms,
                })
            except Exception as exc:
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                _executions[execution_id].update({
                    "status": "failed",
                    "result": str(exc),
                    "duration_ms": duration_ms,
                })
                logger.exception("Async pipeline execution failed for project '%s'", name)

        asyncio.create_task(_run_in_background())

        return {
            "execution_id": execution_id,
            "status": "running",
        }

    # -- Poll execution status ---------------------------------------------

    @router.get("/{name}/runs/{execution_id}")
    async def get_execution(name: str, execution_id: str) -> dict[str, Any]:
        """Poll an async execution for its current status and result."""
        _assert_project_exists(project_manager, name)

        record = _executions.get(execution_id)
        if record is None or record.get("project") != name:
            raise HTTPException(
                status_code=404,
                detail=f"Execution '{execution_id}' not found for project '{name}'",
            )

        return {
            "execution_id": record["execution_id"],
            "status": record["status"],
            "result": record.get("result"),
            "duration_ms": record.get("duration_ms"),
        }

    # -- File upload trigger -----------------------------------------------

    @router.post("/{name}/upload")
    async def upload_file(name: str, file: UploadFile) -> dict[str, Any]:
        """Trigger pipeline execution via file upload."""
        _assert_project_exists(project_manager, name)

        from fireflyframework_genai.studio.execution.compiler import compile_graph

        graph_model = _load_graph_model(project_manager, name)

        content = await file.read()
        inputs = {
            "file_name": file.filename,
            "content_type": file.content_type,
            "content": content.decode("utf-8", errors="replace"),
            "size": len(content),
        }

        execution_id = str(uuid.uuid4())
        start_time = time.monotonic()

        try:
            engine = compile_graph(graph_model)
            result = await engine.run(inputs)
        except Exception as exc:
            logger.exception("File upload pipeline execution failed for project '%s'", name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        return {
            "result": result,
            "execution_id": execution_id,
            "duration_ms": duration_ms,
        }

    # -- Schema endpoint ---------------------------------------------------

    @router.get("/{name}/schema")
    async def get_schema(name: str) -> dict[str, Any]:
        """Return the project's input/output schema from its pipeline."""
        _assert_project_exists(project_manager, name)

        try:
            graph_dict = project_manager.load_pipeline(name, "main")
        except FileNotFoundError:
            # No pipeline saved yet; return empty schema
            return {
                "input_schema": None,
                "output_schema": None,
                "trigger_type": None,
            }

        nodes = graph_dict.get("nodes", [])

        input_schema = None
        output_schema = None
        trigger_type = None

        for node in nodes:
            node_type = node.get("type", "")
            data = node.get("data", {})

            if node_type == "input":
                trigger_type = data.get("trigger_type")
                input_schema = data.get("schema")
            elif node_type == "output":
                output_schema = data.get("response_schema")

        return {
            "input_schema": input_schema,
            "output_schema": output_schema,
            "trigger_type": trigger_type,
        }

    # -- Runtime start -----------------------------------------------------

    @router.post("/{name}/runtime/start")
    async def start_runtime(name: str) -> dict[str, Any]:
        """Start the project runtime (queue consumers, schedulers)."""
        _assert_project_exists(project_manager, name)

        from fireflyframework_genai.studio.runtime import ProjectRuntime

        graph_model = _load_graph_model(project_manager, name)

        # Stop existing runtime if present
        existing = _runtimes.get(name)
        if existing is not None:
            await existing.stop()

        runtime = ProjectRuntime(name)
        await runtime.start(graph_model)
        _runtimes[name] = runtime

        return {"status": "running"}

    # -- Runtime stop ------------------------------------------------------

    @router.post("/{name}/runtime/stop")
    async def stop_runtime(name: str) -> dict[str, Any]:
        """Stop the project runtime."""
        _assert_project_exists(project_manager, name)

        runtime = _runtimes.get(name)
        if runtime is not None:
            await runtime.stop()
            del _runtimes[name]

        return {"status": "stopped"}

    # -- Runtime status ----------------------------------------------------

    @router.get("/{name}/runtime/status")
    async def get_runtime_status(name: str) -> dict[str, Any]:
        """Query the project runtime status."""
        _assert_project_exists(project_manager, name)

        runtime = _runtimes.get(name)
        if runtime is not None:
            return runtime.get_status()

        return {
            "project": name,
            "status": "stopped",
            "trigger_type": None,
            "consumers": 0,
            "scheduler_active": False,
        }

    # -- Execution history -------------------------------------------------

    @router.get("/{name}/runtime/executions")
    async def list_executions(name: str) -> dict[str, Any]:
        """List recent executions for the project."""
        _assert_project_exists(project_manager, name)

        project_executions = [
            {
                "execution_id": rec["execution_id"],
                "status": rec["status"],
                "duration_ms": rec.get("duration_ms"),
            }
            for rec in _executions.values()
            if rec.get("project") == name
        ]

        return {"executions": project_executions}

    return router
