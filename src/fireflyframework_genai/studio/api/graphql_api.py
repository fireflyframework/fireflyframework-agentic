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

"""Strawberry GraphQL endpoint for Firefly Agentic Studio.

Provides a ``/api/graphql`` endpoint with Query and Mutation types that
mirror the REST project and runtime APIs.  Strawberry is treated as an
optional dependency -- when it is not installed the router falls back to
a stub that returns 501 Not Implemented.

.. note::

   This module intentionally does **not** use
   ``from __future__ import annotations`` because Strawberry requires
   concrete type objects at class-definition time in order to build the
   GraphQL schema.  Postponed evaluation (PEP 563) turns annotations
   into strings, which breaks Strawberry's type resolution for classes
   defined inside a function scope.
"""

import logging
from typing import Any

from fireflyframework_genai.studio.projects import ProjectManager

logger = logging.getLogger(__name__)


def create_graphql_router(project_manager: ProjectManager) -> Any:
    """Create a Strawberry :class:`GraphQLRouter` for Studio.

    When ``strawberry-graphql`` is not installed, returns a plain
    :class:`~fastapi.APIRouter` with a single ``POST /api/graphql``
    endpoint that returns a 501 error.

    Parameters
    ----------
    project_manager:
        The :class:`ProjectManager` used to list projects and load
        pipelines.

    Returns
    -------
    A router (either Strawberry ``GraphQLRouter`` or a fallback
    ``APIRouter``) that should be included in the FastAPI app.
    """
    try:
        import strawberry
        from strawberry.fastapi import GraphQLRouter
    except ImportError:
        logger.warning(
            "strawberry-graphql is not installed; GraphQL endpoint disabled"
        )
        from fastapi import APIRouter  # type: ignore[import-not-found]

        router = APIRouter()

        @router.post("/api/graphql")
        async def graphql_not_available() -> dict[str, str]:
            return {"error": "GraphQL not available. Install strawberry-graphql."}

        return router

    # ------------------------------------------------------------------
    # Strawberry types
    # ------------------------------------------------------------------

    @strawberry.type
    class Project:
        name: str
        description: str
        created_at: str

    @strawberry.type
    class RuntimeStatus:
        project: str
        status: str
        trigger_type: str | None
        consumers: int
        scheduler_active: bool

    @strawberry.type
    class ExecutionResult:
        execution_id: str
        status: str
        result: str | None
        duration_ms: float | None

    # ------------------------------------------------------------------
    # Query resolvers
    # ------------------------------------------------------------------

    @strawberry.type
    class Query:
        @strawberry.field
        def projects(self) -> list[Project]:
            """List all Studio projects."""
            return [
                Project(
                    name=p.name,
                    description=p.description,
                    created_at=p.created_at,
                )
                for p in project_manager.list_all()
            ]

        @strawberry.field
        def project(self, name: str) -> Project | None:
            """Fetch a single project by name, or *None* if not found."""
            for p in project_manager.list_all():
                if p.name == name:
                    return Project(
                        name=p.name,
                        description=p.description,
                        created_at=p.created_at,
                    )
            return None

        @strawberry.field
        def runtime_status(self, project: str) -> RuntimeStatus:
            """Return the runtime status for a project.

            If no runtime is active, returns a default "stopped" status.
            """
            from fireflyframework_genai.studio.api.project_api import _runtimes

            runtime = _runtimes.get(project)
            if runtime is not None:
                info = runtime.get_status()
                return RuntimeStatus(
                    project=info["project"],
                    status=info["status"],
                    trigger_type=info.get("trigger_type"),
                    consumers=info.get("consumers", 0),
                    scheduler_active=info.get("scheduler_active", False),
                )

            return RuntimeStatus(
                project=project,
                status="stopped",
                trigger_type=None,
                consumers=0,
                scheduler_active=False,
            )

    # ------------------------------------------------------------------
    # Mutation resolvers
    # ------------------------------------------------------------------

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        async def run_pipeline(self, project: str, input: str) -> ExecutionResult:
            """Execute the project's main pipeline synchronously.

            The *input* parameter is passed as a plain string to the
            compiled pipeline engine.
            """
            import time
            import uuid

            from fireflyframework_genai.studio.codegen.models import (
                GraphEdge,
                GraphModel,
                GraphNode,
            )
            from fireflyframework_genai.studio.execution.compiler import compile_graph

            execution_id = str(uuid.uuid4())

            # Load the project's main pipeline graph
            try:
                graph_dict = project_manager.load_pipeline(project, "main")
            except FileNotFoundError:
                return ExecutionResult(
                    execution_id=execution_id,
                    status="error",
                    result=f"Pipeline 'main' not found in project '{project}'",
                    duration_ms=None,
                )

            nodes = [GraphNode(**n) for n in graph_dict.get("nodes", [])]
            edges = [GraphEdge(**e) for e in graph_dict.get("edges", [])]
            graph_model = GraphModel(
                nodes=nodes,
                edges=edges,
                metadata=graph_dict.get("metadata", {}),
            )

            start_time = time.monotonic()
            try:
                engine = compile_graph(graph_model)
                result = await engine.run(inputs=input)
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                return ExecutionResult(
                    execution_id=execution_id,
                    status="completed",
                    result=str(result) if result is not None else None,
                    duration_ms=duration_ms,
                )
            except Exception as exc:
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                logger.exception(
                    "GraphQL run_pipeline failed for project '%s'", project
                )
                return ExecutionResult(
                    execution_id=execution_id,
                    status="error",
                    result=str(exc),
                    duration_ms=duration_ms,
                )

    # ------------------------------------------------------------------
    # Build schema and return router
    # ------------------------------------------------------------------

    schema = strawberry.Schema(query=Query, mutation=Mutation)
    return GraphQLRouter(schema, path="/api/graphql")
