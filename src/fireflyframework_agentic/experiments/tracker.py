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

"""Experiment result tracking and persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class VariantResult(BaseModel):
    """Result of running a single variant."""

    experiment_name: str
    variant_name: str
    outputs: list[str] = []
    avg_latency_ms: float = 0.0
    total_runs: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = {}


class ExperimentTracker:
    """Stores experiment results in memory with optional JSON export.

    Parameters:
        storage_path: Optional file path for JSON persistence.
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._results: list[VariantResult] = []
        self._storage_path = Path(storage_path) if storage_path else None

    def record(self, result: VariantResult) -> None:
        """Record a variant result."""
        self._results.append(result)
        if self._storage_path:
            self._persist()

    @property
    def results(self) -> list[VariantResult]:
        """All recorded results."""
        return list(self._results)

    def get_by_experiment(self, name: str) -> list[VariantResult]:
        """Return all results for experiment *name*."""
        return [r for r in self._results if r.experiment_name == name]

    def export_json(self) -> str:
        """Serialise all results to JSON."""
        return json.dumps(
            [r.model_dump(mode="json") for r in self._results],
            indent=2,
            default=str,
        )

    def clear(self) -> None:
        """Remove all results."""
        self._results.clear()

    def _persist(self) -> None:
        """Write results to the storage file."""
        if self._storage_path:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(self.export_json(), encoding="utf-8")

    def __len__(self) -> int:
        return len(self._results)
