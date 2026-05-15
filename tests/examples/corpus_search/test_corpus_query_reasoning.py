# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tier A end-to-end tests for the reasoning corpus answer agent.

Each test drives ``ReasoningAnswerAgent`` with:
- a ``FunctionModel`` that replays a pre-recorded tool-decision sequence
  from ``replay/<qid>.json``,
- stubs for ``corpus_agent.retrieve`` (returns recorded ChunkHits) and
  ``structured_retriever.retrieve`` (returns recorded SqlRetrievalOutcomes),
- the real ``python_compute`` sandbox (no stubbing — does the actual math),
- the real trace-translation + citation-enrichment paths.

This is intentionally NOT a full corpus-roundtrip test (real embedder +
real sqlite-vec ingest + real inner SQL agent): the spec's central claim
is that traces are *reproducible*, and that property is testable at this
seam — given the same ``tool_args``, the same stubs deterministically
produce the same observations, and ``python_compute`` deterministically
produces the same numbers. Real end-to-end with real LLMs lives in
``test_corpus_query_reasoning_real_llm.py`` (Tier B / nightly).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    ReasoningAnswerAgent,
)
from fireflyframework_agentic.rag.retrieval.sql import (
    ProbeRecord,
    SqlRetrievalOutcome,
)
from fireflyframework_agentic.reasoning.trace import ActionStep
from tests.examples.corpus_search.reasoning_fixtures import GROUND_TRUTH

REPLAY_ROOT = Path(__file__).parent / "replay"


# ---- Stub helpers ---------------------------------------------------------


def _chunk_hit_from_dict(d: dict[str, Any]) -> ChunkHit:
    return ChunkHit(
        chunk_id=d["chunk_id"],
        score=d.get("score", 1.0),
        content=d["content"],
        metadata=d.get("metadata", {}),
        source_path=d.get("source_path", ""),
    )


def _sql_outcome_from_dict(d: dict[str, Any]) -> SqlRetrievalOutcome:
    return SqlRetrievalOutcome(
        outcome=d["outcome"],
        result_markdown=d.get("result_markdown"),
        attempted_sql=d.get("attempted_sql"),
        probe_trail=[
            ProbeRecord(table=p["table"], column=p["column"], op=p["op"], result=p["result"])
            for p in d.get("probe_trail", [])
        ],
    )


def _split_replay(decisions: list[dict]) -> tuple[list[dict], list[Any], list[SqlRetrievalOutcome]]:
    """Walk decisions once and pre-extract:
    - the tool-call decisions (model's outputs) for the FunctionModel,
    - the queued knowledge_search stub returns (in order of call),
    - the queued sql_query stub returns (in order of call).
    """
    knowledge_returns: list[Any] = []
    sql_returns: list[SqlRetrievalOutcome] = []
    for d in decisions:
        if d.get("kind") != "tool_call":
            continue
        if d["tool_name"] == "knowledge_search":
            knowledge_returns.append([_chunk_hit_from_dict(c) for c in d["stub_return"]])
        elif d["tool_name"] == "sql_query":
            sql_returns.append(_sql_outcome_from_dict(d["stub_return"]))
    return decisions, knowledge_returns, sql_returns


def _build_replay_model(decisions: list[dict]) -> FunctionModel:
    """Build a FunctionModel whose ``call(messages, info)`` emits the next
    recorded decision on each invocation. ``final_answer`` is emitted as a
    call to pydantic-ai's implicit output tool (``info.output_tools[0]``),
    so the inner Agent routes it through validation into ``Answer``.
    """
    state = {"i": 0}

    async def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        idx = state["i"]
        state["i"] += 1
        if idx >= len(decisions):
            raise AssertionError(f"FunctionModel ran out of decisions at call #{idx}")
        d = decisions[idx]
        if d["kind"] == "tool_call":
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_call_id=f"t{idx}",
                        tool_name=d["tool_name"],
                        args=d["args"],
                    )
                ]
            )
        if d["kind"] == "final_answer":
            assert info.output_tools, "pydantic-ai did not register an output tool"
            final_name = info.output_tools[0].name
            payload = {
                "text": d["text"],
                "citations": d.get("citations", []),
            }
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_call_id=f"final{idx}",
                        tool_name=final_name,
                        args=payload,
                    )
                ]
            )
        raise ValueError(f"unknown decision kind: {d['kind']}")

    return FunctionModel(call)


async def _build_rae(tmp_path: Path, fixture: dict) -> ReasoningAnswerAgent:
    """Construct a ReasoningAnswerAgent wired to stubbed corpus + retriever,
    real python_compute, and a FunctionModel that replays the fixture.
    """
    decisions, knowledge_returns, sql_returns = _split_replay(fixture["decisions"])

    corpus = AsyncMock()
    corpus.retrieve.side_effect = knowledge_returns if knowledge_returns else [[]]
    retriever = AsyncMock()
    retriever.retrieve.side_effect = (
        sql_returns
        if sql_returns
        else [SqlRetrievalOutcome(outcome="unsupported", result_markdown=None, attempted_sql=None, probe_trail=[])]
    )
    schema_registry = AsyncMock()
    schema_registry.list_schemas.return_value = []

    return ReasoningAnswerAgent(
        model=_build_replay_model(decisions),
        corpus_agent=corpus,
        structured_retriever=retriever,
        schema_registry=schema_registry,
        db_path=tmp_path / "corpus.sqlite",
        max_tool_calls=20,
        max_llm_calls=20,
        wall_clock_seconds=30.0,
    )


def _load_replay(qid: str) -> dict:
    return json.loads((REPLAY_ROOT / f"{qid}.json").read_text())


