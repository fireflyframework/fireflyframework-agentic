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

"""API endpoints for Cloudflare Tunnel management."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter  # type: ignore[import-not-found]

from fireflyframework_genai.studio.tunnel import TunnelManager

_tunnel: TunnelManager | None = None


def create_tunnel_router(port: int = 8470) -> APIRouter:
    """Create an :class:`APIRouter` for Cloudflare Tunnel management.

    Endpoints
    ---------
    ``GET  /api/tunnel/status`` -- current tunnel status.
    ``POST /api/tunnel/start``  -- start a quick tunnel.
    ``POST /api/tunnel/stop``   -- stop the running tunnel.
    """
    global _tunnel
    _tunnel = TunnelManager(port=port)
    router = APIRouter(prefix="/api/tunnel", tags=["tunnel"])

    @router.get("/status")
    async def tunnel_status() -> dict[str, Any]:
        return _tunnel.get_status()

    @router.post("/start")
    async def tunnel_start() -> dict[str, Any]:
        if not _tunnel.is_available():
            return {
                "error": "cloudflared not installed",
                "install_url": "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/",
            }
        url = await _tunnel.start()
        return {"url": url, "status": "active"}

    @router.post("/stop")
    async def tunnel_stop() -> dict[str, Any]:
        await _tunnel.stop()
        return {"status": "stopped"}

    return router
