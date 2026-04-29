"""Tests for async FileStore wrappers."""

from __future__ import annotations

from pathlib import Path

from fireflyframework_agentic.memory.store import FileStore
from fireflyframework_agentic.memory.types import MemoryEntry


class TestAsyncFileStore:
    async def test_async_save_and_load(self, tmp_path: Path) -> None:
        store = FileStore(base_dir=tmp_path)
        entry = MemoryEntry(key="test_key", content="test_value")
        await store.async_save("ns", entry)
        entries = await store.async_load("ns")
        assert len(entries) == 1
        assert entries[0].key == "test_key"

    async def test_async_load_by_key(self, tmp_path: Path) -> None:
        store = FileStore(base_dir=tmp_path)
        entry = MemoryEntry(key="k1", content="v1")
        await store.async_save("ns", entry)
        found = await store.async_load_by_key("ns", "k1")
        assert found is not None
        assert found.content == "v1"

    async def test_async_delete(self, tmp_path: Path) -> None:
        store = FileStore(base_dir=tmp_path)
        entry = MemoryEntry(key="k1", content="v1")
        await store.async_save("ns", entry)
        await store.async_delete("ns", entry.entry_id)
        entries = await store.async_load("ns")
        assert len(entries) == 0

    async def test_async_clear(self, tmp_path: Path) -> None:
        store = FileStore(base_dir=tmp_path)
        await store.async_save("ns", MemoryEntry(key="k1", content="v1"))
        await store.async_clear("ns")
        entries = await store.async_load("ns")
        assert len(entries) == 0
