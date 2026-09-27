# Copyright 2026 Firefly Software Foundation
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

"""Database-backed memory store implementations.

This module provides PostgreSQL and MongoDB persistence with connection pooling,
schema/index initialization, and namespace-scoped operations. Driver clients live
on one lazily started background event loop shared by the database stores.
Synchronous methods block their caller; async methods await the same owning loop.
Close stores explicitly at application shutdown with ``await store.close()`` or
``store.close_sync()``. The shared worker loop stops when the process exits.

Examples:
    PostgreSQL backend::

        from fireflyframework_agentic.memory.database_store import PostgreSQLStore

        store = PostgreSQLStore(
            url="postgresql://user:pass@localhost/firefly",
            pool_size=10
        )
        await store.initialize()

        # Use like any other MemoryStore
        store.save("agent_1", entry)

    MongoDB backend::

        from fireflyframework_agentic.memory.database_store import MongoDBStore

        store = MongoDBStore(
            url="mongodb://localhost:27017/",
            database="firefly_memory",
            pool_size=10
        )
        await store.initialize()
"""

from __future__ import annotations

import asyncio
import atexit
import functools
import json
import logging
import re
import threading
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, ParamSpec, TypeVar

try:
    import asyncpg  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    asyncpg = None  # type: ignore[assignment]

try:
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    AsyncIOMotorClient = None  # type: ignore[assignment,misc]

from fireflyframework_agentic.exceptions import DatabaseConnectionError, DatabaseStoreError
from fireflyframework_agentic.memory.types import MemoryEntry

_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

logger = logging.getLogger(__name__)

_loop_lock = threading.Lock()
_database_loop: asyncio.AbstractEventLoop | None = None
_database_thread: threading.Thread | None = None
_P = ParamSpec("_P")
_T = TypeVar("_T")


def _serve_database_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def _owning_loop() -> asyncio.AbstractEventLoop:
    """Keep driver clients on one process-owned loop across all caller contexts."""
    global _database_loop, _database_thread
    with _loop_lock:
        if _database_loop is None:
            _database_loop = asyncio.new_event_loop()
            _database_thread = threading.Thread(
                target=_serve_database_loop, args=(_database_loop,), name="firefly-memory-db", daemon=True
            )
            _database_thread.start()
        return _database_loop


def _shutdown_database_loop() -> None:
    if _database_loop is not None and not _database_loop.is_closed():
        _database_loop.call_soon_threadsafe(_database_loop.stop)
    if _database_thread is not None:
        _database_thread.join(timeout=5)


atexit.register(_shutdown_database_loop)


