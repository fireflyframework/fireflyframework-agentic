"""Tests for the in-memory vector store."""

from __future__ import annotations

from fireflyframework_genai.vectorstores.memory_store import InMemoryVectorStore
from fireflyframework_genai.vectorstores.types import SearchFilter, VectorDocument


class TestInMemoryVectorStore:
    async def test_upsert_and_search(self):
        store = InMemoryVectorStore()
        docs = [
            VectorDocument(id="1", text="python", embedding=[1.0, 0.0, 0.0]),
            VectorDocument(id="2", text="javascript", embedding=[0.0, 1.0, 0.0]),
            VectorDocument(id="3", text="rust", embedding=[0.0, 0.0, 1.0]),
        ]
        await store.upsert(docs)
        results = await store.search([1.0, 0.1, 0.0], top_k=2)
        assert len(results) == 2
        # "python" should be most similar
        assert results[0].document.id == "1"
        assert results[0].score > results[1].score

    async def test_search_empty_store(self):
        store = InMemoryVectorStore()
        results = await store.search([1.0, 0.0], top_k=5)
        assert results == []

    async def test_delete(self):
        store = InMemoryVectorStore()
        docs = [VectorDocument(id="1", text="hello", embedding=[1.0, 0.0])]
        await store.upsert(docs)
        await store.delete(["1"])
        results = await store.search([1.0, 0.0], top_k=5)
        assert results == []

    async def test_upsert_overwrites(self):
        store = InMemoryVectorStore()
        doc1 = VectorDocument(id="1", text="v1", embedding=[1.0, 0.0])
        doc2 = VectorDocument(id="1", text="v2", embedding=[0.0, 1.0])
        await store.upsert([doc1])
        await store.upsert([doc2])
        results = await store.search([0.0, 1.0], top_k=1)
        assert results[0].document.text == "v2"

    async def test_namespace_isolation(self):
        store = InMemoryVectorStore()
        doc_a = VectorDocument(id="1", text="a", embedding=[1.0, 0.0])
        doc_b = VectorDocument(id="1", text="b", embedding=[1.0, 0.0])
        await store.upsert([doc_a], namespace="ns_a")
        await store.upsert([doc_b], namespace="ns_b")
        results_a = await store.search([1.0, 0.0], namespace="ns_a")
        results_b = await store.search([1.0, 0.0], namespace="ns_b")
        assert results_a[0].document.text == "a"
        assert results_b[0].document.text == "b"

    async def test_metadata_filter_eq(self):
        store = InMemoryVectorStore()
        docs = [
            VectorDocument(id="1", text="a", embedding=[1.0, 0.0], metadata={"type": "blog"}),
            VectorDocument(id="2", text="b", embedding=[0.9, 0.1], metadata={"type": "doc"}),
        ]
        await store.upsert(docs)
        results = await store.search(
            [1.0, 0.0],
            top_k=5,
            filters=[SearchFilter(field="type", operator="eq", value="blog")],
        )
        assert len(results) == 1
        assert results[0].document.id == "1"

    async def test_top_k_limits(self):
        store = InMemoryVectorStore()
        docs = [VectorDocument(id=str(i), text=f"doc{i}", embedding=[float(i), 0.0]) for i in range(10)]
        await store.upsert(docs)
        results = await store.search([5.0, 0.0], top_k=3)
        assert len(results) == 3
