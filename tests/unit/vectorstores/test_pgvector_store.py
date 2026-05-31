"""Unit tests for the pgvector vector store (no database required)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestPgVectorVectorStoreUnit:
    def test_import_error_when_asyncpg_missing(self) -> None:
        with patch("fireflyframework_agentic.vectorstores.pgvector_store.asyncpg", None):
            from fireflyframework_agentic.vectorstores.pgvector_store import PgVectorVectorStore

            with pytest.raises(ImportError, match="vectorstores-pgvector"):
                PgVectorVectorStore(url="postgresql://localhost/db", dimension=8)

    def test_constructor_params(self) -> None:
        from fireflyframework_agentic.vectorstores.pgvector_store import PgVectorVectorStore

        store = PgVectorVectorStore(
            url="postgresql://localhost/db",
            dimension=1536,
            table_name="my_vectors",
            hnsw_m=32,
            hnsw_ef_construction=128,
            hnsw_ef_search=300,
        )
        assert store._dimension == 1536
        assert store._table == "my_vectors"
        assert store._hnsw_m == 32
        assert store._hnsw_ef_construction == 128
        assert store._hnsw_ef_search == 300

    def test_invalid_table_name_rejected(self) -> None:
        from fireflyframework_agentic.vectorstores.pgvector_store import PgVectorVectorStore

        with pytest.raises(ValueError, match="table_name"):
            PgVectorVectorStore(url="postgresql://localhost/db", dimension=8, table_name="bad name; DROP")

    async def test_prepare_session_default_is_noop(self) -> None:
        from fireflyframework_agentic.vectorstores.pgvector_store import PgVectorVectorStore

        store = PgVectorVectorStore(url="postgresql://localhost/db", dimension=8)
        # Default hook is a no-op and must not require a real connection.
        assert await store._prepare_session(object(), namespace="anything") is None
