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

"""Monitoring API endpoints for Firefly Studio.

Exposes the framework's usage tracking data so the Studio frontend can
display cost, token, and latency metrics in the monitoring dashboard.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter  # type: ignore[import-not-found]


def create_monitoring_router() -> APIRouter:
    """Create an :class:`APIRouter` that serves monitoring data.

    Endpoints
    ---------
    ``GET /api/monitoring/usage``
        Return an aggregated :class:`UsageSummary` dict from the
        default usage tracker.
    """
    router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

    @router.get("/usage")
    async def get_usage() -> dict[str, Any]:
        from fireflyframework_genai.observability.usage import default_usage_tracker

        return default_usage_tracker.get_summary().model_dump()

    return router
