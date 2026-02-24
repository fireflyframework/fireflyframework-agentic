"""Tests for the embedder registry."""

from __future__ import annotations

import pytest

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.embeddings.registry import EmbedderRegistry


class _FakeEmbedder(BaseEmbedder):
    def __init__(self, model: str = "fake"):
        super().__init__(model=model, dimensions=3)

    async def _embed_batch(self, texts, **kwargs):
        return [[0.0] * 3 for _ in texts]


class TestEmbedderRegistry:
    def test_register_and_get(self):
        registry = EmbedderRegistry()
        embedder = _FakeEmbedder("test-model")
        registry.register("test", embedder)
        assert registry.get("test") is embedder

    def test_get_nonexistent_raises(self):
        registry = EmbedderRegistry()
        with pytest.raises(KeyError, match="nonexistent"):
            registry.get("nonexistent")

    def test_list_embedders(self):
        registry = EmbedderRegistry()
        registry.register("a", _FakeEmbedder("a"))
        registry.register("b", _FakeEmbedder("b"))
        assert set(registry.list_names()) == {"a", "b"}

    def test_unregister(self):
        registry = EmbedderRegistry()
        registry.register("x", _FakeEmbedder("x"))
        registry.unregister("x")
        with pytest.raises(KeyError):
            registry.get("x")
