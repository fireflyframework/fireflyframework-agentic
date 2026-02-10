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

"""Health check endpoint factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter  # type: ignore[import-not-found]

from fireflyframework_genai.agents.registry import agent_registry
from fireflyframework_genai.exposure.rest.schemas import HealthResponse


def create_health_router() -> APIRouter:
    """Create a FastAPI router with health check endpoints."""
    from fastapi import APIRouter  # type: ignore[import-not-found]

    router = APIRouter(tags=["health"])

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            agents=len(agent_registry),
        )

    @router.get("/health/ready")
    async def readiness() -> dict[str, str]:
        return {"status": "ready"}

    @router.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "alive"}

    return router
