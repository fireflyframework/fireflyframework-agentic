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

"""Structured event logging for Firefly Agentic operations.

:class:`FireflyEvents` emits structured log records for agent runs,
tool executions, reasoning steps, and lifecycle transitions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("fireflyframework_agentic.events")


class FireflyEvent(BaseModel):
    """A structured event emitted by the framework."""

    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent: str = ""
    tool: str = ""
    pattern: str = ""
    detail: dict[str, Any] = {}
    level: str = "INFO"


class FireflyEvents:
    """Emits structured events via Python logging.

    Events are logged as JSON-serialisable dicts so they integrate with
    any log aggregation backend.
    """

    def agent_started(self, agent_name: str, model: str = "", **extra: Any) -> None:
        """Emit an event when an agent run starts."""
        self._emit(
            FireflyEvent(
                event_type="agent.started",
                agent=agent_name,
                detail={"model": model, **extra},
            )
        )

    def agent_completed(self, agent_name: str, *, tokens: int = 0, latency_ms: float = 0, **extra: Any) -> None:
        """Emit an event when an agent run completes."""
        self._emit(
            FireflyEvent(
                event_type="agent.completed",
                agent=agent_name,
                detail={"tokens": tokens, "latency_ms": latency_ms, **extra},
            )
        )

    def agent_error(self, agent_name: str, error: str, **extra: Any) -> None:
        """Emit an event when an agent run fails."""
        self._emit(
            FireflyEvent(
                event_type="agent.error",
                agent=agent_name,
                level="ERROR",
                detail={"error": error, **extra},
            )
        )

    def tool_executed(self, tool_name: str, *, success: bool = True, latency_ms: float = 0, **extra: Any) -> None:
        """Emit an event for a tool execution."""
        self._emit(
            FireflyEvent(
                event_type="tool.executed",
                tool=tool_name,
                detail={"success": success, "latency_ms": latency_ms, **extra},
            )
        )

    def reasoning_step(self, pattern: str, step: int, step_type: str = "", **extra: Any) -> None:
        """Emit an event for a reasoning step."""
        self._emit(
            FireflyEvent(
                event_type="reasoning.step",
                pattern=pattern,
                detail={"step": step, "step_type": step_type, **extra},
            )
        )

    def _emit(self, event: FireflyEvent) -> None:
        """Log the event as a structured dict."""
        log_level = getattr(logging, event.level, logging.INFO)
        logger.log(log_level, "%s", event.model_dump())


# Module-level default
default_events = FireflyEvents()
