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
The framework ships with :class:`InMemoryStore` (default, dict-backed),
:class:`FileStore` (JSON file persistence), and :class:`SQLiteStore`
(stdlib SQLite, indexed and atomic). All three are stdlib-only — no
optional dependency required.

Backends that require external services (PostgreSQL, MongoDB) live in
:mod:`fireflyframework_agentic.memory.database_store` behind optional
dependency groups.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fireflyframework_agentic.exceptions import DatabaseConnectionError, DatabaseStoreError
from fireflyframework_agentic.memory.types import MemoryEntry

_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

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


class SQLiteStore:
    """SQLite-backed memory store using stdlib :mod:`sqlite3`.

    Like :class:`FileStore`, this backend has no optional dependency and
    requires no remote service — it is file-based and runs entirely in
    process. Compared to :class:`FileStore`, it offers atomic writes
    (single-statement, with rollback on crash), indexed lookups by
    namespace and key, expiration filtering pushed down to SQL, and
    safe concurrent access across multiple processes via SQLite's
    file-level locking and optional WAL mode.

    Choose :class:`FileStore` for the smallest possible setup and human-
    readable JSON files. Choose :class:`SQLiteStore` when you want crash
    safety, indexed access at scale, or multi-process correctness.

    Multiple :class:`SQLiteStore` instances may share the same file
    across processes; SQLite's file-level locking and (optionally) WAL
    mode coordinate access between them.

    Parameters:
        path: Path to the SQLite file. The file is created if it does
            not exist; parent directories are created as needed.
        table_name: Name of the table holding memory entries. Default
            ``"firefly_memory"``, matching the convention used by
            :class:`~fireflyframework_agentic.memory.database_store.PostgreSQLStore`.
            Validated against ``[a-zA-Z_][a-zA-Z0-9_]*``.
        wal: When *True*, opens the database in WAL journal mode for
            better concurrent reader/writer behaviour. Default *False*
            (rollback journal).
    """

    def __init__(
        self,
        path: str | Path,
        *,
        table_name: str = "firefly_memory",
        wal: bool = False,
    ) -> None:
        if not _SAFE_IDENTIFIER.match(table_name):
            raise ValueError(f"Invalid table_name: {table_name!r}. Must be a valid SQL identifier.")
        self._path = Path(path)
        self._table_name = table_name
        self._wal = wal
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._initialize()

    def _initialize(self) -> None:
        """Open the connection, set pragmas, and migrate the schema."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._path),
                check_same_thread=False,
                isolation_level=None,  # autocommit
            )
        except Exception as exc:
            raise DatabaseConnectionError(f"Failed to open SQLite database at {self._path}: {exc}") from exc

        try:
            with self._lock:
                cur = self._conn.cursor()
                if self._wal:
                    cur.execute("PRAGMA journal_mode=WAL")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table_name} (
                        entry_id TEXT PRIMARY KEY,
                        namespace TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        key TEXT,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT,
                        importance REAL NOT NULL DEFAULT 0.5
                    )
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self._table_name}_namespace ON {self._table_name}(namespace)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self._table_name}_namespace_key "
                    f"ON {self._table_name}(namespace, key) WHERE key IS NOT NULL"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self._table_name}_expires_at "
                    f"ON {self._table_name}(expires_at) WHERE expires_at IS NOT NULL"
                )
            logger.debug(
                "SQLite schema ready at %s (table=%s, wal=%s)",
                self._path,
                self._table_name,
                self._wal,
            )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to initialise SQLite schema: {exc}") from exc

    def _require_conn(self) -> sqlite3.Connection:
        """Return the open connection, or raise if the store was closed."""
        if self._conn is None:
            raise DatabaseStoreError("SQLite store is closed")
        return self._conn

    def save(self, namespace: str, entry: MemoryEntry) -> None:
        """Persist a single :class:`MemoryEntry` under *namespace*."""
        try:
            with self._lock:
                self._require_conn().execute(
                    f"""
                    INSERT INTO {self._table_name}
                    (entry_id, namespace, scope, key, content, created_at, expires_at, importance)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET
                        namespace = excluded.namespace,
                        scope = excluded.scope,
                        key = excluded.key,
                        content = excluded.content,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at,
                        importance = excluded.importance
                    """,
                    (
                        entry.entry_id,
                        namespace,
                        entry.scope.value,
                        entry.key,
                        entry.model_dump_json(),
                        entry.created_at.isoformat(),
                        entry.expires_at.isoformat() if entry.expires_at else None,
                        entry.importance,
                    ),
                )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to save entry: {exc}") from exc

    def load(self, namespace: str) -> list[MemoryEntry]:
        """Return all non-expired entries stored under *namespace*."""
        try:
            now = datetime.now(UTC).isoformat()
            with self._lock:
                rows = (
                    self._require_conn()
                    .execute(
                        f"""
                    SELECT content FROM {self._table_name}
                    WHERE namespace = ?
                      AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at ASC
                    """,
                        (namespace, now),
                    )
                    .fetchall()
                )
            return [MemoryEntry.model_validate_json(r[0]) for r in rows]
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to load entries: {exc}") from exc

    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        """Return the latest non-expired entry matching *key*, or *None*."""
        try:
            now = datetime.now(UTC).isoformat()
            with self._lock:
                row = (
                    self._require_conn()
                    .execute(
                        f"""
                    SELECT content FROM {self._table_name}
                    WHERE namespace = ?
                      AND key = ?
                      AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                        (namespace, key, now),
                    )
                    .fetchone()
                )
            if row is None:
                return None
            return MemoryEntry.model_validate_json(row[0])
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to load entry by key: {exc}") from exc

    def delete(self, namespace: str, entry_id: str) -> None:
        """Remove a single entry by ID."""
        try:
            with self._lock:
                self._require_conn().execute(
                    f"DELETE FROM {self._table_name} WHERE namespace = ? AND entry_id = ?",
                    (namespace, entry_id),
                )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to delete entry: {exc}") from exc

    def clear(self, namespace: str) -> None:
        """Remove all entries in *namespace*."""
        try:
            with self._lock:
                self._require_conn().execute(
                    f"DELETE FROM {self._table_name} WHERE namespace = ?",
                    (namespace,),
                )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to clear namespace: {exc}") from exc

    def cleanup_expired(self) -> int:
        """Remove all expired entries across all namespaces.

        Returns:
            Number of entries deleted.
        """
        try:
            now = datetime.now(UTC).isoformat()
            with self._lock:
                cur = self._require_conn().execute(
                    f"""
                    DELETE FROM {self._table_name}
                    WHERE expires_at IS NOT NULL AND expires_at <= ?
                    """,
                    (now,),
                )
                count = cur.rowcount
            logger.debug("Cleaned up %d expired entries", count)
            return count
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to cleanup expired entries: {exc}") from exc

    def close(self) -> None:
        """Close the SQLite connection. Idempotent."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                logger.info("SQLite connection closed")

    # -- Async wrappers ------------------------------------------------------

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

    async def async_cleanup_expired(self) -> int:
        """Non-blocking version of :meth:`cleanup_expired`."""
        return await asyncio.to_thread(self.cleanup_expired)
