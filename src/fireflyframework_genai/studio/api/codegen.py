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

"""Code generation API endpoints for Firefly Agentic Studio.

Provides a REST endpoint that converts the visual graph model (JSON from the
frontend canvas) into executable Python code.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SmithCodegenRequest(BaseModel):
    """Request body for the ``POST /api/codegen/smith`` endpoint."""

    graph: dict


def create_codegen_router() -> APIRouter:
    """Create an :class:`APIRouter` that serves code generation endpoints.

    Endpoints
    ---------
    ``POST /api/codegen/smith``
        Accept a graph model (JSON) and return AI-generated Python code
        via the Smith agent.

        **Request body:**
        ``{"graph": {"nodes": [...], "edges": [...]}}``

        **Response:**
        ``{"files": [{"path": str, "content": str, "language": str}],
        "code": "...concatenated code...", "notes": [...]}``
    """
    router = APIRouter(prefix="/api/codegen", tags=["codegen"])

    @router.post("/smith")
    async def smith_codegen(req: SmithCodegenRequest) -> dict:
        """Generate Python code using the Smith AI agent."""
        from fireflyframework_genai.studio.assistant.smith import generate_code_with_smith
        from fireflyframework_genai.studio.settings import load_settings

        try:
            settings = load_settings()
            settings_dict = {
                "model_defaults": {
                    "default_model": settings.model_defaults.default_model,
                }
            }
            user_name = settings.user_profile.name or ""
        except Exception:
            settings_dict = None
            user_name = ""

        try:
            result = await generate_code_with_smith(req.graph, settings_dict, user_name=user_name)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return result

    return router
