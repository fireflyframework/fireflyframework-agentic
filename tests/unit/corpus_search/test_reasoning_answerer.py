# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from pathlib import Path

from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _CURRENT_CTX,
    _LoopContext,
)


def test_loop_context_defaults():
    ctx = _LoopContext(
        corpus_agent=None,
        structured_retriever=None,
        schemas=[],
        db_path=Path("/tmp/nonexistent.sqlite"),
    )
    assert ctx.accumulated_hits == {}
    assert ctx.sql_calls == []


def test_contextvar_default_is_none():
    assert _CURRENT_CTX.get() is None


from unittest.mock import AsyncMock  # noqa: E402

import pytest  # noqa: E402

from fireflyframework_agentic.rag.corpus import ChunkHit  # noqa: E402
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (  # noqa: E402
    _build_knowledge_search,
)


@pytest.mark.asyncio
async def test_knowledge_search_records_hits_and_returns_dicts():
    hit = ChunkHit(
        chunk_id="c1",
        score=0.9,
        content="hello world",
        metadata={},
        source_path="/x.md",
    )
    corpus = AsyncMock()
    corpus.retrieve.return_value = [hit]
    ctx = _LoopContext(
        corpus_agent=corpus,
        structured_retriever=None,
        schemas=[],
        db_path=Path("/tmp/x.sqlite"),
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        knowledge_search = _build_knowledge_search()
        out = await knowledge_search(query="hello", top_k=3)
    finally:
        _CURRENT_CTX.reset(tok)
    assert isinstance(out, list) and len(out) == 1
    assert out[0]["chunk_id"] == "c1"
    assert out[0]["source_path"] == "/x.md"
    assert "hello" in out[0]["snippet"]
    assert ctx.accumulated_hits == {"c1": hit}
    corpus.retrieve.assert_awaited_once_with("hello", top_k=3, rerank=True)


@pytest.mark.asyncio
async def test_knowledge_search_requires_ctx():
    knowledge_search = _build_knowledge_search()
    with pytest.raises(AssertionError):
        await knowledge_search(query="x")
