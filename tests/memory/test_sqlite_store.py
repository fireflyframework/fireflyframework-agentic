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

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fireflyframework_agentic.memory.store import SQLiteStore
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


def test_save_overwrites_same_entry_id(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    eid = "fixed-id"
    store.save("ns", _entry(entry_id=eid, content="first"))
    store.save("ns", _entry(entry_id=eid, content="second"))

    loaded = store.load("ns")

    assert len(loaded) == 1
    assert loaded[0].content == "second"


def test_load_returns_empty_for_unknown_namespace(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    assert store.load("unknown") == []


def test_load_by_key_hit_and_miss(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    store.save("ns", _entry(key="alpha", content="a"))
    store.save("ns", _entry(key="beta", content="b"))

    hit = store.load_by_key("ns", "alpha")
    assert hit is not None
    assert hit.content == "a"

    miss = store.load_by_key("ns", "gamma")
    assert miss is None


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


def test_clear_removes_all_in_namespace(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    store.save("ns_a", _entry())
    store.save("ns_a", _entry())
    store.save("ns_b", _entry())

    store.clear("ns_a")

    assert store.load("ns_a") == []
    assert len(store.load("ns_b")) == 1


def test_namespace_isolation(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    store.save("ns_a", _entry(key="k", content="A"))
    store.save("ns_b", _entry(key="k", content="B"))

    a = store.load_by_key("ns_a", "k")
    b = store.load_by_key("ns_b", "k")

    assert a is not None and a.content == "A"
    assert b is not None and b.content == "B"


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


def test_load_by_key_filters_expired(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    past = datetime.now(UTC) - timedelta(seconds=1)
    store.save("ns", _entry(key="k", content="old", expires_at=past))

    assert store.load_by_key("ns", "k") is None


def test_persistence_across_instances(tmp_path):
    db = tmp_path / "memory.sqlite"
    SQLiteStore(db).save("ns", _entry(key="persisted", content="value"))

    loaded = SQLiteStore(db).load_by_key("ns", "persisted")

    assert loaded is not None
    assert loaded.content == "value"


def test_parent_directory_is_created(tmp_path):
    nested = tmp_path / "deep" / "path" / "memory.sqlite"
    store = SQLiteStore(nested)

    assert nested.parent.exists()
    store.save("ns", _entry())
    assert len(store.load("ns")) == 1


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


def test_load_returns_entries_in_insertion_order(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    store.save("ns", _entry(content="first"))
    store.save("ns", _entry(content="second"))
    store.save("ns", _entry(content="third"))

    contents = [e.content for e in store.load("ns")]

    assert contents == ["first", "second", "third"]


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