def _tool_names_in_trace(answer) -> list[str]:
    return [s.tool_name for s in answer.reasoning_trace.steps if isinstance(s, ActionStep)]


# ---- Per-question tests --------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_q1_yoy_growth(tmp_path):
    fixture = _load_replay("q1_yoy_growth")
    rae = await _build_rae(tmp_path, fixture)

    answer = await rae.answer(fixture["question"], include_trace=True)

    # Answer mentions each BU and a percentage.
    for bu in GROUND_TRUTH["q1_yoy_growth"]["by_bu"]:
        assert bu in answer.text, f"missing {bu} in answer: {answer.text}"
    assert "%" in answer.text

    # Trace shape: sql_query then python_compute.
    names = _tool_names_in_trace(answer)
    assert "sql_query" in names and "python_compute" in names
    assert names.index("sql_query") < names.index("python_compute"), f"sql_query should precede python_compute: {names}"

    # python_compute observation contains the real computed values within tolerance.
    obs = [s for s in answer.reasoning_trace.steps if getattr(s, "source", "") == "python_compute"]
    assert obs, "missing python_compute observation"
    body = obs[-1].content
    expected = GROUND_TRUTH["q1_yoy_growth"]["by_bu"]
    for bu in expected:
        assert bu in body, f"python_compute output missing {bu}: {body}"
    # The sandbox rounds to 2 decimals; spot-check that Alpha's value appears.
    assert "28.91" in body or "28.9" in body, f"expected Alpha ~28.91 in: {body}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_q2_weighted_price(tmp_path):
    fixture = _load_replay("q2_weighted_price")
    rae = await _build_rae(tmp_path, fixture)

    answer = await rae.answer(fixture["question"], include_trace=True)

    names = _tool_names_in_trace(answer)
    assert "sql_query" in names and "python_compute" in names

    obs = [s for s in answer.reasoning_trace.steps if getattr(s, "source", "") == "python_compute"]
    assert obs
    # 3279099.49 / 21213 ≈ 154.58; sandbox rounds to 2 decimals.
    assert "154.58" in obs[-1].content, f"expected 154.58 in: {obs[-1].content}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_q3_mean_and_stdev_blanks_as_zero(tmp_path):
    fixture = _load_replay("q3_mean_and_stdev_q4_2024_blanks_as_zero")
    rae = await _build_rae(tmp_path, fixture)

    answer = await rae.answer(fixture["question"], include_trace=True)

    names = _tool_names_in_trace(answer)
    assert "sql_query" in names and "python_compute" in names

    obs = [s for s in answer.reasoning_trace.steps if getattr(s, "source", "") == "python_compute"]
    assert obs
    body = obs[-1].content
    # The python_compute output is a dict literal; both regions appear.
    assert "NA" in body and "EU" in body, f"both regions expected: {body}"
    assert "mean" in body and "stdev" in body, f"both stats expected: {body}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_q4_headcount_cv_ranking(tmp_path):
    fixture = _load_replay("q4_headcount_cv_ranking")
    rae = await _build_rae(tmp_path, fixture)

    answer = await rae.answer(fixture["question"], include_trace=True)

    names = _tool_names_in_trace(answer)
    assert "sql_query" in names and "python_compute" in names

    obs = [s for s in answer.reasoning_trace.steps if getattr(s, "source", "") == "python_compute"]
    assert obs
    body = obs[-1].content
    # Ranking from ground truth: Beta, Gamma, Alpha. The dict repr leads
    # with "cv" which orders by insertion (Alpha first); look at the
    # ranking_most_to_least_stable list specifically.
    ranking_start = body.find("ranking_most_to_least_stable")
    assert ranking_start >= 0, f"expected ranking list in output: {body}"
    ranking_segment = body[ranking_start:]
    beta = ranking_segment.find("Beta")
    gamma = ranking_segment.find("Gamma")
    alpha = ranking_segment.find("Alpha")
    assert 0 <= beta < gamma < alpha, f"expected ranking Beta < Gamma < Alpha in segment: {ranking_segment}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_q5_operating_efficiency(tmp_path):
    fixture = _load_replay("q5_operating_efficiency_2024q3")
    rae = await _build_rae(tmp_path, fixture)

    answer = await rae.answer(fixture["question"], include_trace=True)

    names = _tool_names_in_trace(answer)
    # Must use knowledge_search (methodology), THEN sql_query, THEN python_compute.
    assert "knowledge_search" in names
    assert "sql_query" in names
    assert "python_compute" in names
    assert names.index("knowledge_search") < names.index("sql_query"), (
        f"agent should read the methodology before querying: {names}"
    )
    assert names.index("sql_query") < names.index("python_compute")

    # Citation enrichment: methodology chunk_id should be present in cited_sources.
    assert any(c.chunk_id == "methodology#1" for c in answer.cited_sources), (
        f"expected methodology#1 in cited_sources: {answer.cited_sources}"
    )
    assert any(c.source_path == "methodology.md" for c in answer.cited_sources), (
        f"expected methodology.md source_path in cited_sources: {answer.cited_sources}"
    )

    # Numerics computed from canned tool returns.
    obs = [s for s in answer.reasoning_trace.steps if getattr(s, "source", "") == "python_compute"]
    assert obs
    body = obs[-1].content
    # Alpha ≈ 5322.90, Beta ≈ 5972.83, Gamma ≈ 3607.97 — sandbox rounds to 2 dp.
    assert "5322.9" in body and "5972.8" in body and "3607.9" in body, (
        f"expected OE values per BU in python_compute output: {body}"
    )
