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

"""Memory data types used across the memory subsystem.

:class:`MemoryEntry` is the universal unit of storage.
:class:`ConversationTurn` captures a single request/response pair.
:class:`MemoryScope` classifies entries by lifetime.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class MemoryScope(enum.StrEnum):
    """Lifetime classification for memory entries."""

    CONVERSATION = "conversation"
    """Scoped to a single conversation (cleared when the conversation ends)."""

    WORKING = "working"
    """Scoped to a session / pipeline run (intermediate scratchpad)."""

    LONG_TERM = "long_term"
    """Persists across conversations and sessions."""


class MemoryEntry(BaseModel):
    """A single unit of stored memory.

    Attributes:
        entry_id: Unique identifier for this entry.
        scope: Lifetime scope.
        key: Optional key for key-value lookups (used by WorkingMemory).
        content: The stored value (string, dict, list, etc.).
        metadata: Arbitrary metadata (agent name, timestamp, tags).
        created_at: When this entry was created.
        expires_at: Optional TTL-based expiry timestamp.
        importance: Priority weight for eviction decisions (0.0–1.0).
    """

    entry_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    scope: MemoryScope = MemoryScope.WORKING
    key: str | None = None
    content: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    importance: float = 0.5

    @property
    def is_expired(self) -> bool:
        """Return *True* if the entry has passed its expiry time."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at


class ConversationTurn(BaseModel):
    """A single request/response pair in a conversation.

    This is a Firefly-level abstraction over pydantic-ai's ``ModelMessage``
    list.  Each turn stores the user prompt and assistant response as plain
    text for inspection, plus the raw ``ModelMessage`` objects for replay.

    Attributes:
        turn_id: Sequential turn index (0-based).
        user_prompt: The user's input text.
        assistant_response: The assistant's output text.
        raw_messages: The underlying pydantic-ai ``ModelMessage`` objects
            for this turn (used to reconstruct ``message_history``).
        timestamp: When this turn occurred.
        token_estimate: Estimated token count for this turn's messages.
        metadata: Arbitrary metadata (model used, latency, etc.).
    """

    turn_id: int = 0
    user_prompt: str = ""
    assistant_response: str = ""
    raw_messages: list[Any] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    token_estimate: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
