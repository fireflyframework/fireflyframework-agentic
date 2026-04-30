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

"""Working memory: session-scoped key-value scratchpad.

:class:`WorkingMemory` provides a lightweight key-value store for
intermediate facts, entities, and decisions that agents and pipeline
steps need to share during a single session or run.
"""

from __future__ import annotations

import logging
from typing import Any

from fireflyframework_agentic.memory.store import InMemoryStore, MemoryStore
from fireflyframework_agentic.memory.types import MemoryEntry, MemoryScope

logger = logging.getLogger(__name__)


class WorkingMemory:
    """Session-scoped key-value scratchpad backed by a :class:`MemoryStore`.

    Keys are namespaced by a ``scope_id`` (typically a conversation ID,
    pipeline correlation ID, or agent name) so that multiple sessions
    can coexist without collision.

    Parameters:
        store: The persistence backend.  Defaults to :class:`InMemoryStore`.
        scope_id: Namespace prefix for all keys.
    """

    def __init__(
        self,
        *,
        store: MemoryStore | None = None,
        scope_id: str = "default",
    ) -> None:
        self._store = store or InMemoryStore()
        self._scope_id = scope_id
        self._namespace = f"working:{scope_id}"

    @property
    def scope_id(self) -> str:
        return self._scope_id

    # -- CRUD --------------------------------------------------------------

    def set(self, key: str, value: Any, *, importance: float = 0.5) -> None:
        """Set a key-value pair in working memory.

        If the key already exists, the old entry is replaced.
        """
        existing = self._store.load_by_key(self._namespace, key)
        if existing is not None:
            self._store.delete(self._namespace, existing.entry_id)

        entry = MemoryEntry(
            scope=MemoryScope.WORKING,
            key=key,
            content=value,
            importance=importance,
            metadata={"scope_id": self._scope_id},
        )
        self._store.save(self._namespace, entry)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key.  Returns *default* if not found."""
        entry = self._store.load_by_key(self._namespace, key)
        if entry is None:
            return default
        return entry.content

    def has(self, key: str) -> bool:
        """Return *True* if *key* exists in working memory."""
        return self._store.load_by_key(self._namespace, key) is not None

    def delete(self, key: str) -> None:
        """Remove a key from working memory."""
        entry = self._store.load_by_key(self._namespace, key)
        if entry is not None:
            self._store.delete(self._namespace, entry.entry_id)

    def keys(self) -> list[str]:
        """Return all keys in this working memory scope."""
        entries = self._store.load(self._namespace)
        return [e.key for e in entries if e.key is not None]

    def items(self) -> list[tuple[str, Any]]:
        """Return all key-value pairs."""
        entries = self._store.load(self._namespace)
        return [(e.key, e.content) for e in entries if e.key is not None]

    def to_dict(self) -> dict[str, Any]:
        """Return all key-value pairs as a plain dict."""
        return dict(self.items())

    def to_context_string(self) -> str:
        """Render working memory as a text block suitable for injection
        into an agent's prompt context.

        Example output::

            Working Memory:
            - doc_type: invoice
            - language: en
            - total_pages: 5
        """
        items = self.items()
        if not items:
            return ""
        lines = ["Working Memory:"]
        for key, value in items:
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Remove all entries in this scope."""
        self._store.clear(self._namespace)

    def __repr__(self) -> str:
        return f"WorkingMemory(scope_id={self._scope_id!r}, keys={len(self.keys())})"
