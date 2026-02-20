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

"""Registry API endpoints for Firefly Studio.

Exposes the framework's global registries (agents, tools, reasoning patterns)
so the Studio frontend can list available components in the node palette.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter  # type: ignore[import-not-found]

from fireflyframework_genai.agents.registry import agent_registry
from fireflyframework_genai.reasoning.registry import reasoning_registry
from fireflyframework_genai.tools.registry import tool_registry


def create_registry_router() -> APIRouter:
    """Create an :class:`APIRouter` that serves registry data.

    Endpoints
    ---------
    ``GET /api/registry/agents``
        Return a list of :class:`AgentInfo` dicts for every registered agent.
    ``GET /api/registry/tools``
        Return a list of :class:`ToolInfo` dicts for every registered tool.
    ``GET /api/registry/patterns``
        Return a list of pattern name dicts for every registered reasoning
        pattern.
    """
    router = APIRouter(prefix="/api/registry", tags=["registry"])

    @router.get("/agents")
    async def list_agents() -> list[dict[str, Any]]:
        return [info.model_dump() for info in agent_registry.list_agents()]

    @router.get("/tools")
    async def list_tools() -> list[dict[str, Any]]:
        return [info.model_dump() for info in tool_registry.list_tools()]

    @router.get("/patterns")
    async def list_patterns() -> list[dict[str, str]]:
        return [{"name": name} for name in reasoning_registry.list_patterns()]

    return router
