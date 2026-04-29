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

"""Unit tests for SQLiteStore using real on-disk SQLite databases.

Unlike test_mongodb_store.py and test_postgres_store.py, these tests use
real SQLite files (sqlite3 is stdlib — no service or mocking needed).
Each test gets its own temp file via the ``tmp_path`` fixture.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fireflyframework_agentic.memory.database_store import SQLiteStore
from fireflyframework_agentic.memory.types import MemoryEntry, MemoryScope


def _entry(**overrides: Any) -> MemoryEntry:
    """Build a MemoryEntry with sensible defaults for tests."""
    defaults: dict[str, Any] = {"scope": MemoryScope.WORKING, "content": "data"}
    defaults.update(overrides)
    return MemoryEntry(**defaults)


def test_save_and_load_roundtrip(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    entry = _entry(key="k1", content="hello")

    store.save("ns", entry)
    loaded = store.load("ns")

    assert len(loaded) == 1
    assert loaded[0].entry_id == entry.entry_id
    assert loaded[0].key == "k1"
    assert loaded[0].content == "hello"
    assert loaded[0].scope == MemoryScope.WORKING
    store.close()


def test_save_overwrites_same_entry_id(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    eid = "fixed-id"
    store.save("ns", _entry(entry_id=eid, content="first"))
    store.save("ns", _entry(entry_id=eid, content="second"))

    loaded = store.load("ns")
    assert len(loaded) == 1
    assert loaded[0].content == "second"
    store.close()


def test_load_returns_empty_for_unknown_namespace(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    assert store.load("unknown") == []
    store.close()


def test_load_by_key_hit_and_miss(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    store.save("ns", _entry(key="alpha", content="a"))
    store.save("ns", _entry(key="beta", content="b"))

    hit = store.load_by_key("ns", "alpha")
    assert hit is not None
    assert hit.content == "a"

    miss = store.load_by_key("ns", "gamma")
    assert miss is None
    store.close()


def test_delete_removes_specific_entry(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    e1 = _entry(content="one")
    e2 = _entry(content="two")
    store.save("ns", e1)
    store.save("ns", e2)

    store.delete("ns", e1.entry_id)
    remaining = store.load("ns")

    assert len(remaining) == 1
    assert remaining[0].entry_id == e2.entry_id
    store.close()


def test_clear_removes_all_in_namespace(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    store.save("ns_a", _entry())
    store.save("ns_a", _entry())
    store.save("ns_b", _entry())

    store.clear("ns_a")

    assert store.load("ns_a") == []
    assert len(store.load("ns_b")) == 1
    store.close()


def test_namespace_isolation(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    store.save("ns_a", _entry(key="k", content="A"))
    store.save("ns_b", _entry(key="k", content="B"))

    a = store.load_by_key("ns_a", "k")
    b = store.load_by_key("ns_b", "k")

    assert a is not None and a.content == "A"
    assert b is not None and b.content == "B"
    store.close()


def test_load_filters_expired_entries(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    past = datetime.now(UTC) - timedelta(seconds=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    store.save("ns", _entry(content="old", expires_at=past))
    store.save("ns", _entry(content="fresh", expires_at=future))
    store.save("ns", _entry(content="forever"))

    loaded = store.load("ns")
    contents = {e.content for e in loaded}

    assert contents == {"fresh", "forever"}
    store.close()


def test_load_by_key_filters_expired(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    past = datetime.now(UTC) - timedelta(seconds=1)
    store.save("ns", _entry(key="k", content="old", expires_at=past))

    assert store.load_by_key("ns", "k") is None
    store.close()


def test_cleanup_expired_returns_count_and_keeps_fresh(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    past = datetime.now(UTC) - timedelta(seconds=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    store.save("ns", _entry(expires_at=past))
    store.save("ns", _entry(expires_at=past))
    store.save("ns", _entry(expires_at=future))
    store.save("ns", _entry())

    deleted = store.cleanup_expired()

    assert deleted == 2
    assert len(store.load("ns")) == 2
    store.close()


def test_invalid_table_name_raises(tmp_path):
    with pytest.raises(ValueError, match="Invalid table_name"):
        SQLiteStore(tmp_path / "memory.sqlite", table_name="bad-name; DROP TABLE")


def test_custom_table_name_used(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite", table_name="custom_table")
    store.save("ns", _entry(content="data"))

    assert len(store.load("ns")) == 1
    store.close()


def test_persistence_across_instances(tmp_path):
    db = tmp_path / "memory.sqlite"
    store_a = SQLiteStore(db)
    store_a.save("ns", _entry(key="persisted", content="value"))
    store_a.close()

    store_b = SQLiteStore(db)
    loaded = store_b.load_by_key("ns", "persisted")

    assert loaded is not None
    assert loaded.content == "value"
    store_b.close()


def test_wal_mode_can_be_enabled(tmp_path):
    db = tmp_path / "memory.sqlite"
    store = SQLiteStore(db, wal=True)
    store.save("ns", _entry())
    store.close()

    conn = sqlite3.connect(str(db))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    assert mode.lower() == "wal"


def test_close_is_idempotent(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    store.close()
    store.close()


def test_parent_directory_is_created(tmp_path):
    nested = tmp_path / "deep" / "path" / "memory.sqlite"
    store = SQLiteStore(nested)

    assert nested.parent.exists()
    store.save("ns", _entry())
    assert len(store.load("ns")) == 1
    store.close()


def test_metadata_and_importance_round_trip(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    entry = _entry(
        key="k",
        content={"nested": {"data": [1, 2, 3]}},
        metadata={"agent": "test", "tags": ["a", "b"]},
        importance=0.9,
    )
    store.save("ns", entry)

    loaded = store.load_by_key("ns", "k")

    assert loaded is not None
    assert loaded.content == {"nested": {"data": [1, 2, 3]}}
    assert loaded.metadata == {"agent": "test", "tags": ["a", "b"]}
    assert loaded.importance == 0.9
    store.close()


def test_load_returns_entries_ordered_by_created_at(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    base = datetime.now(UTC)
    e_old = _entry(content="old", created_at=base - timedelta(minutes=2))
    e_new = _entry(content="new", created_at=base)
    e_mid = _entry(content="mid", created_at=base - timedelta(minutes=1))

    store.save("ns", e_new)
    store.save("ns", e_old)
    store.save("ns", e_mid)

    contents = [e.content for e in store.load("ns")]

    assert contents == ["old", "mid", "new"]
    store.close()


@pytest.mark.asyncio
async def test_async_save_and_load(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    await store.async_save("ns", _entry(key="async", content="async_value"))

    loaded = await store.async_load("ns")
    by_key = await store.async_load_by_key("ns", "async")

    assert len(loaded) == 1
    assert loaded[0].content == "async_value"
    assert by_key is not None
    assert by_key.content == "async_value"
    store.close()


@pytest.mark.asyncio
async def test_async_delete_and_clear(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    e = _entry()
    await store.async_save("ns", e)
    await store.async_delete("ns", e.entry_id)
    assert await store.async_load("ns") == []

    await store.async_save("ns", _entry())
    await store.async_clear("ns")
    assert await store.async_load("ns") == []
    store.close()


@pytest.mark.asyncio
async def test_async_cleanup_expired(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    past = datetime.now(UTC) - timedelta(seconds=1)
    await store.async_save("ns", _entry(expires_at=past))

    deleted = await store.async_cleanup_expired()

    assert deleted == 1
    store.close()