def _on_database_loop(function: Callable[_P, Coroutine[Any, Any, _T]]) -> Callable[_P, Coroutine[Any, Any, _T]]:
    @functools.wraps(function)
    async def run(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        loop = _owning_loop()
        if asyncio.get_running_loop() is loop:
            return await function(*args, **kwargs)
        future = asyncio.run_coroutine_threadsafe(function(*args, **kwargs), loop)
        return await asyncio.wrap_future(future)

    return run


def _run_sync(coro: Any) -> Any:
    """Block the caller while the coroutine runs on the driver's owning loop."""
    loop = _owning_loop()
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    if current is loop:
        coro.close()
        raise DatabaseStoreError("Use async database methods from the database's owning event loop")
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


# -- PostgreSQL Store -------------------------------------------------------


class PostgreSQLStore:
    """PostgreSQL-backed memory store with connection pooling.

    This implementation uses asyncpg for high-performance async PostgreSQL
    access. It automatically creates the required schema on first connection
    and supports namespace isolation for multi-tenant deployments.

    Parameters:
        url: PostgreSQL connection string (e.g., ``postgresql://user:pass@host/db``).
        pool_size: Maximum number of connections in the pool.
        pool_min_size: Minimum number of connections to maintain.
        timeout: Connection timeout in seconds.
        schema_name: PostgreSQL schema name for table isolation.

    Note:
        Requires the optional ``postgres`` dependency group:
        ``pip install fireflyframework-agentic[postgres]``
    """

    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 10,
        pool_min_size: int = 2,
        timeout: float = 30.0,
        schema_name: str = "firefly_memory",
    ) -> None:
        if not _SAFE_IDENTIFIER.match(schema_name):
            raise ValueError(f"Invalid schema_name: {schema_name!r}. Must be a valid SQL identifier.")
        self._url = url
        self._pool_size = pool_size
        self._pool_min_size = pool_min_size
        self._timeout = timeout
        self._schema_name = schema_name
        self._pool: Any = None
        self._initialized = False
        self._initialization_lock = asyncio.Lock()

    def initialize_sync(self) -> None:
        """Initialize from synchronous code, including synchronous agent hooks."""
        _run_sync(self.initialize())

    @_on_database_loop
    async def initialize(self) -> None:
        """Create the pool and schema once on the driver's owning event loop."""
        async with self._initialization_lock:
            if self._initialized:
                return
            if asyncpg is None:
                raise DatabaseStoreError(
                    "PostgreSQL support requires 'asyncpg' and 'sqlalchemy'. "
                    "Install with: pip install fireflyframework-agentic[postgres]"
                )
            try:
                self._pool = await asyncpg.create_pool(
                    self._url, min_size=self._pool_min_size, max_size=self._pool_size, timeout=self._timeout
                )
                await self._migrate_schema()
                self._initialized = True
                logger.info("PostgreSQL memory backend initialized")
            except (Exception, asyncio.CancelledError) as exc:
                if self._pool is not None:
                    try:
                        await self._pool.close()
                    except Exception:
                        logger.exception("Failed to close PostgreSQL pool after initialization failure")
                    finally:
                        self._pool = None
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise DatabaseConnectionError(f"Failed to connect to PostgreSQL: {exc}") from exc

    async def _migrate_schema(self) -> None:
        """Create the schema and required tables if they don't exist."""
        async with self._pool.acquire() as conn:
            # Create schema
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema_name}")

            # Create memory_entries table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._schema_name}.memory_entries (
                    entry_id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    key TEXT,
                    content JSONB NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ,
                    importance FLOAT NOT NULL DEFAULT 0.5,
                    CONSTRAINT valid_importance CHECK (importance >= 0.0 AND importance <= 1.0)
                )
            """)

            # Create indexes for efficient queries
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_namespace
                ON {self._schema_name}.memory_entries(namespace)
            """)

            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_namespace_key
                ON {self._schema_name}.memory_entries(namespace, key)
                WHERE key IS NOT NULL
            """)

            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_expires_at
                ON {self._schema_name}.memory_entries(expires_at)
                WHERE expires_at IS NOT NULL
            """)

            logger.debug("PostgreSQL schema migration completed")

    def save(self, namespace: str, entry: MemoryEntry) -> None:
        """Persist a single :class:`MemoryEntry` under *namespace*.

        This is the synchronous wrapper that runs the async version in a thread.
        """
        _run_sync(self.async_save(namespace, entry))

    @_on_database_loop
    async def async_save(self, namespace: str, entry: MemoryEntry) -> None:
        """Async version of :meth:`save`."""
        if not self._initialized:
            await self.initialize()

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self._schema_name}.memory_entries
                    (entry_id, namespace, scope, key, content, metadata, created_at, expires_at, importance)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (entry_id) DO UPDATE SET
                        scope = EXCLUDED.scope,
                        key = EXCLUDED.key,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        expires_at = EXCLUDED.expires_at,
                        importance = EXCLUDED.importance
                    """,
                    entry.entry_id,
                    namespace,
                    entry.scope.value,
                    entry.key,
                    entry.model_dump_json(),  # Store full entry as JSONB
                    json.dumps(entry.model_dump(mode="json")["metadata"]),
                    entry.created_at,
                    entry.expires_at,
                    entry.importance,
                )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to save entry: {exc}") from exc

    def load(self, namespace: str) -> list[MemoryEntry]:
        """Return all non-expired entries stored under *namespace*."""
        return _run_sync(self.async_load(namespace))

    @_on_database_loop
    async def async_load(self, namespace: str) -> list[MemoryEntry]:
        """Async version of :meth:`load`."""
        if not self._initialized:
            await self.initialize()

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT content FROM {self._schema_name}.memory_entries
                    WHERE namespace = $1
                      AND (expires_at IS NULL OR expires_at > $2)
                    ORDER BY created_at ASC
                    """,
                    namespace,
                    datetime.now(UTC),
                )

                return [MemoryEntry.model_validate_json(row["content"]) for row in rows]
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to load entries: {exc}") from exc

    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        """Return the entry matching *key*, or *None*."""
        return _run_sync(self.async_load_by_key(namespace, key))

    @_on_database_loop
    async def async_load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        """Async version of :meth:`load_by_key`."""
        if not self._initialized:
            await self.initialize()

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""
                    SELECT content FROM {self._schema_name}.memory_entries
                    WHERE namespace = $1
                      AND key = $2
                      AND (expires_at IS NULL OR expires_at > $3)
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    namespace,
                    key,
                    datetime.now(UTC),
                )

                if row is None:
                    return None

                return MemoryEntry.model_validate_json(row["content"])
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to load entry by key: {exc}") from exc

    def delete(self, namespace: str, entry_id: str) -> None:
        """Remove a single entry by ID."""
        _run_sync(self.async_delete(namespace, entry_id))

    @_on_database_loop
    async def async_delete(self, namespace: str, entry_id: str) -> None:
        """Async version of :meth:`delete`."""
        if not self._initialized:
            await self.initialize()

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"""
                    DELETE FROM {self._schema_name}.memory_entries
                    WHERE namespace = $1 AND entry_id = $2
                    """,
                    namespace,
                    entry_id,
                )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to delete entry: {exc}") from exc

    def clear(self, namespace: str) -> None:
        """Remove all entries in *namespace*."""
        _run_sync(self.async_clear(namespace))

    @_on_database_loop
    async def async_clear(self, namespace: str) -> None:
        """Async version of :meth:`clear`."""
        if not self._initialized:
            await self.initialize()

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"DELETE FROM {self._schema_name}.memory_entries WHERE namespace = $1",
                    namespace,
                )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to clear namespace: {exc}") from exc

    @_on_database_loop
    async def cleanup_expired(self) -> int:
        """Remove all expired entries across all namespaces.

        Returns:
            Number of entries deleted.
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    f"""
                    DELETE FROM {self._schema_name}.memory_entries
                    WHERE expires_at IS NOT NULL AND expires_at <= $1
                    """,
                    datetime.now(UTC),
                )
                # Extract count from result string like "DELETE 5"
                count = int(result.split()[-1]) if result and result.split() else 0
                logger.debug("Cleaned up %d expired entries", count)
                return count
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to cleanup expired entries: {exc}") from exc

    def close_sync(self) -> None:
        """Close the pool synchronously; call after all users of this store finish."""
        _run_sync(self.close())

    @_on_database_loop
    async def close(self) -> None:
        """Close the connection pool on its owning loop. Repeated calls are safe."""
        async with self._initialization_lock:
            if self._pool is not None:
                await self._pool.close()
                self._pool = None
                self._initialized = False
                logger.info("PostgreSQL connection pool closed")


# -- MongoDB Store ----------------------------------------------------------


class MongoDBStore:
    """MongoDB-backed memory store with connection pooling.

    This implementation uses motor (async MongoDB driver) for high-performance
    async access. It automatically creates indexes on first connection and
    supports namespace isolation.

    Parameters:
        url: MongoDB connection string (e.g., ``mongodb://localhost:27017/``).
        database: Database name to use for memory storage.
        collection: Collection name for memory entries.
        pool_size: Maximum number of connections in the pool.

    Note:
        Requires the optional ``mongodb`` dependency group:
        ``pip install fireflyframework-agentic[mongodb]``
    """

    def __init__(
        self,
        url: str,
        *,
        database: str = "firefly_memory",
        collection: str = "entries",
        pool_size: int = 10,
    ) -> None:
        self._url = url
        self._database_name = database
        self._collection_name = collection
        self._pool_size = pool_size
        self._client: Any = None
        self._db: Any = None
        self._collection: Any = None
        self._initialized = False
        self._initialization_lock = asyncio.Lock()

    def initialize_sync(self) -> None:
        """Initialize from synchronous code, including synchronous agent hooks."""
        _run_sync(self.initialize())

    @_on_database_loop
    async def initialize(self) -> None:
        """Create the client and indexes once on the driver's owning event loop."""
        async with self._initialization_lock:
            if self._initialized:
                return
            if AsyncIOMotorClient is None:
                raise DatabaseStoreError(
                    "MongoDB support requires 'motor' and 'pymongo'. "
                    "Install with: pip install fireflyframework-agentic[mongodb]"
                )
            try:
                self._client = AsyncIOMotorClient(self._url, maxPoolSize=self._pool_size, tz_aware=True)
                self._db = self._client[self._database_name]
                self._collection = self._db[self._collection_name]
                await self._client.admin.command("ping")
                await self._create_indexes()
                self._initialized = True
                logger.info("MongoDB memory backend initialized")
            except (Exception, asyncio.CancelledError) as exc:
                if self._client is not None:
                    self._client.close()
                self._client = self._db = self._collection = None
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise DatabaseConnectionError(f"Failed to connect to MongoDB: {exc}") from exc

    async def _create_indexes(self) -> None:
        """Create indexes for efficient queries."""
        try:
            # Compound index for namespace queries
            await self._collection.create_index([("namespace", 1)])

            # Compound index for namespace + key lookups
            await self._collection.create_index(
                [("namespace", 1), ("key", 1)],
                partialFilterExpression={"key": {"$exists": True}},
            )

            # Index for expiration cleanup
            await self._collection.create_index(
                [("expires_at", 1)],
                partialFilterExpression={"expires_at": {"$exists": True}},
            )

            # Unique index on entry_id
            await self._collection.create_index([("entry_id", 1)], unique=True)

            logger.debug("MongoDB indexes created")
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to create MongoDB indexes: {exc}") from exc

    def save(self, namespace: str, entry: MemoryEntry) -> None:
        """Persist a single :class:`MemoryEntry` under *namespace*."""
        _run_sync(self.async_save(namespace, entry))

    @_on_database_loop
    async def async_save(self, namespace: str, entry: MemoryEntry) -> None:
        """Async version of :meth:`save`."""
        if not self._initialized:
            await self.initialize()

        try:
            doc = entry.model_dump(mode="json")
            # BSON dates must remain datetimes for MongoDB comparison operators.
            doc["created_at"] = entry.created_at
            doc["expires_at"] = entry.expires_at
            doc["namespace"] = namespace
            doc["scope"] = entry.scope.value

            await self._collection.update_one(
                {"entry_id": entry.entry_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to save entry: {exc}") from exc

    def load(self, namespace: str) -> list[MemoryEntry]:
        """Return all non-expired entries stored under *namespace*."""
        return _run_sync(self.async_load(namespace))

    @_on_database_loop
    async def async_load(self, namespace: str) -> list[MemoryEntry]:
        """Async version of :meth:`load`."""
        if not self._initialized:
            await self.initialize()

        try:
            now = datetime.now(UTC)
            cursor = self._collection.find(
                {
                    "namespace": namespace,
                    "$or": [
                        {"expires_at": None},
                        {"expires_at": {"$gt": now}},
                    ],
                }
            ).sort("created_at", 1)

            docs = await cursor.to_list(length=None)
            return [MemoryEntry.model_validate(doc) for doc in docs]
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to load entries: {exc}") from exc

    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        """Return the entry matching *key*, or *None*."""
        return _run_sync(self.async_load_by_key(namespace, key))

    @_on_database_loop
    async def async_load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        """Async version of :meth:`load_by_key`."""
        if not self._initialized:
            await self.initialize()

        try:
            now = datetime.now(UTC)
            doc = await self._collection.find_one(
                {
                    "namespace": namespace,
                    "key": key,
                    "$or": [
                        {"expires_at": None},
                        {"expires_at": {"$gt": now}},
                    ],
                },
                sort=[("created_at", -1)],
            )

            if doc is None:
                return None

            return MemoryEntry.model_validate(doc)
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to load entry by key: {exc}") from exc

    def delete(self, namespace: str, entry_id: str) -> None:
        """Remove a single entry by ID."""
        _run_sync(self.async_delete(namespace, entry_id))

    @_on_database_loop
    async def async_delete(self, namespace: str, entry_id: str) -> None:
        """Async version of :meth:`delete`."""
        if not self._initialized:
            await self.initialize()

        try:
            await self._collection.delete_one({"namespace": namespace, "entry_id": entry_id})
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to delete entry: {exc}") from exc

    def clear(self, namespace: str) -> None:
        """Remove all entries in *namespace*."""
        _run_sync(self.async_clear(namespace))

    @_on_database_loop
    async def async_clear(self, namespace: str) -> None:
        """Async version of :meth:`clear`."""
        if not self._initialized:
            await self.initialize()

        try:
            await self._collection.delete_many({"namespace": namespace})
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to clear namespace: {exc}") from exc

    @_on_database_loop
    async def cleanup_expired(self) -> int:
        """Remove all expired entries across all namespaces.

        Returns:
            Number of entries deleted.
        """
        if not self._initialized:
            await self.initialize()

        try:
            result = await self._collection.delete_many({"expires_at": {"$exists": True, "$lte": datetime.now(UTC)}})
            count = result.deleted_count
            logger.debug("Cleaned up %d expired entries", count)
            return count
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to cleanup expired entries: {exc}") from exc

    def close_sync(self) -> None:
        """Close the client synchronously; call after all users of this store finish."""
        _run_sync(self.close())

    @_on_database_loop
    async def close(self) -> None:
        """Close the client on its owning loop. Repeated calls are safe."""
        async with self._initialization_lock:
            if self._client is not None:
                self._client.close()
                self._client = self._db = self._collection = None
                self._initialized = False
                logger.info("MongoDB connection closed")
