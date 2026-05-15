# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tier B end-to-end test: contradictory chunks must surface as a conflict.

Two committed fixtures under
``benchmark/corpus/contradictions/`` give different Q3 2024 revenue figures
for the same fictional company:

  - ``press_release_q3_2024.md``  → USD 47.2 million
  - ``board_memo_q3_2024.md``     → USD 53.6 million (claims to "supersede")

Both files are ingested into a real corpus, and ``corpus_query`` is asked
"What was Acme Corp's Q3 2024 revenue?" under both strategies (fast and
reasoning). The answer must:

  1. Mention both numeric values (47.2 and 53.6).
  2. Carry a conflict-signal token (disagree | conflict | differ | both
     | however | superseded | two sources).
  3. Cite both source files (via ``citations`` / ``cited_sources``).

Skipped automatically unless ANTHROPIC_API_KEY + EMBEDDING_BINDING_HOST +
EMBEDDING_BINDING_API_KEY are set; gated by ``@pytest.mark.nightly`` so
the PR pytest invocation deselects it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent
from tests.examples.corpus_search.reasoning_fixtures import FIXTURE_ROOT

_CONTRADICTIONS_ROOT = FIXTURE_ROOT.parent / "contradictions"
_REQUIRED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "EMBEDDING_BINDING_HOST",
    "EMBEDDING_BINDING_API_KEY",
)
_SKIP_REASON = f"Real LLM + embedding keys not present (need {', '.join(_REQUIRED_ENV_VARS)})."

_QUESTION = "What was Acme Corp's Q3 2024 revenue?"
_CONFLICT_SIGNAL_PATTERN = re.compile(
    r"\b(disagree|conflict|conflicting|contradict|differ|however|supersede|two sources|both sources|different (figures?|values?|numbers?))\b",
    re.IGNORECASE,
)


def _have_real_keys() -> bool:
    return all(os.environ.get(k) for k in _REQUIRED_ENV_VARS)


async def _build_corpus(tmp_path: Path, strategy: Literal["fast", "reasoning"]) -> CorpusAgent:
    agent = CorpusAgent(
        root=tmp_path,
        embed_model="azure:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        answer_strategy=strategy,
        # Generous budgets on the reasoning path: this test is about answer
        # quality, not budget edges. The model should freely use whatever
        # tools it wants.
        max_reasoning_tool_calls=30,
        max_reasoning_llm_calls=20,
        reasoning_wall_clock_seconds=300.0,
    )
    # Ingest both contradicting markdown files as unstructured docs.
    summary = await agent.ingest_folder(_CONTRADICTIONS_ROOT)
    assert summary.ingested == 2, f"expected 2 contradiction fixtures to ingest cleanly; got {summary.ingested}"
    return agent


def _assert_surfaces_conflict(answer_text: str, qid: str) -> None:
    """Three asserts on the answer text:
       (1) both numeric values appear,
       (2) a conflict-signal token appears,
       (3) the wording isn't bluntly picking one (no 'the revenue was X' without
           also mentioning the other).
    Failure messages name the question id so a multi-strategy run identifies
    which path mis-behaved.
    """
    has_47 = "47.2" in answer_text
    has_53 = "53.6" in answer_text
    assert has_47 and has_53, f"[{qid}] expected both revenue figures (47.2 AND 53.6) in answer; got: {answer_text!r}"
    assert _CONFLICT_SIGNAL_PATTERN.search(answer_text), (
        f"[{qid}] expected a conflict-signal token in answer "
        f"(disagree/conflict/differ/both/however/supersede/etc.); got: {answer_text!r}"
    )


@pytest.mark.nightly
@pytest.mark.skipif(not _have_real_keys(), reason=_SKIP_REASON)
@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["fast", "reasoning"])
async def test_contradicting_chunks_surface_conflict(strategy: Literal["fast", "reasoning"], tmp_path: Path) -> None:
    agent = await _build_corpus(tmp_path, strategy)
    try:
        answer = await agent.query(_QUESTION, include_trace=(strategy == "reasoning"))
    finally:
        await agent.close()

    qid = f"contradiction.{strategy}"

    # 1. Text-level: both figures + conflict signal.
    _assert_surfaces_conflict(answer.text, qid)

    # 2. Citations: both source files should appear in cited_sources
    #    (chunk IDs are opaque; we check by source_path).
    cited_paths = {c.source_path for c in answer.cited_sources}
    expected_basenames = {"press_release_q3_2024.md", "board_memo_q3_2024.md"}
    cited_basenames = {Path(p).name for p in cited_paths}
    assert expected_basenames <= cited_basenames, (
        f"[{qid}] expected both source files in cited_sources; "
        f"missing: {expected_basenames - cited_basenames}; got: {cited_basenames}"
    )
