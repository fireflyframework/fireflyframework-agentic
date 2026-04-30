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

"""Interactive lab session management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from fireflyframework_agentic.types import AgentLike


class SessionEntry(BaseModel):
    """A single interaction within a lab session."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    prompt: str
    response: str = ""
    metadata: dict[str, Any] = {}


class LabSession:
    """Manages an interactive experimentation session with history.

    Parameters:
        name: Session name for identification.
        agent: The agent to interact with in this session.
    """

    def __init__(self, name: str, agent: AgentLike) -> None:
        self._name = name
        self._agent = agent
        self._history: list[SessionEntry] = []
        self._created_at = datetime.now(UTC)

    @property
    def name(self) -> str:
        return self._name

    @property
    def history(self) -> list[SessionEntry]:
        return list(self._history)

    async def interact(self, prompt: str, **kwargs: Any) -> str:
        """Send a prompt to the agent and record the interaction."""
        result = await self._agent.run(prompt, **kwargs)
        response = str(result.output if hasattr(result, "output") else result)
        self._history.append(SessionEntry(prompt=prompt, response=response, metadata=kwargs))
        return response

    def clear_history(self) -> None:
        """Clear the session history."""
        self._history.clear()
