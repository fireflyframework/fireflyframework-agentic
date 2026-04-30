"""Tests for SqliteVecVectorStore (sqlite-vec backend)."""
from __future__ import annotations

import pytest

from fireflyframework_agentic.vectorstores.types import VectorDocument


@pytest.fixture
def store(tmp_path):
    from fireflyframework_agentic.vectorstores.sqlite_vec_store import SqliteVecVectorStore

    return SqliteVecVectorStore(db_path=tmp_path / "test.sqlite", dimension=4)


async def test_upsert_and_search_returns_closest_first(store):
    docs = [
        VectorDocument(id="a", text="alpha", embedding=[1.0, 0.0, 0.0, 0.0]),
        VectorDocument(id="b", text="beta", embedding=[0.0, 1.0, 0.0, 0.0]),
        VectorDocument(id="c", text="gamma", embedding=[0.0, 0.0, 1.0, 0.0]),
    ]
    await store.upsert(docs)
    results = await store.search([0.99, 0.01, 0.0, 0.0], top_k=3)
    assert len(results) == 3
    assert results[0].document.id == "a"


async def test_search_scores_decrease(store):
    docs = [
        VectorDocument(id="x", text="x", embedding=[1.0, 0.0, 0.0, 0.0]),
        VectorDocument(id="y", text="y", embedding=[0.0, 1.0, 0.0, 0.0]),
    ]
    await store.upsert(docs)
    results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert results[0].score >= results[1].score


async def test_search_empty_store_returns_empty(store):
    results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5)
    assert results == []


async def test_upsert_overwrites_existing_id(store):
    doc = VectorDocument(id="dup", text="v1", embedding=[1.0, 0.0, 0.0, 0.0])
    await store.upsert([doc])
    doc2 = VectorDocument(id="dup", text="v2", embedding=[0.0, 1.0, 0.0, 0.0])
    await store.upsert([doc2])
    results = await store.search([0.0, 1.0, 0.0, 0.0], top_k=5)
    ids = [r.document.id for r in results]
    assert ids.count("dup") == 1
    assert results[0].document.id == "dup"


async def test_delete_removes_document(store):
    docs = [
        VectorDocument(id="keep", text="k", embedding=[1.0, 0.0, 0.0, 0.0]),
        VectorDocument(id="drop", text="d", embedding=[0.9, 0.1, 0.0, 0.0]),
    ]
    await store.upsert(docs)
    await store.delete(["drop"])
    results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5)
    ids = [r.document.id for r in results]
    assert "drop" not in ids
    assert "keep" in ids


async def test_delete_nonexistent_id_is_silent(store):
    await store.delete(["ghost"])


async def test_namespace_isolation(tmp_path):
    from fireflyframework_agentic.vectorstores.sqlite_vec_store import SqliteVecVectorStore

    s = SqliteVecVectorStore(db_path=tmp_path / "ns.sqlite", dimension=4)
    await s.upsert(
        [VectorDocument(id="ns_a_doc", text="", embedding=[1.0, 0.0, 0.0, 0.0])],
        namespace="ns_a",
    )
    await s.upsert(
        [VectorDocument(id="ns_b_doc", text="", embedding=[1.0, 0.0, 0.0, 0.0])],
        namespace="ns_b",
    )
    results_a = await s.search([1.0, 0.0, 0.0, 0.0], top_k=5, namespace="ns_a")
    ids_a = [r.document.id for r in results_a]
    assert "ns_a_doc" in ids_a
    assert "ns_b_doc" not in ids_a

    results_b = await s.search([1.0, 0.0, 0.0, 0.0], top_k=5, namespace="ns_b")
    ids_b = [r.document.id for r in results_b]
    assert "ns_b_doc" in ids_b
    assert "ns_a_doc" not in ids_b


async def test_import_error_when_sqlite_vec_not_installed(tmp_path):
    from unittest.mock import patch

    from fireflyframework_agentic.exceptions import VectorStoreError
    from fireflyframework_agentic.vectorstores import sqlite_vec_store as m

    with patch.object(m, "sqlite_vec", None):
        store = m.SqliteVecVectorStore(db_path=tmp_path / "x.sqlite", dimension=4)
        # ImportError from _initialise_sync is wrapped by BaseVectorStore.upsert
        with pytest.raises(VectorStoreError, match="sqlite-vec"):
            await store.upsert([VectorDocument(id="x", text="", embedding=[1.0, 0.0, 0.0, 0.0])])
