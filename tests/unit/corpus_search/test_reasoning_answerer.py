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


from fireflyframework_agentic.rag.retrieval.reasoning_answerer import _build_sql_query  # noqa: E402
from fireflyframework_agentic.rag.retrieval.sql import (  # noqa: E402
    ProbeRecord,
    SqlRetrievalOutcome,
)


@pytest.mark.asyncio
async def test_sql_query_serialises_outcome_and_records():
    outcome = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="| col |\n| --- |\n| 1 |",
        attempted_sql="SELECT col FROM t",
        probe_trail=[ProbeRecord(table="t", column="col", op="count", result="1")],
    )
    retriever = AsyncMock()
    retriever.retrieve.return_value = outcome
    ctx = _LoopContext(
        corpus_agent=None,
        structured_retriever=retriever,
        schemas=[],
        db_path=Path("/tmp/x.sqlite"),
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        sql_query = _build_sql_query()
        out = await sql_query(question="how many rows?")
    finally:
        _CURRENT_CTX.reset(tok)
    assert out["outcome"] == "answered"
    assert out["attempted_sql"] == "SELECT col FROM t"
    assert "| col |" in out["result_markdown"]
    assert out["probe_trail"] == [{"table": "t", "column": "col", "op": "count", "result": "1"}]
    assert ctx.sql_calls == [outcome]


import sqlite3  # noqa: E402

from fireflyframework_agentic.rag.ingest.structured_schema import (  # noqa: E402
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (  # noqa: E402
    _build_inspect_table_tool,
)


@pytest.mark.asyncio
async def test_inspect_table_distinct_values(tmp_path):
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE products (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO products VALUES (1, 'Widget'), (2, 'Gadget')")
    conn.commit()
    conn.close()
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="products",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                    ColumnSpec(name="name", type=ColumnType.string),
                ],
            )
        ]
    )
    ctx = _LoopContext(
        corpus_agent=None,
        structured_retriever=None,
        schemas=[schema],
        db_path=db,
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        inspect_table = _build_inspect_table_tool()
        out = await inspect_table(table="products", column="name", op="distinct_values")
    finally:
        _CURRENT_CTX.reset(tok)
    assert "Widget" in out and "Gadget" in out


from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (  # noqa: E402
    _build_python_compute_tool,
)


@pytest.mark.asyncio
async def test_python_compute_tool_runs_source_with_data():
    ctx = _LoopContext(
        corpus_agent=None,
        structured_retriever=None,
        schemas=[],
        db_path=Path("/tmp/x.sqlite"),
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        python_compute = _build_python_compute_tool()
        out = await python_compute(source="result = sum(xs)", data={"xs": [1, 2, 3]})
    finally:
        _CURRENT_CTX.reset(tok)
    assert "6" in out


from pydantic_ai.models.test import TestModel  # noqa: E402

from fireflyframework_agentic.rag.retrieval.answerer import Answer  # noqa: E402
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (  # noqa: E402
    ReasoningAnswerAgent,
)


@pytest.mark.asyncio
async def test_reasoning_answerer_runs_with_stub_model_and_returns_answer(tmp_path):
    hit = ChunkHit(chunk_id="c1", score=1.0, content="X", metadata={}, source_path="/x")
    corpus = AsyncMock()
    corpus.retrieve.return_value = [hit]
    retriever = AsyncMock()
    retriever.retrieve.return_value = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="| n |\n|-|\n|1|",
        attempted_sql="SELECT 1",
        probe_trail=[],
    )
    schema_registry = AsyncMock()
    schema_registry.list_schemas.return_value = []

    # call_tools=[] tells TestModel to skip tool invocation and emit a
    # default Answer directly — we're testing the orchestrator wiring,
    # not the model's tool-picking. End-to-end tool exercise lives in the
    # Tier A replay tests.
    rae = ReasoningAnswerAgent(
        model=TestModel(call_tools=[]),
        corpus_agent=corpus,
        structured_retriever=retriever,
        schema_registry=schema_registry,
        db_path=tmp_path / "corpus.sqlite",
        max_tool_calls=4,
        max_llm_calls=4,
        wall_clock_seconds=10.0,
    )
    answer = await rae.answer("how many?", include_trace=True)
    assert isinstance(answer, Answer)
    assert answer.reasoning_trace is not None


# ---- Graceful degradation: fallback synthesiser on budget exhaustion ----


class _FakeUsageLimitError(Exception):
    """Stand-in for pydantic-ai's UsageLimitExceeded. Defined at module
    scope so it's a stable class identity rather than a per-test inner type.
    The reasoning_answerer's exception handler labels exceptions by class
    name + message, so any class whose name contains 'UsageLimit' routes
    through the tool_limit / llm_limit branches.
    """


@pytest.mark.asyncio
async def test_falls_back_to_answer_agent_on_timeout(tmp_path):
    """When asyncio.wait_for cancels the inner loop, the user must still get
    a grounded Answer synthesised from whatever evidence the tools managed
    to collect — not an apology. We assert (1) the fallback synthesiser was
    called with the accumulated chunks + the last SQL outcome, (2) the
    returned Answer is the one it produced, and (3) the terminal_state
    counter still records the timeout label."""
    hit = ChunkHit(chunk_id="c1", score=1.0, content="hi", metadata={}, source_path="/x")
    sql_outcome = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="| n |\n|-|\n|1|",
        attempted_sql="SELECT 1",
        probe_trail=[],
    )

    corpus = AsyncMock()
    corpus.retrieve.return_value = [hit]
    retriever = AsyncMock()
    retriever.retrieve.return_value = sql_outcome
    schema_registry = AsyncMock()
    schema_registry.list_schemas.return_value = []

    rae = ReasoningAnswerAgent(
        model=TestModel(call_tools=[]),
        corpus_agent=corpus,
        structured_retriever=retriever,
        schema_registry=schema_registry,
        db_path=tmp_path / "corpus.sqlite",
    )

    # Pre-seed the loop context as if the agent had managed to call both
    # tools before timing out. We do this by stubbing the inner agent.run
    # to populate ctx as a side-effect, then raise TimeoutError.
    async def _populate_then_timeout(*args, **kwargs):
        # Mimic the closures running once each.
        await rae._knowledge_search("q", top_k=1)
        await rae._sql_query("how many?")
        raise TimeoutError("simulated")

    rae._agent.run = AsyncMock(side_effect=_populate_then_timeout)  # type: ignore[method-assign]

    expected = Answer(text="From SQL results: 1.", citations=[], cited_sources=[])
    rae._fallback_answerer.answer = AsyncMock(return_value=expected)  # type: ignore[method-assign]

    answer = await rae.answer("how many?", include_trace=True)

    # Fallback was called with the accumulated state.
    rae._fallback_answerer.answer.assert_awaited_once()
    call_args = rae._fallback_answerer.answer.await_args
    assert call_args.args[0] == "how many?"
    passed_hits = call_args.args[1]
    assert [h.chunk_id for h in passed_hits] == ["c1"]
    assert call_args.kwargs["sql_outcome"] is sql_outcome

    # Answer is what the fallback returned.
    assert answer is expected
    # No partial-Answer apology text.
    assert "couldn't complete reasoning" not in answer.text


