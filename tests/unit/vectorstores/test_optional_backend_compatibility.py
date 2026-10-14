"""Exercise optional backends locally with their real SDK validators."""

from __future__ import annotations

from uuid import uuid4

import pytest

from fireflyframework_agentic.vectorstores.types import SearchFilter, VectorDocument


@pytest.fixture
def chroma_store(tmp_path):
    chromadb = pytest.importorskip("chromadb")
    from chromadb.config import Settings

    from fireflyframework_agentic.vectorstores.chroma_store import ChromaVectorStore

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"), settings=Settings(anonymized_telemetry=False))
    store = ChromaVectorStore(collection_name="compatibility", client=client)
    yield store
    client.delete_collection("compatibility")


async def test_chroma_combines_namespace_and_metadata_with_native_query(chroma_store):
    await chroma_store.upsert(
        [
            VectorDocument(id="wanted", text="match", embedding=[1.0, 0.0], metadata={"kind": "note"}),
            VectorDocument(id="other-kind", text="skip", embedding=[1.0, 0.0], metadata={"kind": "article"}),
        ],
        namespace="alpha",
    )
    await chroma_store.upsert(
        [VectorDocument(id="other-scope", text="private", embedding=[1.0, 0.0], metadata={"kind": "note"})],
        namespace="beta",
    )
    results = await chroma_store.search(
        [1.0, 0.0], namespace="alpha", filters=[SearchFilter(field="kind", operator="eq", value="note")]
    )
    assert [result.document.id for result in results] == ["wanted"]
    assert results[0].document.text == "match"
    assert results[0].document.metadata == {"kind": "note"}
    assert results[0].score == pytest.approx(1.0)
    await chroma_store.delete(["wanted", "other-scope"], namespace="alpha")
    assert [r.document.id for r in await chroma_store.search([1.0, 0.0], namespace="beta")] == ["other-scope"]


async def test_chroma_namespace_filter_cannot_override_requested_scope(chroma_store):
    await chroma_store.upsert([VectorDocument(id="private", text="private", embedding=[1.0, 0.0])], namespace="beta")
    results = await chroma_store.search(
        [1.0, 0.0], namespace="alpha", filters=[SearchFilter(field="_namespace", operator="eq", value="beta")]
    )
    assert results == []


async def test_qdrant_local_round_trip_uses_native_points_and_scoped_delete(monkeypatch):
    qdrant = pytest.importorskip("qdrant_client")
    from fireflyframework_agentic.vectorstores import qdrant_store

    client = qdrant.AsyncQdrantClient(location=":memory:")
    monkeypatch.setattr(qdrant_store, "AsyncQdrantClient", lambda **kwargs: client)
    store = qdrant_store.QdrantVectorStore(collection_name="compatibility", vector_size=2)
    alpha_id, beta_id = str(uuid4()), str(uuid4())
    try:
        await store.initialise()
        await store.upsert(
            [VectorDocument(id=alpha_id, text="match", embedding=[1.0, 0.0], metadata={"kind": "note"})],
            namespace="alpha",
        )
        await store.upsert([VectorDocument(id=beta_id, text="private", embedding=[1.0, 0.0])], namespace="beta")
        results = await store.search(
            [1.0, 0.0], namespace="alpha", filters=[SearchFilter(field="kind", operator="eq", value="note")]
        )
        assert [r.document.id for r in results] == [alpha_id]
        assert results[0].document.text == "match"
        assert results[0].document.metadata == {"kind": "note"}
        assert results[0].score == pytest.approx(1.0)
        await store.delete([alpha_id, beta_id], namespace="alpha")
        assert await store.search([1.0, 0.0], namespace="alpha") == []
        assert [r.document.id for r in await store.search([1.0, 0.0], namespace="beta")] == [beta_id]
    finally:
        await store.close()
