"""Tests for vector store protocol and base class."""

from __future__ import annotations

import pytest

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import VectorStoreError
from fireflyframework_genai.vectorstores.base import BaseVectorStore, VectorStoreProtocol
from fireflyframework_genai.vectorstores.types import SearchResult, VectorDocument


class _FakeEmbedder(BaseEmbedder):
    def __init__(self):
        super().__init__(model="fake", dimensions=3)

    async def _embed_batch(self, texts, **kwargs):
        return [[float(len(t)), 0.0, 1.0] for t in texts]


class _FakeVectorStore(BaseVectorStore):
    def __init__(self, embedder=None):
        super().__init__(embedder=embedder)
        self.docs: dict[str, dict[str, VectorDocument]] = {}

    async def _upsert(self, documents, namespace):
        if namespace not in self.docs:
            self.docs[namespace] = {}
        for doc in documents:
            self.docs[namespace][doc.id] = doc

    async def _search(self, query_embedding, top_k, namespace, filters):
        ns_docs = self.docs.get(namespace, {})
        results = []
        for doc in list(ns_docs.values())[:top_k]:
            results.append(SearchResult(document=doc, score=0.9))
        return results

    async def _delete(self, ids, namespace):
        ns_docs = self.docs.get(namespace, {})
        for id_ in ids:
            ns_docs.pop(id_, None)


class TestVectorStoreProtocol:
    def test_satisfies_protocol(self):
        store = _FakeVectorStore()
        assert isinstance(store, VectorStoreProtocol)


class TestBaseVectorStore:
    async def test_upsert_and_search(self):
        store = _FakeVectorStore()
        docs = [
            VectorDocument(id="1", text="hello", embedding=[1.0, 0.0, 0.0]),
            VectorDocument(id="2", text="world", embedding=[0.0, 1.0, 0.0]),
        ]
        await store.upsert(docs)
        results = await store.search([1.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2

    async def test_auto_embed_on_upsert(self):
        embedder = _FakeEmbedder()
        store = _FakeVectorStore(embedder=embedder)
        docs = [VectorDocument(id="1", text="hello")]  # No embedding
        await store.upsert(docs)
        stored = store.docs["default"]["1"]
        assert stored.embedding is not None
        assert len(stored.embedding) == 3

    async def test_search_text(self):
        embedder = _FakeEmbedder()
        store = _FakeVectorStore(embedder=embedder)
        docs = [VectorDocument(id="1", text="hello", embedding=[1.0, 0.0, 0.0])]
        await store.upsert(docs)
        results = await store.search_text("test query", top_k=1)
        assert len(results) == 1

    async def test_search_text_without_embedder_raises(self):
        store = _FakeVectorStore()
        with pytest.raises(VectorStoreError, match="embedder"):
            await store.search_text("query")

    async def test_delete(self):
        store = _FakeVectorStore()
        docs = [VectorDocument(id="1", text="hello", embedding=[1.0, 0.0, 0.0])]
        await store.upsert(docs)
        await store.delete(["1"])
        assert "1" not in store.docs.get("default", {})

    async def test_namespace_isolation(self):
        store = _FakeVectorStore()
        doc_a = VectorDocument(id="1", text="a", embedding=[1.0, 0.0, 0.0])
        doc_b = VectorDocument(id="1", text="b", embedding=[0.0, 1.0, 0.0])
        await store.upsert([doc_a], namespace="ns_a")
        await store.upsert([doc_b], namespace="ns_b")
        results_a = await store.search([1.0, 0.0, 0.0], namespace="ns_a")
        results_b = await store.search([1.0, 0.0, 0.0], namespace="ns_b")
        assert results_a[0].document.text == "a"
        assert results_b[0].document.text == "b"
