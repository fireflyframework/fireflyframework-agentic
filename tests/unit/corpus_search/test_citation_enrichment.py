# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Regression test for ReasoningAnswerAgent cited_sources enrichment.

When the LLM calls knowledge_search several times in a single answer() run,
``Answer.cited_sources`` must be enrichable from the *union* of every hit
returned across calls, not just the last one. Hallucinated chunk_ids (ones
the LLM cites but never appeared in any tool return) must be dropped.

We exercise this at the unit level by driving the tool closure directly
rather than going through pydantic-ai's tool loop: that keeps the test
focused on the union+hallucination contract and independent of model
behaviour. End-to-end coverage lives in the Tier A replay tests.
"""

from unittest.mock import AsyncMock

import pytest

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.answerer import _build_cited_sources
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _CURRENT_CTX,
    _build_knowledge_search,
    _LoopContext,
)


@pytest.mark.asyncio
async def test_cited_sources_unions_across_multiple_knowledge_search_calls(tmp_path):
    hits_round_1 = [
        ChunkHit(chunk_id="c1", score=1.0, content="A", metadata={}, source_path="/a"),
    ]
    hits_round_2 = [
        ChunkHit(chunk_id="c2", score=1.0, content="B", metadata={}, source_path="/b"),
    ]
    corpus = AsyncMock()
    corpus.retrieve.side_effect = [hits_round_1, hits_round_2]
    ctx = _LoopContext(
        corpus_agent=corpus,
        structured_retriever=None,
        schemas=[],
        db_path=tmp_path / "corpus.sqlite",
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        knowledge_search = _build_knowledge_search()
        await knowledge_search(query="first", top_k=1)
        await knowledge_search(query="second", top_k=1)
    finally:
        _CURRENT_CTX.reset(tok)

    # Both rounds' hits accumulated.
    assert set(ctx.accumulated_hits) == {"c1", "c2"}

    # Citing both produces both, regardless of order.
    cited = _build_cited_sources(["c2", "c1"], list(ctx.accumulated_hits.values()))
    assert [c.chunk_id for c in cited] == ["c2", "c1"]
    assert {c.source_path for c in cited} == {"/a", "/b"}


@pytest.mark.asyncio
async def test_cited_sources_drops_hallucinated_chunk_ids(tmp_path):
    hit = ChunkHit(chunk_id="c1", score=1.0, content="A", metadata={}, source_path="/a")
    corpus = AsyncMock()
    corpus.retrieve.return_value = [hit]
    ctx = _LoopContext(
        corpus_agent=corpus,
        structured_retriever=None,
        schemas=[],
        db_path=tmp_path / "corpus.sqlite",
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        knowledge_search = _build_knowledge_search()
        await knowledge_search(query="x", top_k=1)
    finally:
        _CURRENT_CTX.reset(tok)

    # The LLM cited a chunk that was never returned by any knowledge_search.
    # _build_cited_sources must drop it silently.
    cited = _build_cited_sources(
        ["c1", "halluc-99"],
        list(ctx.accumulated_hits.values()),
    )
    assert [c.chunk_id for c in cited] == ["c1"]


@pytest.mark.asyncio
async def test_cited_sources_dedups_repeated_citations(tmp_path):
    """If the LLM cites the same chunk_id twice, only one CitedSource is emitted."""
    hit = ChunkHit(chunk_id="c1", score=1.0, content="A" * 250, metadata={}, source_path="/a")
    corpus = AsyncMock()
    corpus.retrieve.return_value = [hit]
    ctx = _LoopContext(
        corpus_agent=corpus,
        structured_retriever=None,
        schemas=[],
        db_path=tmp_path / "corpus.sqlite",
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        knowledge_search = _build_knowledge_search()
        await knowledge_search(query="x", top_k=1)
    finally:
        _CURRENT_CTX.reset(tok)

    cited = _build_cited_sources(
        ["c1", "c1", "c1"],
        list(ctx.accumulated_hits.values()),
    )
    assert len(cited) == 1
    assert cited[0].chunk_id == "c1"
    # Snippet capped to the default 200 chars.
    assert len(cited[0].snippet) <= 200
