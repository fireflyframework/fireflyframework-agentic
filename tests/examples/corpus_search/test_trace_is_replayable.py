# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Headline test for the spec's central claim: a recorded ``ReasoningTrace``
is reproducible.

After running Q1 through the orchestrator and capturing the trace, we build
a *fresh* ``_LoopContext`` against equivalent (re-stubbed) corpus + retriever
backends, walk every ``ActionStep`` in the trace, call the corresponding
tool closure with the recorded ``tool_args``, and verify each replayed
observation matches its original.

If this test passes, "the trace is reproducible" is fact, not aspiration.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _CURRENT_CTX,
    _build_inspect_table_tool,
    _build_knowledge_search,
    _build_python_compute_tool,
    _build_sql_query,
    _LoopContext,
)
from fireflyframework_agentic.rag.retrieval.sql import SqlRetrievalOutcome
from fireflyframework_agentic.reasoning.trace import ActionStep, ObservationStep
from tests.examples.corpus_search.test_corpus_query_reasoning import (
    _build_rae,
    _chunk_hit_from_dict,
    _load_replay,
    _sql_outcome_from_dict,
)

_TOOL_BUILDERS = {
    "knowledge_search": _build_knowledge_search,
    "sql_query": _build_sql_query,
    "inspect_table": _build_inspect_table_tool,
    "python_compute": _build_python_compute_tool,
}


def _fresh_ctx(tmp_path: Path, fixture: dict) -> _LoopContext:
    """Build a fresh _LoopContext with mocks re-stubbed from the same fixture.

    The mocks' ``side_effect`` queues are reconstructed from the recorded
    ``stub_return`` payloads, so a second walk over the trace observes
    deterministically the same returns as the first run.
    """
    knowledge_returns: list = []
    sql_returns: list[SqlRetrievalOutcome] = []
    for d in fixture["decisions"]:
        if d.get("kind") != "tool_call":
            continue
        if d["tool_name"] == "knowledge_search":
            knowledge_returns.append([_chunk_hit_from_dict(c) for c in d["stub_return"]])
        elif d["tool_name"] == "sql_query":
            sql_returns.append(_sql_outcome_from_dict(d["stub_return"]))

    corpus = AsyncMock()
    corpus.retrieve.side_effect = knowledge_returns if knowledge_returns else [[]]
    retriever = AsyncMock()
    retriever.retrieve.side_effect = (
        sql_returns
        if sql_returns
        else [SqlRetrievalOutcome(outcome="unsupported", result_markdown=None, attempted_sql=None, probe_trail=[])]
    )

    return _LoopContext(
        corpus_agent=corpus,
        structured_retriever=retriever,
        schemas=[],
        db_path=tmp_path / "corpus.sqlite",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_trace_is_replayable(tmp_path):
    fixture = _load_replay("q1_yoy_growth")

    # 1. First run — captures the trace.
    rae = await _build_rae(tmp_path, fixture)
    answer = await rae.answer(fixture["question"], include_trace=True)
    trace = answer.reasoning_trace
    assert trace is not None and trace.steps, "expected a populated trace"

    # 2. Fresh _LoopContext (new mocks, fresh side_effect queues).
    fresh_ctx = _fresh_ctx(tmp_path, fixture)

    # 3+4. Walk the trace. For each ActionStep, call the matching tool with
    # the recorded tool_args. Pair each call with the original
    # ObservationStep that immediately followed in the trace, and compare.
    steps = list(trace.steps)
    tok = _CURRENT_CTX.set(fresh_ctx)
    replayed_pairs: list[tuple[str, str]] = []  # (original, replayed)
    try:
        for i, step in enumerate(steps):
            if not isinstance(step, ActionStep):
                continue
            # Find the next ObservationStep (skip any interleaved thoughts).
            next_obs = None
            for follow in steps[i + 1 :]:
                if isinstance(follow, ObservationStep) and follow.source == step.tool_name:
                    next_obs = follow
                    break
            assert next_obs is not None, f"step {i}: ActionStep({step.tool_name}) has no matching ObservationStep"

            builder = _TOOL_BUILDERS.get(step.tool_name)
            assert builder is not None, f"unknown tool in trace: {step.tool_name}"
            tool = builder()
            replay_result = await tool(**step.tool_args)
            replayed_pairs.append((next_obs.content, str(replay_result)))
    finally:
        _CURRENT_CTX.reset(tok)

    assert replayed_pairs, "expected at least one ActionStep in the trace"

    # 5. Each replayed observation must reproduce the original — modulo
    # the trace truncation suffix when the observation hit the 2 KB cap.
    # We require that the replay either equals the original verbatim, OR
    # starts with the same prefix the original recorded (when the original
    # was truncated). Tokens are split on whitespace so harmless formatting
    # differences (e.g. dict-iteration order in repr) don't cause flakes.
    for original, replayed in replayed_pairs:
        # Strip the truncation suffix from the original (if any) before
        # comparing: "x" * N + "… (M more bytes)" — match only the prefix.
        truncated_marker = "more bytes)"
        prefix_end = original.find(truncated_marker)
        original_prefix = original[: prefix_end - 4] if prefix_end >= 0 else original
        original_tokens = original_prefix.split()
        replayed_tokens = replayed.split()[: len(original_tokens)]
        assert original_tokens == replayed_tokens, (
            f"replay diverged:\n  ORIG: {original_prefix[:300]}\n  REP:  {replayed[:300]}"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_trace_action_args_are_json_serializable(tmp_path):
    """Every ActionStep.tool_args must round-trip through json. Without this
    invariant the trace stops being a portable artifact — re-execution would
    require side-channel state.
    """
    fixture = _load_replay("q5_operating_efficiency_2024q3")  # most complex trace
    rae = await _build_rae(tmp_path, fixture)
    answer = await rae.answer(fixture["question"], include_trace=True)
    assert answer.reasoning_trace is not None

    for step in answer.reasoning_trace.steps:
        if not isinstance(step, ActionStep):
            continue
        # Round-trip and assert equality.
        roundtripped = json.loads(json.dumps(step.tool_args))
        assert roundtripped == step.tool_args, (
            f"tool_args lost fidelity through JSON for {step.tool_name}: before={step.tool_args} after={roundtripped}"
        )
