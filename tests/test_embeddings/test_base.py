"""Tests for embedding protocol and base class."""

from __future__ import annotations

from fireflyframework_genai.embeddings.base import BaseEmbedder, EmbeddingProtocol
from fireflyframework_genai.embeddings.types import EmbeddingResult


class _FakeEmbedder(BaseEmbedder):
    """Concrete embedder for testing."""

    def __init__(self):
        super().__init__(model="fake-model", dimensions=3)
        self.call_count = 0

    async def _embed_batch(self, texts: list[str], **kwargs) -> list[list[float]]:
        self.call_count += 1
        return [[float(len(t)), 0.0, 1.0] for t in texts]


class TestEmbeddingProtocol:
    def test_fake_embedder_satisfies_protocol(self):
        embedder = _FakeEmbedder()
        assert isinstance(embedder, EmbeddingProtocol)


class TestBaseEmbedder:
    async def test_embed_returns_result(self):
        embedder = _FakeEmbedder()
        result = await embedder.embed(["hello", "world"])
        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "fake-model"
        assert result.dimensions == 3

    async def test_embed_one(self):
        embedder = _FakeEmbedder()
        vec = await embedder.embed_one("test")
        assert isinstance(vec, list)
        assert len(vec) == 3

    async def test_batching(self):
        embedder = _FakeEmbedder()
        embedder._batch_size = 2
        texts = ["a", "b", "c", "d", "e"]
        result = await embedder.embed(texts)
        assert len(result.embeddings) == 5
        # With batch_size=2, 5 texts should produce 3 batches
        assert embedder.call_count == 3

    async def test_empty_input(self):
        embedder = _FakeEmbedder()
        result = await embedder.embed([])
        assert result.embeddings == []
        assert result.usage.total_tokens == 0

    async def test_model_property(self):
        embedder = _FakeEmbedder()
        assert embedder.model == "fake-model"
