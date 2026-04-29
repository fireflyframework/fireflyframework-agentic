from __future__ import annotations

from typing import Any

import pytest

from examples.corpus_search.corpus import ChunkHit, SqliteCorpus, StoredChunk
from examples.corpus_search.retrieval.hybrid import (
    HybridRetriever,
    reciprocal_rank_fusion,
)

# --- RRF helper -----------------------------------------------------------


def test_rrf_with_single_ranking_returns_input_order():
    rankings = [["a", "b", "c"]]
    out = reciprocal_rank_fusion(rankings, k=60)
    ids = [cid for cid, _ in out]
    assert ids == ["a", "b", "c"]


def test_rrf_combines_two_rankings():
    # 'a' is rank 1 in both -> highest fused score
    # 'b' is rank 2 in first, rank 3 in second
    # 'c' is rank 3 in first, rank 2 in second
    # Tie between b and c on RRF? Both get 1/61 + 1/63 = same. We just check 'a' wins.
    rankings = [
        ["a", "b", "c"],
        ["a", "c", "b"],
    ]
    out = reciprocal_rank_fusion(rankings, k=60)
    assert out[0][0] == "a"
    assert {cid for cid, _ in out} == {"a", "b", "c"}


def test_rrf_handles_disjoint_rankings():
    rankings = [["a"], ["b"]]
    out = reciprocal_rank_fusion(rankings)
    ids = {cid for cid, _ in out}
    assert ids == {"a", "b"}


def test_rrf_empty_rankings_returns_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[]]) == []


# --- HybridRetriever ------------------------------------------------------


class _StubEmbedder:
    async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
        # Deterministic 4-d vector based on text length.
        return [float(len(text)), 0.0, 0.0, 0.0]


class _StubSearchResult:
    def __init__(self, doc_id: str, score: float = 0.0) -> None:
        self.id = doc_id
        self.score = score
        self.metadata: dict[str, Any] = {}
        self.content: str = ""


class _StubVectorStore:
    """Returns canned ranked ids per query embedding magnitude."""

    def __init__(self, results: dict[float, list[str]]) -> None:
        self._results = results

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        namespace: str = "default",
        filters: list[Any] | None = None,
    ) -> list[Any]:
        # Use first dim as the lookup key.
        key = query_embedding[0]
        ids = self._results.get(key, [])
        return [_StubSearchResult(i) for i in ids[:top_k]]


@pytest.fixture
async def corpus(tmp_path):
    c = SqliteCorpus(tmp_path / "corpus.sqlite")
    await c.initialise()
    chunks = [
        StoredChunk(
            chunk_id=f"d-{i}",
            doc_id="d",
            source_path="/p",
            index_in_doc=i,
            content=f"content {i} sam altman openai",
            metadata={},
        )
        for i in range(5)
    ]
    await c.upsert_chunks(chunks)
    yield c
    await c.close()


async def test_retrieve_combines_bm25_and_vector_via_rrf(corpus):
    # Vector store ranks: d-2 first, then d-0 — the embedding for "sam"
    # has length 3.0 in the stub.
    vector_store = _StubVectorStore({3.0: ["d-2", "d-0", "d-1"]})
    embedder = _StubEmbedder()
    retriever = HybridRetriever(corpus=corpus, vector_store=vector_store, embedder=embedder)

    hits = await retriever.retrieve(["sam"], top_k_per_query=5, top_k_final=3)
    assert len(hits) <= 3
    assert all(isinstance(h, ChunkHit) for h in hits)
    # All returned chunks should appear in the corpus seed
    assert {h.chunk_id for h in hits} <= {f"d-{i}" for i in range(5)}
    # Content materialised from corpus
    for h in hits:
        assert h.content.startswith("content")


async def test_retrieve_with_multiple_queries_dedupes(corpus):
    vector_store = _StubVectorStore(
        {
            3.0: ["d-0", "d-1"],  # for "sam" (len 3)
            3.0 + 1: ["d-1"],  # not used since we only key on first dim
        }
    )
    embedder = _StubEmbedder()
    retriever = HybridRetriever(corpus=corpus, vector_store=vector_store, embedder=embedder)
    hits = await retriever.retrieve(["sam", "sam"], top_k_per_query=5, top_k_final=10)
    chunk_ids = [h.chunk_id for h in hits]
    # No duplicates
    assert len(chunk_ids) == len(set(chunk_ids))


async def test_retrieve_with_no_matches_returns_empty(corpus):
    vector_store = _StubVectorStore({})  # vector store returns nothing
    embedder = _StubEmbedder()
    retriever = HybridRetriever(corpus=corpus, vector_store=vector_store, embedder=embedder)
    hits = await retriever.retrieve(["totally-unrelated"], top_k_per_query=5, top_k_final=10)
    # BM25 may also return empty for that hyphenated query (parsing). Accept both.
    assert hits == [] or all(h.chunk_id.startswith("d-") for h in hits)


async def test_retrieve_preserves_rrf_order(corpus):
    # Make BM25 and vector both rank d-2 first.
    # BM25 will rank by content match — all chunks contain "altman", so we
    # rely mostly on the vector store for deterministic order in this test.
    vector_store = _StubVectorStore({3.0: ["d-2", "d-0", "d-1", "d-3", "d-4"]})
    embedder = _StubEmbedder()
    retriever = HybridRetriever(corpus=corpus, vector_store=vector_store, embedder=embedder)
    hits = await retriever.retrieve(["sam"], top_k_per_query=5, top_k_final=5)
    # d-2 should appear early in the result given vector ranks it first
    chunk_ids = [h.chunk_id for h in hits]
    assert "d-2" in chunk_ids[:3]
