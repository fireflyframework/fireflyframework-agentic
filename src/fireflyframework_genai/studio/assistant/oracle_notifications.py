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

"""Oracle notification / insight manager.

Stores structured insights from The Oracle as JSON files per project.
Each insight has a severity, description, optional action instruction,
and a status (pending / approved / skipped).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_BASE = Path.home() / ".firefly-studio" / "projects"


@dataclass
class OracleInsight:
    """A single insight or suggestion from The Oracle."""

    id: str
    title: str
    description: str
    severity: str  # 'info' | 'warning' | 'suggestion' | 'critical'
    action_instruction: str | None = None
    timestamp: str = ""
    status: str = "pending"  # 'pending' | 'approved' | 'skipped'


def create_insight(
    title: str,
    description: str,
    severity: str = "suggestion",
    action_instruction: str | None = None,
) -> OracleInsight:
    """Create a new Oracle insight with auto-generated ID and timestamp."""
    return OracleInsight(
        id=uuid.uuid4().hex[:12],
        title=title,
        description=description,
        severity=severity,
        action_instruction=action_instruction,
        timestamp=datetime.now(UTC).isoformat(),
        status="pending",
    )


def _insights_path(project: str, base: Path | None = None) -> Path:
    """Return the path to the insights JSON file for a project."""
    base_dir = base or _DEFAULT_BASE
    return base_dir / project / "oracle_insights.json"


def _load_raw(path: Path) -> list[dict]:
    """Load raw insight dicts from disk."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Corrupt oracle insights at %s, resetting", path)
        return []


def _save_raw(path: Path, data: list[dict]) -> None:
    """Persist insight dicts to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_insights(project: str, base: Path | None = None) -> list[OracleInsight]:
    """List all insights for a project."""
    path = _insights_path(project, base)
    raw = _load_raw(path)
    insights: list[OracleInsight] = []
    for r in raw:
        try:
            insights.append(OracleInsight(**r))
        except (TypeError, KeyError):
            continue
    return insights


def add_insight(
    project: str,
    insight: OracleInsight,
    base: Path | None = None,
) -> OracleInsight:
    """Append an insight to a project's insight list and persist."""
    path = _insights_path(project, base)
    raw = _load_raw(path)
    raw.append(asdict(insight))
    _save_raw(path, raw)
    return insight


def update_insight_status(
    project: str,
    insight_id: str,
    status: str,
    base: Path | None = None,
) -> OracleInsight | None:
    """Update an insight's status (pending -> approved/skipped)."""
    path = _insights_path(project, base)
    raw = _load_raw(path)

    for item in raw:
        if item.get("id") == insight_id:
            item["status"] = status
            _save_raw(path, raw)
            return OracleInsight(**item)

    return None
