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

"""Records decision traces for explainability and audit.

:class:`TraceRecorder` captures every LLM call, tool invocation, and
reasoning step so they can be reviewed, explained, and audited.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DecisionRecord(BaseModel):
    """A single recorded decision point."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: str  # "llm_call", "tool_invocation", "reasoning_step", "delegation"
    agent: str = ""
    detail: dict[str, Any] = {}
    input_summary: str = ""
    output_summary: str = ""


class TraceRecorder:
    """Captures decision records throughout an agent's execution.

    Records are stored in memory and can be retrieved for explanation
    generation or audit trail creation.
    """

    def __init__(self) -> None:
        self._records: list[DecisionRecord] = []

    def record(
        self,
        category: str,
        *,
        agent: str = "",
        detail: dict[str, Any] | None = None,
        input_summary: str = "",
        output_summary: str = "",
    ) -> DecisionRecord:
        """Create and store a new decision record."""
        rec = DecisionRecord(
            category=category,
            agent=agent,
            detail=detail or {},
            input_summary=input_summary,
            output_summary=output_summary,
        )
        self._records.append(rec)
        logger.debug("Recorded %s decision for agent '%s'", category, agent)
        return rec

    @property
    def records(self) -> list[DecisionRecord]:
        """All recorded decision points (read-only copy)."""
        return list(self._records)

    def clear(self) -> None:
        """Remove all records."""
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)


# Module-level default trace recorder
default_trace_recorder = TraceRecorder()
