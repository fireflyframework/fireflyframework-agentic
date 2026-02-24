"""Tests for embeddings package public API."""

from __future__ import annotations


class TestEmbeddingsPublicAPI:
    def test_core_imports(self):
        from fireflyframework_genai.embeddings import (
            BaseEmbedder,
            EmbedderRegistry,
            EmbeddingProtocol,
            EmbeddingResult,
            EmbeddingUsage,
            cosine_similarity,
            dot_product,
            euclidean_distance,
        )

        assert BaseEmbedder is not None
        assert EmbeddingProtocol is not None
        assert EmbedderRegistry is not None
        assert EmbeddingResult is not None
        assert EmbeddingUsage is not None
        assert cosine_similarity is not None
        assert dot_product is not None
        assert euclidean_distance is not None

    def test_provider_imports(self):
        from fireflyframework_genai.embeddings.providers.openai import OpenAIEmbedder

        assert OpenAIEmbedder is not None
