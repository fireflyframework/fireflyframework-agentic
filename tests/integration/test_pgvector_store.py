"""Integration tests for the pgvector vector store against a real Postgres.

Uses Testcontainers with the ``pgvector/pgvector`` image, so these exercise the
real schema bootstrap, HNSW index, ANN ordering, namespace isolation, metadata
filtering, and the ``_prepare_session`` extension hook -- no mocks.

Marked ``integration``; deselect with ``-m "not integration"`` when Docker is
unavailable.
"""

from __future__ import annotations

import uuid

import pytest

from fireflyframework_agentic.vectorstores.pgvector_store import PgVectorVectorStore
from fireflyframework_agentic.vectorstores.types import SearchFilter, VectorDocument

pytestmark = pytest.mark.integration

_DIM = 4


def _asyncpg_url(raw: str) -> str:
    """Strip any SQLAlchemy driver suffix so asyncpg accepts the URL."""
    return raw.replace("+psycopg2", "").replace("+psycopg", "")


@pytest.fixture(scope="module")
def pg_url() -> str:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield _asyncpg_url(pg.get_connection_url())


@pytest.fixture
async def store(pg_url: str):
    """A freshly-initialised store on a unique table per test."""
    table = f"vec_{uuid.uuid4().hex[:8]}"
    s = PgVectorVectorStore(url=pg_url, dimension=_DIM, table_name=table)
    await s.initialise()
    try:
        yield s
    finally:
        await s.close()


def _doc(id_: str, vec: list[float], **metadata: object) -> VectorDocument:
    return VectorDocument(id=id_, text=f"doc-{id_}", embedding=vec, metadata=metadata)


class TestPgVectorIntegration:
    async def test_initialise_is_idempotent(self, store: PgVectorVectorStore) -> None:
        # Already initialised by the fixture; a second call must not raise.
        await store.initialise()

    async def test_upsert_then_search_returns_doc(self, store: PgVectorVectorStore) -> None:
        await store.upsert([_doc("1", [1.0, 0.0, 0.0, 0.0])], namespace="ns")
        results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5, namespace="ns")
        assert [r.document.id for r in results] == ["1"]
        assert results[0].document.text == "doc-1"
        assert results[0].score == pytest.approx(1.0, abs=1e-3)

    async def test_search_orders_by_cosine_similarity(self, store: PgVectorVectorStore) -> None:
        await store.upsert(
            [_doc("near", [1.0, 0.0, 0.0, 0.0]), _doc("far", [0.0, 1.0, 0.0, 0.0])],
            namespace="ns",
        )
        results = await store.search([1.0, 0.1, 0.0, 0.0], top_k=2, namespace="ns")
        assert [r.document.id for r in results] == ["near", "far"]

    async def test_namespace_isolation(self, store: PgVectorVectorStore) -> None:
        await store.upsert([_doc("a", [1.0, 0.0, 0.0, 0.0])], namespace="ns_a")
        await store.upsert([_doc("b", [1.0, 0.0, 0.0, 0.0])], namespace="ns_b")
        results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5, namespace="ns_a")
        assert [r.document.id for r in results] == ["a"]
        # A namespace that was never written returns nothing.
        empty = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5, namespace="ns_none")
        assert empty == []

    async def test_upsert_overwrites_by_id(self, store: PgVectorVectorStore) -> None:
        await store.upsert([_doc("1", [1.0, 0.0, 0.0, 0.0], v="old")], namespace="ns")
        await store.upsert([_doc("1", [1.0, 0.0, 0.0, 0.0], v="new")], namespace="ns")
        results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5, namespace="ns")
        assert len(results) == 1
        assert results[0].document.metadata["v"] == "new"

    async def test_delete_removes(self, store: PgVectorVectorStore) -> None:
        await store.upsert([_doc("1", [1.0, 0.0, 0.0, 0.0])], namespace="ns")
        await store.delete(["1"], namespace="ns")
        results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5, namespace="ns")
        assert results == []

    async def test_metadata_filter_eq(self, store: PgVectorVectorStore) -> None:
        await store.upsert(
            [
                _doc("1", [1.0, 0.0, 0.0, 0.0], source_id="s1"),
                _doc("2", [1.0, 0.0, 0.0, 0.0], source_id="s2"),
            ],
            namespace="ns",
        )
        results = await store.search(
            [1.0, 0.0, 0.0, 0.0],
            top_k=5,
            namespace="ns",
            filters=[SearchFilter(field="source_id", operator="eq", value="s1")],
        )
        assert [r.document.id for r in results] == ["1"]

    async def test_prepare_session_hook_is_invoked(self, pg_url: str) -> None:
        """A subclass can observe/augment the per-operation session (RLS seam)."""
        seen: list[str] = []
        table = f"vec_{uuid.uuid4().hex[:8]}"

        class _HookedStore(PgVectorVectorStore):
            async def _prepare_session(self, conn, *, namespace: str) -> None:
                seen.append(namespace)

        s = _HookedStore(url=pg_url, dimension=_DIM, table_name=table)
        await s.initialise()
        try:
            await s.upsert([_doc("1", [1.0, 0.0, 0.0, 0.0])], namespace="ns_hook")
            await s.search([1.0, 0.0, 0.0, 0.0], namespace="ns_hook")
            assert "ns_hook" in seen
        finally:
            await s.close()
