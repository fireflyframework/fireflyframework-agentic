"""Tests for embedding data models."""

from __future__ import annotations

from fireflyframework_genai.embeddings.types import EmbeddingResult, EmbeddingUsage


class TestEmbeddingUsage:
    def test_create(self):
        usage = EmbeddingUsage(total_tokens=150)
        assert usage.total_tokens == 150


class TestEmbeddingResult:
    def test_create(self):
        result = EmbeddingResult(
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            model="test-model",
            usage=EmbeddingUsage(total_tokens=10),
            dimensions=3,
        )
        assert len(result.embeddings) == 2
        assert result.dimensions == 3
        assert result.model == "test-model"
        assert result.usage.total_tokens == 10

    def test_serialization(self):
        result = EmbeddingResult(
            embeddings=[[1.0, 2.0]],
            model="m",
            usage=EmbeddingUsage(total_tokens=5),
            dimensions=2,
        )
        data = result.model_dump()
        assert data["model"] == "m"
        assert data["dimensions"] == 2
