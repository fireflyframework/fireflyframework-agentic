"""Tests for vector store registry."""

from __future__ import annotations

import pytest

from fireflyframework_genai.vectorstores.memory_store import InMemoryVectorStore
from fireflyframework_genai.vectorstores.registry import VectorStoreRegistry


class TestVectorStoreRegistry:
    def test_register_and_get(self):
        registry = VectorStoreRegistry()
        store = InMemoryVectorStore()
        registry.register("test", store)
        assert registry.get("test") is store

    def test_get_nonexistent_raises(self):
        registry = VectorStoreRegistry()
        with pytest.raises(KeyError, match="nonexistent"):
            registry.get("nonexistent")

    def test_list_names(self):
        registry = VectorStoreRegistry()
        registry.register("a", InMemoryVectorStore())
        registry.register("b", InMemoryVectorStore())
        assert set(registry.list_names()) == {"a", "b"}

    def test_unregister(self):
        registry = VectorStoreRegistry()
        registry.register("x", InMemoryVectorStore())
        registry.unregister("x")
        with pytest.raises(KeyError):
            registry.get("x")

    def test_unregister_nonexistent_is_noop(self):
        registry = VectorStoreRegistry()
        registry.unregister("nonexistent")  # Should not raise

    def test_list_names_empty(self):
        registry = VectorStoreRegistry()
        assert registry.list_names() == []

    def test_register_overwrites(self):
        registry = VectorStoreRegistry()
        store1 = InMemoryVectorStore()
        store2 = InMemoryVectorStore()
        registry.register("x", store1)
        registry.register("x", store2)
        assert registry.get("x") is store2
        assert registry.list_names() == ["x"]
