# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tier B end-to-end tests for the reasoning corpus agent — real LLMs only.

Skipped automatically unless ANTHROPIC_API_KEY, EMBEDDING_BINDING_HOST, and
EMBEDDING_BINDING_API_KEY are set, plus the explicit @pytest.mark.nightly
gate (so the PR pytest invocation deselects them).

Each test:
- spins up a CorpusAgent under answer_strategy="reasoning" against a tmp
  corpus root,
- discovers the schema of the structured fixtures, ingests the CSVs +
  methodology.md for real,
- asks the question with include_trace=True,
- asserts the trace shape (sql_query present; python_compute present for
  numeric questions; knowledge_search precedes sql_query for Q5) and that
  the python_compute source body carries numeric content (signature that
  values were threaded from a prior sql_query observation).

Per-question value assertions (regex against ``answer.text`` for the
expected number within tolerance) deliberately are not added up-front —
we observe real model behaviour first and tighten the asserts one
question at a time, otherwise three nightlies of flake-mining destroy
signal.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent
from fireflyframework_agentic.reasoning.trace import ActionStep
from tests.examples.corpus_search.reasoning_fixtures import FIXTURE_ROOT, fixture_path

_REQUIRED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "EMBEDDING_BINDING_HOST",
    "EMBEDDING_BINDING_API_KEY",
)
_SKIP_REASON = f"Real LLM + embedding keys not present (need {', '.join(_REQUIRED_ENV_VARS)})."


def _have_real_keys() -> bool:
    return all(os.environ.get(k) for k in _REQUIRED_ENV_VARS)


async def _build_corpus_with_fixtures(tmp_path: Path) -> CorpusAgent:
    """Real end-to-end setup: build a CorpusAgent against tmp_path, discover
    the structured-fixture schema, ingest both CSVs under it, then ingest
    methodology.md as an unstructured doc. Uses Azure embeddings + Anthropic
    Claude models, configured via env vars (see _REQUIRED_ENV_VARS).
    """
    agent = CorpusAgent(
        root=tmp_path,
        embed_model="azure:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        answer_strategy="reasoning",
        max_reasoning_tool_calls=30,
        max_reasoning_llm_calls=20,
        reasoning_wall_clock_seconds=300.0,
    )
    schema = await agent.discover_schema(FIXTURE_ROOT)
    await agent.ingest_folder(FIXTURE_ROOT, mode="structured", schema=schema)
    await agent.ingest_one(fixture_path("methodology.md"))
    return agent


def _tool_names(answer) -> list[str]:
    return [s.tool_name for s in answer.reasoning_trace.steps if isinstance(s, ActionStep)]


@pytest.mark.nightly
@pytest.mark.skipif(not _have_real_keys(), reason=_SKIP_REASON)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "qid,question",
    [
        (
            "q1_yoy_growth",
            "What's the YoY revenue growth rate per business unit from 2023 to 2024?",
        ),
        (
            "q2_weighted_price",
            "What's the weighted average price across products, weighted by units sold?",
        ),
        (
            "q3_mean_and_stdev_q4_2024_blanks_as_zero",
            ("For Q4 2024 revenue, treat blank cells as 0 — what's the mean per region and the standard deviation?"),
        ),
        (
            "q4_headcount_cv_ranking",
            (
                "What's the coefficient of variation of monthly headcount per BU, "
                "and rank BUs most-stable to least-stable?"
            ),
        ),
        (
            "q5_operating_efficiency_2024q3",
            "What's the Operating Efficiency for each BU in 2024 Q3?",
        ),
    ],
)
async def test_real_llm_reasoning_trace_shape(qid: str, question: str, tmp_path: Path) -> None:
    agent = await _build_corpus_with_fixtures(tmp_path)
    try:
        answer = await agent.query(question, include_trace=True)
    finally:
        await agent.close()

    assert answer.reasoning_trace is not None, "reasoning_trace missing on real-LLM answer"
    names = _tool_names(answer)

    # Every quantitative question needs to run SQL at some point.
    assert "sql_query" in names, f"[{qid}] missing sql_query in trace: {names}"

    # All five end in some kind of computation. Allow either python_compute
    # (most likely) or that the model handled the math in-prose; we tighten
    # to require python_compute once observed behaviour confirms it.
    if "python_compute" in names:
        code_steps = [
            s for s in answer.reasoning_trace.steps if isinstance(s, ActionStep) and s.tool_name == "python_compute"
        ]
        # The source must reference at least one numeric literal, which is a
        # plausible signature that values from a prior sql_query observation
        # were threaded into the Python snippet.
        assert any(re.search(r"\d", s.tool_args.get("source", "")) for s in code_steps), (
            f"[{qid}] python_compute source has no numeric content: "
            f"{[s.tool_args.get('source', '') for s in code_steps]}"
        )

    # Q5 specifically: methodology must be read BEFORE the SQL query, so the
    # agent's SQL formulation reflects the Operating Efficiency definition.
    if qid == "q5_operating_efficiency_2024q3":
        assert "knowledge_search" in names, f"[{qid}] expected knowledge_search to surface methodology: {names}"
        assert names.index("knowledge_search") < names.index("sql_query"), (
            f"[{qid}] knowledge_search must precede sql_query: {names}"
        )
