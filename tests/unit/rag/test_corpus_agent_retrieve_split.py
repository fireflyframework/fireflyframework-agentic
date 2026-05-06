# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests asserting `retrieve` and `query` are independent surfaces."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent
from fireflyframework_agentic.rag.corpus import ChunkHit


def _agent(tmp_path: Path) -> CorpusAgent:
    return CorpusAgent(
        root=tmp_path,
        embed_model="openai:text-embedding-3-small",
        embed_dimension=8,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=object(),
        _vector_store=object(),
    )


@pytest.mark.asyncio
async def test_retrieve_does_not_invoke_answer_agent(tmp_path: Path) -> None:
    a = _agent(tmp_path)
    fake_hits = [ChunkHit(chunk_id="c1", content="x", source_path="/p", score=1.0, metadata={})]

    with (
        patch.object(a, "_ensure_query_ready", new=AsyncMock()),
        patch.object(a, "_expander", create=True) as expander,
        patch.object(a, "_retriever", create=True) as retriever,
        patch.object(a, "_reranker", create=True) as reranker,
        patch.object(a, "_answerer", create=True) as answerer,
    ):
        expander.expand = AsyncMock(return_value=["q"])
        retriever.retrieve = AsyncMock(return_value=fake_hits)
        reranker.rerank = AsyncMock(return_value=fake_hits)
        answerer.answer = AsyncMock()

        hits = await a.retrieve("question", top_k=1)

    assert hits == fake_hits
    answerer.answer.assert_not_called()


@pytest.mark.asyncio
async def test_query_calls_answer_agent(tmp_path: Path) -> None:
    from fireflyframework_agentic.rag.retrieval.answerer import Answer

    a = _agent(tmp_path)
    fake_hits = [ChunkHit(chunk_id="c1", content="x", source_path="/p", score=1.0, metadata={})]
    fake_answer = Answer(text="y", citations=[], cited_sources=[])

    with (
        patch.object(a, "_ensure_query_ready", new=AsyncMock()),
        patch.object(a, "_expander", create=True) as expander,
        patch.object(a, "_retriever", create=True) as retriever,
        patch.object(a, "_reranker", create=True) as reranker,
        patch.object(a, "_answerer", create=True) as answerer,
        patch.object(a, "_structured_retriever", create=True) as sql_retriever,
        patch.object(a, "_schema_registry", create=True) as schema_registry,
    ):
        expander.expand = AsyncMock(return_value=["q"])
        retriever.retrieve = AsyncMock(return_value=fake_hits)
        reranker.rerank = AsyncMock(return_value=fake_hits)
        answerer.answer = AsyncMock(return_value=fake_answer)
        sql_retriever.retrieve = AsyncMock(return_value=None)
        schema_registry.list_schemas = AsyncMock(return_value=[])

        result = await a.query("question", top_k=1)

    assert result is fake_answer
    answerer.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_skips_reranker_when_disabled(tmp_path: Path) -> None:
    a = _agent(tmp_path)
    fake_hits = [ChunkHit(chunk_id="c1", content="x", source_path="/p", score=1.0, metadata={})]

    with (
        patch.object(a, "_ensure_query_ready", new=AsyncMock()),
        patch.object(a, "_expander", create=True) as expander,
        patch.object(a, "_retriever", create=True) as retriever,
        patch.object(a, "_reranker", create=True) as reranker,
    ):
        expander.expand = AsyncMock(return_value=["q"])
        retriever.retrieve = AsyncMock(return_value=fake_hits)
        reranker.rerank = AsyncMock()

        await a.retrieve("question", top_k=1, rerank=False)

    reranker.rerank.assert_not_called()
