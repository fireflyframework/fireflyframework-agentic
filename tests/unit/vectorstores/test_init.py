"""Tests for vectorstores package public API."""

from __future__ import annotations


class TestVectorStoresPublicAPI:
    def test_imports(self):
        from fireflyframework_agentic.vectorstores import (
            BaseVectorStore,
            InMemoryVectorStore,
            PgVectorVectorStore,
            ScopedVectorStore,
            SearchFilter,
            SearchResult,
            TenantScopedVectorStore,
            VectorDocument,
            VectorStoreProtocol,
            VectorStoreRegistry,
            parse_scope_namespace,
            scope_namespace,
        )

        assert BaseVectorStore is not None
        assert InMemoryVectorStore is not None
        assert PgVectorVectorStore is not None
        assert VectorStoreProtocol is not None
        assert VectorStoreRegistry is not None
        assert VectorDocument is not None
        assert SearchResult is not None
        assert SearchFilter is not None
        assert ScopedVectorStore is not None
        assert TenantScopedVectorStore is not None
        assert scope_namespace is not None
        assert parse_scope_namespace is not None

    def test_public_api_exports_new_vectorstore_surface(self):
        import fireflyframework_agentic.vectorstores as vs

        for name in (
            "PgVectorVectorStore",
            "ScopedVectorStore",
            "TenantScopedVectorStore",
            "scope_namespace",
            "parse_scope_namespace",
        ):
            assert name in vs.__all__, f"{name} missing from vectorstores.__all__"
