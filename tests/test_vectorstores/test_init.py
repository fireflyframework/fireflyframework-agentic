"""Tests for vectorstores package public API."""

from __future__ import annotations


class TestVectorStoresPublicAPI:
    def test_imports(self):
        from fireflyframework_genai.vectorstores import (
            BaseVectorStore,
            InMemoryVectorStore,
            SearchFilter,
            SearchResult,
            VectorDocument,
            VectorStoreProtocol,
            VectorStoreRegistry,
        )

        assert BaseVectorStore is not None
        assert InMemoryVectorStore is not None
        assert VectorStoreProtocol is not None
        assert VectorStoreRegistry is not None
        assert VectorDocument is not None
        assert SearchResult is not None
        assert SearchFilter is not None
