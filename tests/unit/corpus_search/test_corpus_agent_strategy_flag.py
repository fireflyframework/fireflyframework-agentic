# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent


def _make(tmp_path: Path, strategy: str = "fast") -> CorpusAgent:
    return CorpusAgent(
        root=tmp_path,
        embed_model="openai:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        answer_strategy=strategy,
        _embedder=MagicMock(),
        _vector_store=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_default_strategy_is_fast(tmp_path):
    agent = _make(tmp_path, strategy="fast")
    await agent._ensure_query_ready()
    from fireflyframework_agentic.rag.retrieval.answerer import AnswerAgent

    assert isinstance(agent._answerer, AnswerAgent)


@pytest.mark.asyncio
async def test_reasoning_strategy_uses_reasoning_answerer(tmp_path):
    agent = _make(tmp_path, strategy="reasoning")
    await agent._ensure_query_ready()
    from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
        ReasoningAnswerAgent,
    )

    assert isinstance(agent._answerer, ReasoningAnswerAgent)
