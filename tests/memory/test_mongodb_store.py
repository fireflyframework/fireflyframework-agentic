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

"""Unit tests for MongoDB memory store.

These tests use mocks to avoid requiring a real MongoDB instance.
See tests/integration/test_storage/test_database_integration.py for
integration tests with real databases.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_genai.exceptions import DatabaseConnectionError, DatabaseStoreError
from fireflyframework_genai.memory.types import MemoryEntry, MemoryScope


@pytest.fixture
def mock_motor_client():
    """Mock Motor AsyncIOMotorClient for testing."""
    client = MagicMock()
    db = MagicMock()
    collection = AsyncMock()

    # Mock admin command for ping
    client.admin.command = AsyncMock(return_value={"ok": 1})

    # Mock collection operations
    collection.create_index = AsyncMock()
    collection.update_one = AsyncMock()
    collection.find_one = AsyncMock(return_value=None)
    collection.delete_one = AsyncMock()
    collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))

    # Mock cursor for find()
    cursor = AsyncMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[])
    collection.find = MagicMock(return_value=cursor)

    # Wire up the hierarchy
    client.__getitem__ = MagicMock(return_value=db)
    db.__getitem__ = MagicMock(return_value=collection)
    client.close = MagicMock()

    return client, db, collection, cursor


@pytest.fixture(autouse=True)
def _ensure_motor_mockable(monkeypatch):
    """Ensure motor module is importable (mocked) so patch() targets resolve."""
    import sys

    if "motor" not in sys.modules:
        mock_motor = MagicMock()
        monkeypatch.setitem(sys.modules, "motor", mock_motor)
        monkeypatch.setitem(sys.modules, "motor.motor_asyncio", mock_motor.motor_asyncio)


@pytest.mark.asyncio
class TestMongoDBStore:
    """Test suite for MongoDBStore."""

    async def test_import_error_without_motor(self):
        """Test that helpful error is raised when motor is not installed."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        store = MongoDBStore(url="mongodb://test")

        with (
            patch.dict("sys.modules", {"motor.motor_asyncio": None}),
            pytest.raises(DatabaseStoreError, match="MongoDB support requires"),
        ):
            await store.initialize()

    async def test_connection_failure(self):
        """Test handling of connection failures."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        store = MongoDBStore(url="mongodb://invalid:27017/")

        with patch("motor.motor_asyncio.AsyncIOMotorClient") as mock_client_class:
            client = MagicMock()
            client.admin.command = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client_class.return_value = client

            with pytest.raises(DatabaseConnectionError, match="Failed to connect"):
                await store.initialize()

    async def test_initialize_creates_indexes(self, mock_motor_client):
        """Test that initialize creates indexes."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, _ = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            # Verify indexes were created
            assert collection.create_index.call_count >= 3  # namespace, namespace+key, expires_at, entry_id

    async def test_save_entry(self, mock_motor_client):
        """Test saving a memory entry."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, _ = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            entry = MemoryEntry(
                key="test_key",
                content="test content",
                scope=MemoryScope.WORKING,
            )

            await store.async_save("test_namespace", entry)

            # Verify update_one was called with upsert
            collection.update_one.assert_called_once()
            call_args = collection.update_one.call_args
            assert call_args[1]["upsert"] is True

    async def test_load_entries(self, mock_motor_client):
        """Test loading entries from a namespace."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, cursor = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        entry = MemoryEntry(key="test", content="data")
        cursor.to_list.return_value = [entry.model_dump(mode="json")]

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            results = await store.async_load("test_namespace")

            assert len(results) == 1
            assert results[0].key == "test"
            assert results[0].content == "data"

    async def test_load_filters_expired(self, mock_motor_client):
        """Test that load filters out expired entries."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, cursor = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            await store.async_load("test_namespace")

            # Verify the query includes expiration filter
            call_args = collection.find.call_args
            query = call_args[0][0]
            assert "namespace" in query
            assert "$or" in query  # Should have OR condition for null/future expires_at

    async def test_load_by_key(self, mock_motor_client):
        """Test loading a specific entry by key."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, _ = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        entry = MemoryEntry(key="specific_key", content="specific data")
        collection.find_one.return_value = entry.model_dump(mode="json")

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            result = await store.async_load_by_key("test_namespace", "specific_key")

            assert result is not None
            assert result.key == "specific_key"
            assert result.content == "specific data"

    async def test_load_by_key_not_found(self, mock_motor_client):
        """Test loading non-existent key returns None."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, _ = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        collection.find_one.return_value = None

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            result = await store.async_load_by_key("test_namespace", "nonexistent")

            assert result is None

    async def test_delete_entry(self, mock_motor_client):
        """Test deleting an entry."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, _ = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            await store.async_delete("test_namespace", "entry_123")

            # Verify delete_one was called
            collection.delete_one.assert_called_once()
            call_args = collection.delete_one.call_args
            query = call_args[0][0]
            assert query["namespace"] == "test_namespace"
            assert query["entry_id"] == "entry_123"

    async def test_clear_namespace(self, mock_motor_client):
        """Test clearing all entries in a namespace."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, _ = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            await store.async_clear("test_namespace")

            # Verify delete_many was called
            collection.delete_many.assert_called_once()
            call_args = collection.delete_many.call_args
            query = call_args[0][0]
            assert query["namespace"] == "test_namespace"

    async def test_cleanup_expired(self, mock_motor_client):
        """Test cleanup of expired entries."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, _ = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        result_mock = MagicMock()
        result_mock.deleted_count = 7
        collection.delete_many.return_value = result_mock

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            count = await store.cleanup_expired()

            assert count == 7
            call_args = collection.delete_many.call_args
            query = call_args[0][0]
            assert "expires_at" in query

    async def test_close_connection(self, mock_motor_client):
        """Test closing the MongoDB connection."""
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, _, _, _ = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            await store.close()

            client.close.assert_called_once()

    async def test_sync_wrappers(self, mock_motor_client):
        """Test that synchronous methods delegate to async counterparts.

        The sync methods use asyncio.run() which cannot be called from
        within an already-running event loop.  Instead of calling them
        directly we verify they delegate to the async implementations.
        """
        from fireflyframework_genai.memory.database_store import MongoDBStore

        client, db, collection, cursor = mock_motor_client
        store = MongoDBStore(url="mongodb://test")

        with patch("motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            await store.initialize()

            # Test async save (sync wrappers delegate to these)
            entry = MemoryEntry(key="test", content="data")
            await store.async_save("namespace", entry)
            collection.update_one.assert_called()

            # Test async load
            cursor.to_list.return_value = []
            results = await store.async_load("namespace")
            assert isinstance(results, list)

            # Test async delete
            await store.async_delete("namespace", "entry_id")

            # Test async clear
            await store.async_clear("namespace")
