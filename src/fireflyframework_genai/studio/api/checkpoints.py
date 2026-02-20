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

"""Checkpoint API endpoints for Firefly Studio.

Exposes the :class:`CheckpointManager` over REST so the frontend can
list, inspect, fork, and diff execution checkpoints for the timeline
debugging UI.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]
from pydantic import BaseModel  # type: ignore[import-not-found]

from fireflyframework_genai.studio.execution.checkpoint import CheckpointManager


class ForkRequest(BaseModel):
    """Request body for forking a checkpoint."""

    from_index: int
    modified_state: dict[str, Any]


class DiffRequest(BaseModel):
    """Request body for diffing two checkpoints."""

    index_a: int
    index_b: int


def create_checkpoints_router(manager: CheckpointManager) -> APIRouter:
    """Create an :class:`APIRouter` that serves checkpoint data.

    Endpoints
    ---------
    ``GET /api/checkpoints``
        Return a list of all checkpoints.
    ``GET /api/checkpoints/{index}``
        Return a single checkpoint by index.
    ``POST /api/checkpoints/fork``
        Fork from an existing checkpoint with modified state.
    ``POST /api/checkpoints/diff``
        Diff the state of two checkpoints.
    ``DELETE /api/checkpoints``
        Clear all checkpoints.
    """
    router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"])

    @router.get("")
    async def list_checkpoints() -> list[dict[str, Any]]:
        return [asdict(cp) for cp in manager.list_all()]

    @router.get("/{index}")
    async def get_checkpoint(index: int) -> dict[str, Any]:
        try:
            return asdict(manager.get(index))
        except IndexError as exc:
            raise HTTPException(status_code=404, detail=f"Checkpoint {index} not found") from exc

    @router.post("/fork")
    async def fork_checkpoint(body: ForkRequest) -> dict[str, Any]:
        try:
            cp = manager.fork(body.from_index, body.modified_state)
        except IndexError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint {body.from_index} not found",
            ) from exc
        return asdict(cp)

    @router.post("/diff")
    async def diff_checkpoints(body: DiffRequest) -> dict[str, Any]:
        try:
            result = manager.diff(body.index_a, body.index_b)
        except IndexError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # Convert sets to sorted lists for JSON serialisation
        return {k: sorted(v) for k, v in result.items()}

    @router.delete("")
    async def clear_checkpoints() -> dict[str, str]:
        manager.clear()
        return {"status": "cleared"}

    return router
