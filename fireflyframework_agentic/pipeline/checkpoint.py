# Copyright 2026 Firefly Software Foundation
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

"""Pipeline state checkpointing for failure recovery and resumable runs.

A :class:`Checkpointer` persists state after each successful node, keyed by
``(pipeline_name, run_id, node_id)``. On resume the engine loads the latest
checkpoint and skips nodes that already completed in that run.

:class:`FileCheckpointer` is a filesystem-backed JSON implementation suitable
for single-process workflows. Redis / Postgres checkpointers can implement
the same Protocol and be swapped in without API changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class CheckpointRecord(BaseModel):
    """One saved checkpoint."""

    pipeline_name: str
    run_id: str
    node_id: str
    sequence: int
    state: dict[str, Any]
    completed_nodes: list[str]


@runtime_checkable
class Checkpointer(Protocol):
    """Persists pipeline state after each successful node.

    Implementations must be safe to call from async code (the engine awaits
    save() inside its task loop) but the methods themselves may be sync.
    """

    def save(self, record: CheckpointRecord) -> None:
        """Persist a checkpoint. Overwrites if (pipeline, run_id, node_id) exists."""
        ...

    def load_latest(self, pipeline_name: str, run_id: str) -> CheckpointRecord | None:
        """Return the most recent checkpoint for ``run_id`` or ``None`` if no run exists."""
        ...

    def list_runs(self, pipeline_name: str) -> list[str]:
        """Return all known run IDs for ``pipeline_name``."""
        ...


class FileCheckpointer:
    """Filesystem-backed checkpointer. Layout::

        <root>/<pipeline_name>/<run_id>/<sequence>_<node_id>.json

    The ``sequence`` prefix gives a natural sort order for ``load_latest``.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, record: CheckpointRecord) -> None:
        run_dir = self._root / record.pipeline_name / record.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{record.sequence:06d}_{record.node_id}.json"
        path.write_text(record.model_dump_json(indent=2))

    def load_latest(self, pipeline_name: str, run_id: str) -> CheckpointRecord | None:
        run_dir = self._root / pipeline_name / run_id
        if not run_dir.exists():
            return None
        files = sorted(run_dir.glob("*.json"))
        if not files:
            return None
        latest = files[-1]
        return CheckpointRecord.model_validate(json.loads(latest.read_text()))

    def list_runs(self, pipeline_name: str) -> list[str]:
        pipeline_dir = self._root / pipeline_name
        if not pipeline_dir.exists():
            return []
        return sorted(d.name for d in pipeline_dir.iterdir() if d.is_dir())
