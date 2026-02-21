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

"""Pluggable memory store backends.

:class:`MemoryStore` is the protocol that all backends must satisfy.
The framework ships with :class:`InMemoryStore` (default, dict-backed)
and :class:`FileStore` (JSON file persistence).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fireflyframework_genai.memory.types import MemoryEntry

logger = logging.getLogger(__name__)


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol for memory persistence backends.

    Implementations must support namespace-scoped CRUD operations so
    that different conversations, agents, or pipelines can maintain
    independent storage.
    """

    def save(self, namespace: str, entry: MemoryEntry) -> None:
        """Persist a single :class:`MemoryEntry` under *namespace*."""
        ...

    def load(self, namespace: str) -> list[MemoryEntry]:
        """Return all entries stored under *namespace*."""
        ...

    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        """Return the entry matching *key*, or *None*."""
        ...

    def delete(self, namespace: str, entry_id: str) -> None:
        """Remove a single entry by ID."""
        ...

    def clear(self, namespace: str) -> None:
        """Remove all entries in *namespace*."""
        ...


class InMemoryStore:
    """Dict-backed in-memory store.  Fast but non-persistent.

    Suitable for testing, short-lived sessions, and as the default backend.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, MemoryEntry]] = defaultdict(dict)
        self._lock = threading.Lock()

    def save(self, namespace: str, entry: MemoryEntry) -> None:
        with self._lock:
            self._data[namespace][entry.entry_id] = entry

    def load(self, namespace: str) -> list[MemoryEntry]:
        with self._lock:
            entries = list(self._data.get(namespace, {}).values())
        return [e for e in entries if not e.is_expired]

    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        with self._lock:
            for entry in self._data.get(namespace, {}).values():
                if entry.key == key and not entry.is_expired:
                    return entry
        return None

    def delete(self, namespace: str, entry_id: str) -> None:
        with self._lock:
            self._data.get(namespace, {}).pop(entry_id, None)

    def clear(self, namespace: str) -> None:
        with self._lock:
            self._data.pop(namespace, None)

    @property
    def namespaces(self) -> list[str]:
        """Return all namespaces that have stored entries."""
        return list(self._data.keys())


class FileStore:
    """JSON file-backed store for lightweight persistence.

    Each namespace is stored as a separate JSON file under *base_dir*.

    Parameters:
        base_dir: Directory where namespace JSON files are written.
    """

    def __init__(self, base_dir: str | Path = ".firefly_memory") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str) -> Path:
        safe_name = namespace.replace("/", "_").replace("\\", "_")
        resolved = (self._base_dir / f"{safe_name}.json").resolve()
        if not resolved.is_relative_to(self._base_dir.resolve()):
            raise ValueError(f"Path traversal detected in namespace: {namespace!r}")
        return resolved

    def _read(self, namespace: str) -> dict[str, Any]:
        path = self._path(namespace)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt memory file '%s', resetting", path)
            return {}

    def _write(self, namespace: str, data: dict[str, Any]) -> None:
        path = self._path(namespace)
        path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def save(self, namespace: str, entry: MemoryEntry) -> None:
        data = self._read(namespace)
        data[entry.entry_id] = entry.model_dump(mode="json")
        self._write(namespace, data)

    def load(self, namespace: str) -> list[MemoryEntry]:
        data = self._read(namespace)
        entries = [MemoryEntry.model_validate(v) for v in data.values()]
        return [e for e in entries if not e.is_expired]

    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        for entry in self.load(namespace):
            if entry.key == key:
                return entry
        return None

    def delete(self, namespace: str, entry_id: str) -> None:
        data = self._read(namespace)
        data.pop(entry_id, None)
        self._write(namespace, data)

    def clear(self, namespace: str) -> None:
        path = self._path(namespace)
        if path.exists():
            path.unlink()

    # -- Async wrappers for non-blocking I/O ---------------------------------

    async def async_save(self, namespace: str, entry: MemoryEntry) -> None:
        """Non-blocking version of :meth:`save`."""
        await asyncio.to_thread(self.save, namespace, entry)

    async def async_load(self, namespace: str) -> list[MemoryEntry]:
        """Non-blocking version of :meth:`load`."""
        return await asyncio.to_thread(self.load, namespace)

    async def async_load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        """Non-blocking version of :meth:`load_by_key`."""
        return await asyncio.to_thread(self.load_by_key, namespace, key)

    async def async_delete(self, namespace: str, entry_id: str) -> None:
        """Non-blocking version of :meth:`delete`."""
        await asyncio.to_thread(self.delete, namespace, entry_id)

    async def async_clear(self, namespace: str) -> None:
        """Non-blocking version of :meth:`clear`."""
        await asyncio.to_thread(self.clear, namespace)
