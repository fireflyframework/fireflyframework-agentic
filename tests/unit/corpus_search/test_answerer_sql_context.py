from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.retrieval.answerer import Answer, AnswerAgent
from fireflyframework_agentic.rag.corpus import ChunkHit


@pytest.mark.asyncio
async def test_answer_without_sql_context_unchanged():
    """sql_context=None must not change existing behaviour."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    mock_result = MagicMock()
    mock_result.output = Answer(text="42", citations=[], cited_sources=[])
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        hits = [ChunkHit(chunk_id="c1", content="some context", score=0.9, metadata={})]
        result = await agent.answer("What is the answer?", hits)
    assert result.text == "42"


@pytest.mark.asyncio
async def test_answer_with_sql_context_includes_structured_section():
    """When sql_context is provided, the prompt must contain '## Structured Data Results'."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    captured_prompts: list[str] = []
    mock_result = MagicMock()
    mock_result.output.answer = "2 products"
    mock_result.output.cited_sources = []

    async def capture_run(prompt: str) -> MagicMock:
        captured_prompts.append(prompt)
        return mock_result

    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(side_effect=capture_run)
        await agent.answer(
            "How many products?",
            [],
            sql_context="id | name\n--- | ---\n1 | Widget",
        )
    assert len(captured_prompts) == 1
    assert "## Structured Data Results" in captured_prompts[0]
    assert "Widget" in captured_prompts[0]


@pytest.mark.asyncio
async def test_answer_short_circuit_only_when_both_empty():
    """Short circuit fires only when hits is empty AND sql_context is None."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    mock_result = MagicMock()
    mock_result.output.answer = "structured answer"
    mock_result.output.cited_sources = []
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        # should NOT short-circuit — sql_context is present
        await agent.answer(
            "question",
            [],  # no hits
            sql_context="col\n---\nval",
        )
    mock_agent.run.assert_called_once()
