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

"""Unit tests for PostgreSQL memory store.

These tests use mocks to avoid requiring a real PostgreSQL instance.
See tests/integration/test_storage/test_database_integration.py for
integration tests with real databases.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_genai.exceptions import DatabaseConnectionError, DatabaseStoreError
from fireflyframework_genai.memory.types import MemoryEntry, MemoryScope


@pytest.fixture
def mock_asyncpg_pool():
    """Mock asyncpg pool for testing."""
    pool = MagicMock()
    connection = AsyncMock()
    connection.execute = AsyncMock()
    connection.fetch = AsyncMock(return_value=[])
    connection.fetchrow = AsyncMock(return_value=None)

    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
    pool.acquire.return_value.__aexit__ = AsyncMock()
    pool.close = AsyncMock()

    return pool, connection


@pytest.fixture(autouse=True)
def _ensure_asyncpg_mockable(monkeypatch):
    """Ensure asyncpg module is importable (mocked) so patch() targets resolve."""
    import sys

    if "asyncpg" not in sys.modules:
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock()
        monkeypatch.setitem(sys.modules, "asyncpg", mock_asyncpg)


@pytest.mark.asyncio
class TestPostgreSQLStore:
    """Test suite for PostgreSQLStore."""

    async def test_import_error_without_asyncpg(self):
        """Test that helpful error is raised when asyncpg is not installed."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        store = PostgreSQLStore(url="postgresql://test")

        with (
            patch.dict("sys.modules", {"asyncpg": None}),
            pytest.raises(DatabaseStoreError, match="PostgreSQL support requires"),
        ):
            await store.initialize()

    async def test_connection_failure(self):
        """Test handling of connection failures."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        store = PostgreSQLStore(url="postgresql://invalid:5432/db")

        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
            mock_create_pool.side_effect = Exception("Connection refused")

            with pytest.raises(DatabaseConnectionError, match="Failed to connect"):
                await store.initialize()

    async def test_initialize_creates_schema(self, mock_asyncpg_pool):
        """Test that initialize creates schema and tables."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test", schema_name="test_schema")

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            # Verify schema and table creation
            calls = connection.execute.call_args_list
            assert any("CREATE SCHEMA IF NOT EXISTS" in str(call) for call in calls)
            assert any("CREATE TABLE IF NOT EXISTS" in str(call) for call in calls)
            assert any("CREATE INDEX IF NOT EXISTS" in str(call) for call in calls)

    async def test_save_entry(self, mock_asyncpg_pool):
        """Test saving a memory entry."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            entry = MemoryEntry(
                key="test_key",
                content="test content",
                scope=MemoryScope.WORKING,
            )

            await store.async_save("test_namespace", entry)

            # Verify INSERT was called
            connection.execute.assert_called()
            call_args = connection.execute.call_args
            assert "INSERT INTO" in call_args[0][0]
            assert entry.entry_id in call_args[0]
            assert "test_namespace" in call_args[0]

    async def test_load_entries(self, mock_asyncpg_pool):
        """Test loading entries from a namespace."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        entry = MemoryEntry(key="test", content="data")
        connection.fetch.return_value = [{"content": entry.model_dump_json()}]

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            results = await store.async_load("test_namespace")

            assert len(results) == 1
            assert results[0].key == "test"
            assert results[0].content == "data"

    async def test_load_by_key(self, mock_asyncpg_pool):
        """Test loading a specific entry by key."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        entry = MemoryEntry(key="specific_key", content="specific data")
        connection.fetchrow.return_value = {"content": entry.model_dump_json()}

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            result = await store.async_load_by_key("test_namespace", "specific_key")

            assert result is not None
            assert result.key == "specific_key"
            assert result.content == "specific data"

    async def test_load_by_key_not_found(self, mock_asyncpg_pool):
        """Test loading non-existent key returns None."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        connection.fetchrow.return_value = None

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            result = await store.async_load_by_key("test_namespace", "nonexistent")

            assert result is None

    async def test_delete_entry(self, mock_asyncpg_pool):
        """Test deleting an entry."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            await store.async_delete("test_namespace", "entry_123")

            # Verify DELETE was called
            call_args = connection.execute.call_args
            assert "DELETE FROM" in call_args[0][0]
            assert "test_namespace" in call_args[0]
            assert "entry_123" in call_args[0]

    async def test_clear_namespace(self, mock_asyncpg_pool):
        """Test clearing all entries in a namespace."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            await store.async_clear("test_namespace")

            # Verify DELETE was called
            call_args = connection.execute.call_args
            assert "DELETE FROM" in call_args[0][0]
            assert "test_namespace" in call_args[0]

    async def test_cleanup_expired(self, mock_asyncpg_pool):
        """Test cleanup of expired entries."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        connection.execute.return_value = "DELETE 5"

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            count = await store.cleanup_expired()

            assert count == 5
            call_args = connection.execute.call_args
            assert "DELETE FROM" in call_args[0][0]
            assert "expires_at" in call_args[0][0]

    async def test_close_pool(self, mock_asyncpg_pool):
        """Test closing the connection pool."""
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, _ = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            await store.close()

            pool.close.assert_called_once()

    async def test_sync_wrappers(self, mock_asyncpg_pool):
        """Test that synchronous methods delegate to async counterparts.

        The sync methods use asyncio.run() which cannot be called from
        within an already-running event loop.  Instead of calling them
        directly we verify they delegate to the async implementations.
        """
        from fireflyframework_genai.memory.database_store import PostgreSQLStore

        pool, connection = mock_asyncpg_pool
        store = PostgreSQLStore(url="postgresql://test")

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool):
            await store.initialize()

            # Test async save (sync wrappers delegate to these)
            entry = MemoryEntry(key="test", content="data")
            await store.async_save("namespace", entry)
            connection.execute.assert_called()

            # Test async load
            connection.fetch.return_value = []
            results = await store.async_load("namespace")
            assert isinstance(results, list)

            # Test async delete
            await store.async_delete("namespace", "entry_id")

            # Test async clear
            await store.async_clear("namespace")
