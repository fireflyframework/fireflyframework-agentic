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

"""Database-backed memory store implementations.

This module provides production-grade persistence backends using PostgreSQL
and MongoDB. Both implementations support connection pooling, automatic
schema migration, and namespace-scoped isolation.

Examples:
    PostgreSQL backend::

        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        store = PostgreSQLStore(
            url="postgresql://user:pass@localhost/firefly",
            pool_size=10
        )
        await store.initialize()

        # Use like any other MemoryStore
        store.save("agent_1", entry)

    MongoDB backend::

        from fireflyframework_genai.memory.database_store import MongoDBStore

        store = MongoDBStore(
            url="mongodb://localhost:27017/",
            database="firefly_memory",
            pool_size=10
        )
        await store.initialize()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fireflyframework_genai.exceptions import DatabaseConnectionError, DatabaseStoreError
from fireflyframework_genai.memory.types import MemoryEntry

logger = logging.getLogger(__name__)

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
        ``pip install fireflyframework-genai[postgres]``
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
        self._url = url
        self._pool_size = pool_size
        self._pool_min_size = pool_min_size
        self._timeout = timeout
        self._schema_name = schema_name
        self._pool: Any = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create the connection pool and initialize the schema.

        This method must be called before any other operations.
        It's safe to call multiple times (subsequent calls are no-ops).

        Raises:
            DatabaseConnectionError: If connection to PostgreSQL fails.
        """
        if self._initialized:
            return

        try:
            import asyncpg  # type: ignore[import-not-found]
        except ImportError as exc:
            raise DatabaseStoreError(
                "PostgreSQL support requires 'asyncpg' and 'sqlalchemy'. "
                "Install with: pip install fireflyframework-genai[postgres]"
            ) from exc

        try:
            self._pool = await asyncpg.create_pool(
                self._url,
                min_size=self._pool_min_size,
                max_size=self._pool_size,
                timeout=self._timeout,
            )
            logger.info(
                "PostgreSQL connection pool created (min=%d, max=%d)",
                self._pool_min_size,
                self._pool_size,
            )
        except Exception as exc:
            raise DatabaseConnectionError(f"Failed to connect to PostgreSQL: {exc}") from exc

        # Create schema and tables
        await self._migrate_schema()
        self._initialized = True

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
        asyncio.run(self.async_save(namespace, entry))

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
                    entry.metadata,
                    entry.created_at,
                    entry.expires_at,
                    entry.importance,
                )
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to save entry: {exc}") from exc

    def load(self, namespace: str) -> list[MemoryEntry]:
        """Return all non-expired entries stored under *namespace*."""
        return asyncio.run(self.async_load(namespace))

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
        return asyncio.run(self.async_load_by_key(namespace, key))

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
        asyncio.run(self.async_delete(namespace, entry_id))

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
        asyncio.run(self.async_clear(namespace))

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

    async def close(self) -> None:
        """Close the connection pool.

        Should be called during application shutdown.
        """
        if self._pool is not None:
            await self._pool.close()
            logger.info("PostgreSQL connection pool closed")
            self._initialized = False


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
        ``pip install fireflyframework-genai[mongodb]``
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

    async def initialize(self) -> None:
        """Create the connection and initialize indexes.

        This method must be called before any other operations.
        It's safe to call multiple times (subsequent calls are no-ops).

        Raises:
            DatabaseConnectionError: If connection to MongoDB fails.
        """
        if self._initialized:
            return

        try:
            from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise DatabaseStoreError(
                "MongoDB support requires 'motor' and 'pymongo'. "
                "Install with: pip install fireflyframework-genai[mongodb]"
            ) from exc

        try:
            self._client = AsyncIOMotorClient(self._url, maxPoolSize=self._pool_size)
            self._db = self._client[self._database_name]
            self._collection = self._db[self._collection_name]

            # Test connection
            await self._client.admin.command("ping")
            logger.info(
                "MongoDB connected (database=%s, collection=%s, pool_size=%d)",
                self._database_name,
                self._collection_name,
                self._pool_size,
            )
        except Exception as exc:
            raise DatabaseConnectionError(f"Failed to connect to MongoDB: {exc}") from exc

        # Create indexes
        await self._create_indexes()
        self._initialized = True

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
            logger.warning("Failed to create MongoDB indexes: %s", exc)

    def save(self, namespace: str, entry: MemoryEntry) -> None:
        """Persist a single :class:`MemoryEntry` under *namespace*."""
        asyncio.run(self.async_save(namespace, entry))

    async def async_save(self, namespace: str, entry: MemoryEntry) -> None:
        """Async version of :meth:`save`."""
        if not self._initialized:
            await self.initialize()

        try:
            doc = entry.model_dump(mode="json")
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
        return asyncio.run(self.async_load(namespace))

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
        return asyncio.run(self.async_load_by_key(namespace, key))

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
        asyncio.run(self.async_delete(namespace, entry_id))

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
        asyncio.run(self.async_clear(namespace))

    async def async_clear(self, namespace: str) -> None:
        """Async version of :meth:`clear`."""
        if not self._initialized:
            await self.initialize()

        try:
            await self._collection.delete_many({"namespace": namespace})
        except Exception as exc:
            raise DatabaseStoreError(f"Failed to clear namespace: {exc}") from exc

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

    async def close(self) -> None:
        """Close the MongoDB connection.

        Should be called during application shutdown.
        """
        if self._client is not None:
            self._client.close()
            logger.info("MongoDB connection closed")
            self._initialized = False
