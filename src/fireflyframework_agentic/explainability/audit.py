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

"""Immutable audit trail for regulatory compliance.

:class:`AuditTrail` stores :class:`AuditEntry` records that cannot be
modified after creation.  Entries can be exported to JSON for archival.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    """A single immutable audit record."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str  # agent name, user id, or system
    action: str  # "llm_call", "tool_execution", "delegation", etc.
    resource: str = ""  # what was acted upon
    detail: dict[str, Any] = {}
    outcome: str = "success"  # "success" or "failure"


class AuditTrail:
    """Append-only audit log.

    Entries cannot be removed or modified after they are appended.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def append(
        self,
        actor: str,
        action: str,
        *,
        resource: str = "",
        detail: dict[str, Any] | None = None,
        outcome: str = "success",
    ) -> AuditEntry:
        """Create and append an immutable audit entry."""
        entry = AuditEntry(
            actor=actor,
            action=action,
            resource=resource,
            detail=detail or {},
            outcome=outcome,
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[AuditEntry]:
        """All audit entries (read-only copy)."""
        return list(self._entries)

    def export_json(self) -> str:
        """Serialise the entire audit trail to a JSON string."""
        return json.dumps(
            [e.model_dump(mode="json") for e in self._entries],
            indent=2,
            default=str,
        )

    def __len__(self) -> int:
        return len(self._entries)