@pytest.mark.asyncio
async def test_falls_back_on_usage_limit_exceeded(tmp_path):
    """A UsageLimitExceeded-shaped exception (the most common failure mode
    in practice — caller burns the tool-call or LLM-call budget) routes
    through the fallback synthesiser identically to the timeout path."""
    corpus = AsyncMock()
    corpus.retrieve.return_value = []
    retriever = AsyncMock()
    retriever.retrieve.return_value = SqlRetrievalOutcome(
        outcome="unsupported", result_markdown=None, attempted_sql=None, probe_trail=[]
    )
    schema_registry = AsyncMock()
    schema_registry.list_schemas.return_value = []

    rae = ReasoningAnswerAgent(
        model=TestModel(call_tools=[]),
        corpus_agent=corpus,
        structured_retriever=retriever,
        schema_registry=schema_registry,
        db_path=tmp_path / "corpus.sqlite",
    )
    rae._agent.run = AsyncMock(  # type: ignore[method-assign]
        side_effect=_FakeUsageLimitError("Exceeded tool_calls_limit of 20")
    )

    expected = Answer(text="(no info)", citations=[], cited_sources=[])
    rae._fallback_answerer.answer = AsyncMock(return_value=expected)  # type: ignore[method-assign]

    answer = await rae.answer("anything", include_trace=False)

    assert answer is expected
    rae._fallback_answerer.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_falls_back_to_apology_when_synthesiser_also_fails(tmp_path):
    """If even the fallback synthesiser raises, we never propagate the
    exception out of answer() — the orchestrator returns a structured
    Answer-shaped error so callers' contracts hold."""
    corpus = AsyncMock()
    corpus.retrieve.return_value = []
    retriever = AsyncMock()
    retriever.retrieve.return_value = SqlRetrievalOutcome(
        outcome="unsupported", result_markdown=None, attempted_sql=None, probe_trail=[]
    )
    schema_registry = AsyncMock()
    schema_registry.list_schemas.return_value = []

    rae = ReasoningAnswerAgent(
        model=TestModel(call_tools=[]),
        corpus_agent=corpus,
        structured_retriever=retriever,
        schema_registry=schema_registry,
        db_path=tmp_path / "corpus.sqlite",
    )
    rae._agent.run = AsyncMock(side_effect=TimeoutError("simulated"))  # type: ignore[method-assign]
    rae._fallback_answerer.answer = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("model unreachable")
    )

    answer = await rae.answer("anything")

    assert isinstance(answer, Answer)
    assert "couldn't complete reasoning (timeout)" in answer.text
    assert "fallback synthesiser also failed" in answer.text


