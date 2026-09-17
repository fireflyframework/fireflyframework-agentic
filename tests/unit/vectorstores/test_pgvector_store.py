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

    async def test_create_schema_false_verifies_instead_of_creating(self) -> None:
        """An application pod never runs DDL: with ``create_schema=False`` the store checks the
        extension and the table exist and raises, naming what is missing, instead of creating."""
        from fireflyframework_agentic.exceptions import VectorStoreError
        from fireflyframework_agentic.vectorstores.pgvector_store import PgVectorVectorStore

        class FakeConn:
            def __init__(self, extension: bool, table: bool) -> None:
                self.answers = {"pg_extension": extension, "to_regclass": table}
                self.statements: list[str] = []

            async def execute(self, sql: str, *args: object) -> None:
                self.statements.append(sql)

            async def fetchval(self, sql: str, *args: object) -> object:
                self.statements.append(sql)
                if "pg_extension" in sql:
                    return self.answers["pg_extension"]
                return "public.vector_documents" if self.answers["to_regclass"] else None

        store = PgVectorVectorStore(url="postgresql://localhost/db", dimension=8, create_schema=False)
        assert store.create_schema is False

        ok = FakeConn(extension=True, table=True)
        await store._create_schema(ok)
        assert not any(s.lstrip().upper().startswith("CREATE") for s in ok.statements)

        no_table = FakeConn(extension=True, table=False)
        with pytest.raises(VectorStoreError, match="vector_documents"):
            await store._create_schema(no_table)
        assert not any(s.lstrip().upper().startswith("CREATE") for s in no_table.statements)

        no_ext = FakeConn(extension=False, table=True)
        with pytest.raises(VectorStoreError, match="extension"):
            await store._create_schema(no_ext)

    async def test_create_schema_defaults_to_true_and_issues_ddl(self) -> None:
        from fireflyframework_agentic.vectorstores.pgvector_store import PgVectorVectorStore

        class FakeConn:
            def __init__(self) -> None:
                self.statements: list[str] = []

            async def execute(self, sql: str, *args: object) -> None:
                self.statements.append(sql)

        store = PgVectorVectorStore(url="postgresql://localhost/db", dimension=8)
        assert store.create_schema is True
        conn = FakeConn()
        await store._create_schema(conn)
        assert any("CREATE EXTENSION" in s for s in conn.statements)
        assert any("CREATE TABLE" in s for s in conn.statements)
