from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent


def _make_agent(tmp_path: Path) -> CorpusAgent:
    return CorpusAgent(
        root=tmp_path / "corpus",
        embed_model="openai:text-embedding-3-small",
        embed_dimension=4,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-haiku-4-5-20251001",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=MagicMock(),
        _vector_store=MagicMock(),
    )


@pytest.mark.asyncio
async def test_query_calls_structured_retriever_in_parallel(tmp_path: Path):
    """StructuredRetriever.retrieve must be called alongside HybridRetriever.retrieve."""
    agent = _make_agent(tmp_path)
    await agent._ensure_started()

    mock_answer = MagicMock()
    mock_answer.cited_sources = []

    with (
        patch.object(agent._expander, "expand", new_callable=AsyncMock, return_value=["q"]),
        patch.object(agent._retriever, "retrieve", new_callable=AsyncMock, return_value=[]),
        patch.object(agent._reranker, "rerank", new_callable=AsyncMock, return_value=[]),
        patch.object(agent._answerer, "answer", new_callable=AsyncMock, return_value=mock_answer),
        patch.object(agent._structured_retriever, "retrieve", new_callable=AsyncMock, return_value=None) as mock_sql,
        patch.object(agent._schema_registry, "list_schemas", new_callable=AsyncMock, return_value=[]),
    ):
        await agent.query("test question")
    mock_sql.assert_called_once()


@pytest.mark.asyncio
async def test_query_passes_sql_outcome_to_answerer(tmp_path: Path):
    """When SQL retrieval returns data, it must be forwarded to AnswerAgent."""
    from fireflyframework_agentic.rag.retrieval.sql import SqlRetrievalOutcome

    agent = _make_agent(tmp_path)
    await agent._ensure_started()

    mock_answer = MagicMock()
    mock_answer.cited_sources = ["src1"]
    stub_outcome = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="id | name\n--- | ---\n1 | Widget",
        attempted_sql="SELECT id, name FROM products",
        probe_trail=[],
    )

    with (
        patch.object(agent._expander, "expand", new_callable=AsyncMock, return_value=["q"]),
        patch.object(agent._retriever, "retrieve", new_callable=AsyncMock, return_value=[]),
        patch.object(agent._reranker, "rerank", new_callable=AsyncMock, return_value=[]),
        patch.object(agent._answerer, "answer", new_callable=AsyncMock, return_value=mock_answer) as mock_answer_fn,
        patch.object(agent._structured_retriever, "retrieve", new_callable=AsyncMock, return_value=stub_outcome),
        patch.object(agent._schema_registry, "list_schemas", new_callable=AsyncMock, return_value=[]),
    ):
        await agent.query("How many products?")

    _, kwargs = mock_answer_fn.call_args
    assert kwargs.get("sql_outcome") is stub_outcome
