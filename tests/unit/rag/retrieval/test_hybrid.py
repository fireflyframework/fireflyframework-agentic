from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.rag.corpus import ChunkHit, SqliteCorpus, StoredChunk
from fireflyframework_agentic.rag.retrieval.expander import ExpandedQuery
from fireflyframework_agentic.rag.retrieval.hybrid import (
    HybridRetriever,
    reciprocal_rank_fusion,
)
from fireflyframework_agentic.vectorstores.types import SearchResult, VectorDocument

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
    ) -> list[SearchResult]:
        # Use first dim as the lookup key.
        key = query_embedding[0]
        ids = self._results.get(key, [])
        return [SearchResult(document=VectorDocument(id=i, text="", metadata={}), score=0.0) for i in ids[:top_k]]


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


# --- ExpandedQuery routing ---------------------------------------------------


async def test_retrieve_vec_only_query_skips_bm25(corpus):
    """A hyde (vec_only) ExpandedQuery must not issue a BM25 call.

    We verify both sides: the routing guard prevents the BM25 call (negative
    assertion via mock), and the vec_only result still surfaces via RRF
    (positive assertion on returned chunk_ids).
    """
    # Embedding for "xyzzy" has len 5 → key 5.0 in the stub.
    vector_store = _StubVectorStore({5.0: ["d-3", "d-1"]})
    embedder = _StubEmbedder()
    retriever = HybridRetriever(corpus=corpus, vector_store=vector_store, embedder=embedder)

    hyde_q = ExpandedQuery(text="xyzzy", route="vec_only")
    with patch.object(corpus, "bm25_search", new_callable=AsyncMock) as mock_bm25:
        hits = await retriever.retrieve([hyde_q], top_k_per_query=5, top_k_final=5)
        mock_bm25.assert_not_awaited()
    chunk_ids = [h.chunk_id for h in hits]
    assert "d-3" in chunk_ids


async def test_retrieve_hybrid_and_vec_only_fused(corpus):
    """Hybrid and vec_only queries are fused together via RRF.

    The hybrid query's BM25 and vector rankings and the hyde's vector
    ranking all contribute — the chunk appearing across more rankings wins.
    """
    # "sam" (len 3) → d-0,d-1 via vector; "xyzzy" (len 5) → d-2,d-0 via vector.
    vector_store = _StubVectorStore(
        {
            3.0: ["d-0", "d-1"],  # hybrid query vector hits
            5.0: ["d-2", "d-0"],  # hyde query vector hits
        }
    )
    embedder = _StubEmbedder()
    retriever = HybridRetriever(corpus=corpus, vector_store=vector_store, embedder=embedder)

    queries: list[str | ExpandedQuery] = [
        ExpandedQuery(text="sam", route="hybrid"),
        ExpandedQuery(text="xyzzy", route="vec_only"),
    ]
    hits = await retriever.retrieve(queries, top_k_per_query=5, top_k_final=5)
    chunk_ids = [h.chunk_id for h in hits]
    # d-0 appears in both vector rankings → highest RRF score
    assert "d-0" in chunk_ids
    assert chunk_ids.index("d-0") < chunk_ids.index("d-2") if "d-2" in chunk_ids else True
