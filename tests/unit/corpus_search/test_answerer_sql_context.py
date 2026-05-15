from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.answerer import Answer, AnswerAgent
from fireflyframework_agentic.rag.retrieval.sql import ProbeRecord, SqlRetrievalOutcome


@pytest.mark.asyncio
async def test_answer_without_sql_outcome_unchanged():
    """sql_outcome=None must not change existing behaviour."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    mock_result = MagicMock()
    mock_result.output = Answer(text="42", citations=[], cited_sources=[])
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        hits = [ChunkHit(chunk_id="c1", content="some context", score=0.9, metadata={})]
        result = await agent.answer("What is the answer?", hits)
    assert result.text == "42"


@pytest.mark.asyncio
async def test_answer_with_answered_outcome_includes_structured_section():
    """outcome='answered' must produce the existing structured-data prompt section."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    captured_prompts: list[str] = []
    mock_result = MagicMock()
    mock_result.output = Answer(text="2 products", citations=[], cited_sources=[])

    async def capture_run(prompt: str) -> MagicMock:
        captured_prompts.append(prompt)
        return mock_result

    outcome = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="id | name\n--- | ---\n1 | Widget",
        attempted_sql="SELECT id, name FROM products",
        probe_trail=[],
    )
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(side_effect=capture_run)
        await agent.answer("How many products?", [], sql_outcome=outcome)
    assert "## Structured Data Results" in captured_prompts[0]
    assert "Widget" in captured_prompts[0]


@pytest.mark.asyncio
async def test_answer_with_empty_outcome_includes_probe_trail_and_does_not_short_circuit():
    """outcome='empty' must NOT short-circuit, and the probe trail must be in the prompt."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    captured_prompts: list[str] = []
    mock_result = MagicMock()
    mock_result.output = Answer(text="closest region is EU-North", citations=[], cited_sources=[])

    async def capture_run(prompt: str) -> MagicMock:
        captured_prompts.append(prompt)
        return mock_result

    outcome = SqlRetrievalOutcome(
        outcome="empty",
        result_markdown=None,
        attempted_sql="SELECT * FROM sales WHERE region='Antarctica'",
        probe_trail=[
            ProbeRecord(
                table="sales",
                column="region",
                op="distinct_values",
                result="EU-North | EU-South | NA | APAC",
            ),
        ],
    )
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(side_effect=capture_run)
        result = await agent.answer("Antarctica sales?", [], sql_outcome=outcome)

    # The agent was actually called — no short-circuit.
    assert mock_agent.run.await_count == 1
    p = captured_prompts[0]
    assert "## SQL attempt (no matching rows)" in p
    assert "SELECT * FROM sales WHERE region='Antarctica'" in p
    assert "EU-North" in p
    assert result.text == "closest region is EU-North"


@pytest.mark.asyncio
async def test_answer_with_unsupported_outcome_and_no_hits_short_circuits():
    """outcome='unsupported' + empty hits should still short-circuit to _NO_INFO_TEXT."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    outcome = SqlRetrievalOutcome(
        outcome="unsupported",
        result_markdown=None,
        attempted_sql=None,
        probe_trail=[],
    )
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock()
        result = await agent.answer("Off-topic question?", [], sql_outcome=outcome)
    mock_agent.run.assert_not_called()
    assert result.text == "I don't have enough information."


def test_answer_reasoning_trace_defaults_to_none_and_serialises_clean():
    a = Answer(text="hi")
    assert a.reasoning_trace is None
    dumped = a.model_dump(exclude_none=True)
    assert "reasoning_trace" not in dumped


def test_answer_reasoning_trace_round_trip():
    from fireflyframework_agentic.reasoning.trace import ActionStep, ReasoningTrace

    trace = ReasoningTrace(pattern_name="reasoning_answerer")
    trace.add_step(ActionStep(tool_name="knowledge_search", tool_args={"q": "x"}))
    a = Answer(text="hi", reasoning_trace=trace)
    dumped = a.model_dump(mode="json")
    assert dumped["reasoning_trace"]["pattern_name"] == "reasoning_answerer"
    assert dumped["reasoning_trace"]["steps"][0]["tool_name"] == "knowledge_search"