# ---- Sharpened python_compute decision rules in the system prompt ----


def test_system_prompt_requires_python_compute_for_arithmetic():
    """Hard rule in the system prompt: the agent MUST call python_compute
    for any answer involving arithmetic. Soft-suggestions ('verify with…')
    drift across turns; a MUST rule is what the model actually follows.
    """
    from fireflyframework_agentic.rag.retrieval.reasoning_answerer import _SYSTEM

    assert "MUST call python_compute" in _SYSTEM, (
        "the python_compute hard-rule sentence must be present in _SYSTEM — "
        "removing it regresses arithmetic accuracy on numeric questions"
    )
    # Spot-check that the trigger list is comprehensive: callers rely on
    # python_compute firing across these patterns, not just a subset.
    # Flatten whitespace before matching so line-wrapping in the prompt
    # doesn't break the assertion.
    import re

    flat = re.sub(r"\s+", " ", _SYSTEM)
    for trigger in ("sums", "averages", "ratios", "percentages", "growth rates", "rankings"):
        assert trigger in flat, f"trigger '{trigger}' missing from _SYSTEM rule"


def test_python_compute_tool_description_steers_arithmetic():
    """The tool-catalog entry should also tell the model that python_compute
    is the right tool for arithmetic — defense in depth, since pydantic-ai
    surfaces tool descriptions to the model independently of the system
    prompt's strategy section.
    """
    from fireflyframework_agentic.rag.retrieval.reasoning_answerer import _SYSTEM

    # The tool description sits in the "Available tools:" block.
    tools_section = _SYSTEM.split("Strategy:")[0]
    assert "python_compute" in tools_section
    assert "arithmetic" in tools_section.lower(), "the python_compute tool-catalog entry must reference arithmetic"
