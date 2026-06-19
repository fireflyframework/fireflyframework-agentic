from unittest.mock import MagicMock

import pytest

from fireflyframework_agentic.evaluation.judge import (
    EvalContext,
    addresses_question,
    contains_answer,
    excerpt_fill_rate,
    faithfulness,
    source_coverage,
)
from fireflyframework_agentic.evaluation.judge_client import JudgeClient


def make_ctx(responses: list[dict]) -> EvalContext:
    client = MagicMock(spec=JudgeClient)
    client.model_spec = "anthropic:claude-sonnet-4-6"
    client.provider = "anthropic"
    client.model = "claude-sonnet-4-6"
    call_iter = iter(responses)

    async def mock_chat_json(system, user, max_tokens=1024):
        return next(call_iter)

    client.chat_json = mock_chat_json
    return EvalContext(client=client, runs=1)


# ── contains_answer ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contains_answer_present():
    ctx = make_ctx([{"contains_answer": 1.0, "addresses_question": 1.0}])
    item = {"question": "Q", "reference": "R", "answer": "A"}
    score = await contains_answer(item, ctx)
    assert score == 1.0


@pytest.mark.asyncio
async def test_contains_answer_absent():
    ctx = make_ctx([{"contains_answer": 0.0, "addresses_question": 0.5}])
    item = {"question": "Q", "reference": "R", "answer": "wrong"}
    score = await contains_answer(item, ctx)
    assert score == 0.0


@pytest.mark.asyncio
async def test_contains_answer_partial():
    ctx = make_ctx([{"contains_answer": 0.5, "addresses_question": 0.8}])
    item = {"question": "Q", "reference": "R", "answer": "partial"}
    score = await contains_answer(item, ctx)
    assert score == 0.5


@pytest.mark.asyncio
async def test_contains_answer_missing_question_returns_none():
    ctx = make_ctx([])
    item = {"reference": "R", "answer": "A"}
    score = await contains_answer(item, ctx)
    assert score is None


# ── addresses_question ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_addresses_question_yes():
    ctx = make_ctx([{"contains_answer": 0.5, "addresses_question": 1.0}])
    item = {"question": "Q", "reference": "R", "answer": "A"}
    score = await addresses_question(item, ctx)
    assert score == 1.0


@pytest.mark.asyncio
async def test_addresses_question_no():
    ctx = make_ctx([{"contains_answer": 0.0, "addresses_question": 0.0}])
    item = {"question": "Q", "reference": "R", "answer": "irrelevant"}
    score = await addresses_question(item, ctx)
    assert score == 0.0


@pytest.mark.asyncio
async def test_addresses_question_missing_answer_returns_none():
    ctx = make_ctx([])
    item = {"question": "Q", "reference": "R"}
    score = await addresses_question(item, ctx)
    assert score is None


# ── faithfulness ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_faithfulness_all_supported():
    # One finding with cited evidence, judge says SUPPORTED.
    ctx = make_ctx([{"verdict": "SUPPORTED", "reason": "matches"}])
    item = {
        "findings": [
            {
                "id": "F1",
                "description": "The process takes 3 days.",
                "evidence_refs": [{"evidence_id": "E1"}],
            }
        ],
        "evidence_index": [{"id": "E1", "locator": "doc.pdf#1", "excerpt": "The process takes 3 days as documented."}],
    }
    result = await faithfulness(item, ctx)
    assert result["supported"] == 1
    assert result["total"] == 1
    assert result["unsupported_ids"] == []


@pytest.mark.asyncio
async def test_faithfulness_not_supported():
    ctx = make_ctx([{"verdict": "NOT_SUPPORTED", "reason": "contradicts"}])
    item = {
        "findings": [
            {
                "id": "F1",
                "description": "The process takes 45 days.",
                "evidence_refs": [{"evidence_id": "E1"}],
            }
        ],
        "evidence_index": [{"id": "E1", "locator": "doc.pdf#1", "excerpt": "The process takes 3 days."}],
    }
    result = await faithfulness(item, ctx)
    assert result["supported"] == 0
    assert result["total"] == 1
    assert "F1" in result["unsupported_ids"]


@pytest.mark.asyncio
async def test_faithfulness_no_cited_evidence():
    # Finding with no evidence_refs -> counted as unsupported without LLM call.
    ctx = make_ctx([])
    item = {
        "findings": [{"id": "F1", "description": "Something.", "evidence_refs": []}],
        "evidence_index": [],
    }
    result = await faithfulness(item, ctx)
    assert result["supported"] == 0
    assert result["total"] == 1
    assert "F1" in result["unsupported_ids"]


# ── source_coverage ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_source_coverage_all_cited():
    ctx = make_ctx([])
    item = {
        "findings": [
            {
                "id": "F1",
                "description": "X",
                "evidence_refs": [{"evidence_id": "E1"}],
            }
        ],
        "evidence_index": [{"id": "E1", "locator": "doc.pdf#section1", "excerpt": "text"}],
    }
    result = await source_coverage(item, ctx)
    assert result["cited"] == 1
    assert result["total"] == 1
    assert result["orphaned"] == []


@pytest.mark.asyncio
async def test_source_coverage_orphaned():
    ctx = make_ctx([])
    item = {
        "findings": [{"id": "F1", "description": "X", "evidence_refs": []}],
        "evidence_index": [
            {"id": "E1", "locator": "doc1.pdf#p1", "excerpt": "text"},
            {"id": "E2", "locator": "doc2.pdf#p2", "excerpt": "text2"},
        ],
    }
    result = await source_coverage(item, ctx)
    assert result["cited"] == 0
    assert result["total"] == 2
    assert len(result["orphaned"]) == 2


@pytest.mark.asyncio
async def test_source_coverage_stem_dedup():
    # Two evidence items from the same file (different fragments) -> 1 source stem.
    ctx = make_ctx([])
    item = {
        "findings": [
            {
                "id": "F1",
                "description": "X",
                "evidence_refs": [{"evidence_id": "E1"}],
            }
        ],
        "evidence_index": [
            {"id": "E1", "locator": "doc.pdf#section1", "excerpt": "text1"},
            {"id": "E2", "locator": "doc.pdf#section2", "excerpt": "text2"},
        ],
    }
    result = await source_coverage(item, ctx)
    # Both E1 and E2 share "doc.pdf" stem -> 1 total stem.
    assert result["total"] == 1
    # E1 is cited -> that stem is covered.
    assert result["cited"] == 1


# ── excerpt_fill_rate ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_excerpt_fill_rate_full():
    ctx = make_ctx([])
    item = {
        "evidence_index": [
            {"id": "E1", "excerpt": "has content"},
            {"id": "E2", "excerpt": "also has content"},
        ]
    }
    result = await excerpt_fill_rate(item, ctx)
    assert result["populated"] == 2
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_excerpt_fill_rate_partial():
    ctx = make_ctx([])
    item = {
        "evidence_index": [
            {"id": "E1", "excerpt": "has content"},
            {"id": "E2", "excerpt": ""},
            {"id": "E3", "excerpt": "   "},
        ]
    }
    result = await excerpt_fill_rate(item, ctx)
    assert result["populated"] == 1
    assert result["total"] == 3


@pytest.mark.asyncio
async def test_excerpt_fill_rate_empty():
    ctx = make_ctx([])
    item = {"evidence_index": []}
    result = await excerpt_fill_rate(item, ctx)
    assert result["populated"] == 0
    assert result["total"] == 0
