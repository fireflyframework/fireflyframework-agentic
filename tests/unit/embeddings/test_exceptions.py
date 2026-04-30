"""Tests for embedding and vector store exceptions."""

from __future__ import annotations

from fireflyframework_agentic.exceptions import (
    EmbeddingError,
    EmbeddingProviderError,
    FireflyAgenticError,
    VectorStoreConnectionError,
    VectorStoreError,
)


class TestEmbeddingExceptions:
    def test_embedding_error_inherits_base(self):
        assert issubclass(EmbeddingError, FireflyAgenticError)

    def test_embedding_provider_error_inherits_embedding(self):
        assert issubclass(EmbeddingProviderError, EmbeddingError)

    def test_vector_store_error_inherits_base(self):
        assert issubclass(VectorStoreError, FireflyAgenticError)

    def test_vector_store_connection_inherits(self):
        assert issubclass(VectorStoreConnectionError, VectorStoreError)

    def test_embedding_error_message(self):
        err = EmbeddingError("test error")
        assert str(err) == "test error"
