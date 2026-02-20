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

"""Code generation API endpoints for Firefly Studio.

Provides a REST endpoint that converts the visual graph model (JSON from the
frontend canvas) into executable Python code.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]
from pydantic import BaseModel, ValidationError

from fireflyframework_genai.studio.codegen.generator import generate_python
from fireflyframework_genai.studio.codegen.models import GraphModel

logger = logging.getLogger(__name__)


class ToCodeRequest(BaseModel):
    """Request body for the ``POST /api/codegen/to-code`` endpoint."""

    graph: dict  # raw graph dict that will be validated as GraphModel


def create_codegen_router() -> APIRouter:
    """Create an :class:`APIRouter` that serves code generation endpoints.

    Endpoints
    ---------
    ``POST /api/codegen/to-code``
        Accept a graph model (JSON) and return the generated Python code.

        **Request body:**
        ``{"graph": {"nodes": [...], "edges": [...]}}``

        **Response:**
        ``{"code": "...generated python code..."}``
    """
    router = APIRouter(prefix="/api/codegen", tags=["codegen"])

    @router.post("/to-code")
    async def to_code(req: ToCodeRequest) -> dict[str, str]:
        """Convert a graph model to Python code."""
        try:
            graph = GraphModel.model_validate(req.graph)
        except ValidationError as exc:
            logger.warning("Invalid graph model: %s", exc)
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        code = generate_python(graph)
        return {"code": code}

    return router
