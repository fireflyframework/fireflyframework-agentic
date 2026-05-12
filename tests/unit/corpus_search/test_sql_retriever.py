# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.sql import (
    MAX_ROWS_IN_RESULT,
    ProbeRecord,
    SqlRetrievalOutcome,
    StructuredRetriever,
    _build_inspect_tool,
    _build_run_select_tool,
    _build_schema_context,
    _execute,
    _LoopContext,
)


def _schema() -> TargetSchema:
    return TargetSchema(
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


def _populated_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE products (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO products VALUES (1, 'Widget')")
    conn.execute("INSERT INTO products VALUES (2, 'Gadget')")
    conn.commit()
    conn.close()
    return db


def test_execute_returns_none_for_empty_result(tmp_path: Path):
    db = _populated_db(tmp_path)
    result = _execute(db, "SELECT * FROM products WHERE 1=0")
    assert result is None


# ---- Task 1: data model -------------------------------------------------


def test_probe_record_is_frozen_dataclass():
    from dataclasses import FrozenInstanceError

    r = ProbeRecord(table="t", column="c", op="distinct_values", result="a | b")
    assert r.table == "t"
    with pytest.raises(FrozenInstanceError):
        r.table = "u"  # type: ignore[misc]


def test_sql_retrieval_outcome_answered():
    out = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="col\n---\nval",
        attempted_sql="SELECT col FROM t",
        probe_trail=[],
    )
    assert out.outcome == "answered"
    assert out.result_markdown == "col\n---\nval"


def test_sql_retrieval_outcome_unsupported_default_shape():
    out = SqlRetrievalOutcome(
        outcome="unsupported",
        result_markdown=None,
        attempted_sql=None,
        probe_trail=[],
    )
    assert out.outcome == "unsupported"
    assert out.result_markdown is None


# ---- Task 2: _execute extensions ----------------------------------------


def test_execute_returns_error_message_on_sql_error(tmp_path: Path):
    db = _populated_db(tmp_path)
    result = _execute(db, "SELECT * FROM does_not_exist")
    assert result is not None
    assert "no such table" in result.lower()


def test_execute_caps_rows_and_appends_truncation_footer(tmp_path: Path):
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (n INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(MAX_ROWS_IN_RESULT + 5)])
    conn.commit()
    conn.close()
    result = _execute(db, "SELECT n FROM t ORDER BY n")
    assert result is not None
    body_lines = result.split("\n")
    # header + sep + capped rows + footer
    assert len(body_lines) == 2 + MAX_ROWS_IN_RESULT + 1
    assert body_lines[-1] == f"(+5 more rows; result capped at {MAX_ROWS_IN_RESULT})"


# ---- Task 3: inspect_table tool -----------------------------------------


def _seeded_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sales (period TEXT, region TEXT, product_name TEXT, revenue REAL)")
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?, ?, ?)",
        [
            ("2025-Q4", "EU-North", "MX-3000 Wireless Mouse", 1200.0),
            ("2025-Q4", "EU-South", "K10 Keyboard", 800.0),
            ("2025-Q3", "NA", "MX-3000 Wireless Mouse", 950.0),
        ],
    )
    conn.commit()
    conn.close()
    return db


def _sales_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="period", type=ColumnType.string),
                    ColumnSpec(name="region", type=ColumnType.string),
                    ColumnSpec(name="product_name", type=ColumnType.string),
                    ColumnSpec(name="revenue", type=ColumnType.float_),
                ],
            )
        ]
    )


@pytest.mark.asyncio
async def test_inspect_table_distinct_values(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("sales", "region", "distinct_values")
    assert "EU-North" in result
    assert "EU-South" in result
    assert "NA" in result
    assert len(ctx.probe_trail) == 1
    assert ctx.probe_trail[0].column == "region"
    assert ctx.probe_trail[0].op == "distinct_values"


@pytest.mark.asyncio
async def test_inspect_table_count(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("sales", "period", "count")
    assert "3" in result


@pytest.mark.asyncio
async def test_inspect_table_sample_rows(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("sales", "period", "sample_rows")
    assert "EU-North" in result or "EU-South" in result


@pytest.mark.asyncio
async def test_inspect_table_value_range(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("sales", "revenue", "value_range")
    assert "800" in result
    assert "1200" in result


@pytest.mark.asyncio
async def test_inspect_table_rejects_unknown_table(tmp_path: Path):
    from pydantic_ai.exceptions import ModelRetry

    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    # ModelRetry is pydantic-ai's hook for "tell the LLM and let it retry"
    # rather than terminating the loop on a typo'd name.
    with pytest.raises(ModelRetry, match="not in registered schemas"):
        await inspect("sqlite_master", "name", "distinct_values")


@pytest.mark.asyncio
async def test_inspect_table_rejects_unknown_column(tmp_path: Path):
    from pydantic_ai.exceptions import ModelRetry

    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    with pytest.raises(ModelRetry, match="column 'phantom' not in"):
        await inspect("sales", "phantom", "distinct_values")


# ---- Task 4: run_select tool --------------------------------------------


@pytest.mark.asyncio
async def test_run_select_returns_markdown_and_records_sql(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    result = await run_select("SELECT period, region FROM sales WHERE region='EU-North'")
    assert "EU-North" in result
    assert "2025-Q4" in result
    assert ctx.attempted_sql == "SELECT period, region FROM sales WHERE region='EU-North'"
    assert ctx.last_result_was_empty is False
    assert ctx.run_select_call_count == 1


@pytest.mark.asyncio
async def test_run_select_rejects_non_select(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    result = await run_select("DROP TABLE sales")
    assert "must start with SELECT" in result
    # The attempt is still recorded so cap-exhausted outcomes carry the SQL.
    assert ctx.attempted_sql == "DROP TABLE sales"


@pytest.mark.asyncio
async def test_run_select_returns_error_message_on_sql_error(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    result = await run_select("SELECT * FROM phantom_table")
    assert "SQL error" in result
    assert "no such table" in result.lower()


@pytest.mark.asyncio
async def test_run_select_sets_empty_flag_on_zero_rows(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    result = await run_select("SELECT * FROM sales WHERE region='Antarctica'")
    assert "0 rows" in result or "no rows" in result.lower()
    assert ctx.last_result_was_empty is True
    assert ctx.attempted_sql == "SELECT * FROM sales WHERE region='Antarctica'"


@pytest.mark.asyncio
async def test_run_select_detects_sentinel(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    await run_select("SELECT 1 WHERE 1=0")
    assert ctx.last_result_was_sentinel is True


# ---- Task 5: StructuredRetriever loop driver ----------------------------


@pytest.mark.asyncio
async def test_retrieve_empty_schemas_returns_unsupported(tmp_path: Path):
    retriever = StructuredRetriever(tmp_path / "corpus.sqlite")
    outcome = await retriever.retrieve("Anything?", schemas=[])
    assert outcome.outcome == "unsupported"
    assert outcome.result_markdown is None
    assert outcome.attempted_sql is None
    assert outcome.probe_trail == []


@pytest.mark.asyncio
async def test_retrieve_answered_after_probes(tmp_path: Path):
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_agent_run(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["inspect_table"]("sales", "region", "distinct_values")
        await tools["run_select"]("SELECT period, region FROM sales WHERE region='EU-North'")
        return MagicMock(output="done")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("Which periods saw EU-North sales?", schemas=[_sales_schema()])

    assert outcome.outcome == "answered"
    assert outcome.result_markdown is not None
    assert "EU-North" in outcome.result_markdown
    assert outcome.attempted_sql == "SELECT period, region FROM sales WHERE region='EU-North'"
    assert len(outcome.probe_trail) == 1
    assert outcome.probe_trail[0].column == "region"


@pytest.mark.asyncio
async def test_retrieve_empty_when_select_matches_nothing(tmp_path: Path):
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_agent_run(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["inspect_table"]("sales", "region", "distinct_values")
        await tools["run_select"]("SELECT * FROM sales WHERE region='Antarctica'")
        return MagicMock(output="no rows")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("Antarctica sales?", schemas=[_sales_schema()])

    assert outcome.outcome == "empty"
    assert outcome.result_markdown is None
    assert outcome.attempted_sql == "SELECT * FROM sales WHERE region='Antarctica'"
    assert len(outcome.probe_trail) == 1


@pytest.mark.asyncio
async def test_retrieve_unsupported_on_sentinel(tmp_path: Path):
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_agent_run(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["run_select"]("SELECT 1 WHERE 1=0")
        return MagicMock(output="give up")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("Something off-topic.", schemas=[_sales_schema()])

    assert outcome.outcome == "unsupported"


@pytest.mark.asyncio
async def test_retrieve_unsupported_when_agent_makes_no_tool_calls(tmp_path: Path):
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_agent_run(prompt, **kwargs):
        return MagicMock(output="I have nothing to do.")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("Question?", schemas=[_sales_schema()])

    assert outcome.outcome == "unsupported"
    assert outcome.attempted_sql is None


def test_build_schema_context_has_no_sample_values_section():
    """Sample values are now the agent's job — context should not include them."""
    ctx = _build_schema_context([_sales_schema()])
    assert "sales" in ctx
    assert "region" in ctx
    assert "sample" not in ctx.lower()


# ---- Reviewer fixes: concurrency, exception-recovery, ModelRetry --------


@pytest.mark.asyncio
async def test_retrieve_preserves_answered_when_agent_later_raises(tmp_path: Path):
    """If run_select succeeded and then the loop raises, outcome stays 'answered'.

    Reviewer C3: the broad `except Exception` previously discarded the
    successful run_select state and returned 'unsupported'. After the fix the
    terminal context state drives the outcome regardless of how the loop
    ended.
    """
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_agent_run(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["run_select"]("SELECT period, region FROM sales WHERE region='EU-North'")
        # Now simulate the agent's loop blowing up after the successful query
        # (e.g. UsageLimitExceeded, a model error, a network blip).
        raise RuntimeError("simulated post-success loop failure")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("EU-North sales?", schemas=[_sales_schema()])

    assert outcome.outcome == "answered", outcome
    assert outcome.result_markdown is not None
    assert "EU-North" in outcome.result_markdown


@pytest.mark.asyncio
async def test_retrieve_is_re_entrant_under_concurrent_calls(tmp_path: Path):
    """Two overlapping retrieve() calls on the same retriever must have isolated trails.

    Reviewer C1: `self._current_ctx` was shared across calls and the production
    MCP path caches one retriever per corpus_id. After the ContextVar fix each
    coroutine sees its own context.
    """
    import asyncio

    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    started_a = asyncio.Event()
    can_finish_a = asyncio.Event()

    async def fake_run_a(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["inspect_table"]("sales", "region", "distinct_values")
        started_a.set()
        await can_finish_a.wait()
        await tools["run_select"]("SELECT period, region FROM sales WHERE region='EU-North'")
        return MagicMock(output="done")

    async def fake_run_b(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["inspect_table"]("sales", "product_name", "distinct_values")
        await tools["run_select"]("SELECT period, region FROM sales WHERE region='EU-South'")
        return MagicMock(output="done")

    # Replace one agent on call A, another on call B — but since they share an
    # agent instance, alternate via a counter that picks the right side.
    call_idx = [0]

    async def dispatch(prompt, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        if idx == 0:
            return await fake_run_a(prompt, **kwargs)
        return await fake_run_b(prompt, **kwargs)

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=dispatch)):
        task_a = asyncio.create_task(retriever.retrieve("a", schemas=[_sales_schema()]))
        # Wait for A to hit its mid-call barrier (one probe registered),
        # then start B in parallel and let it run to completion first.
        await started_a.wait()
        outcome_b = await retriever.retrieve("b", schemas=[_sales_schema()])
        # Now let A finish.
        can_finish_a.set()
        outcome_a = await task_a

    # Each outcome must see only its own probes and its own SELECT.
    assert {p.column for p in outcome_a.probe_trail} == {"region"}, outcome_a.probe_trail
    assert outcome_a.attempted_sql == "SELECT period, region FROM sales WHERE region='EU-North'"
    assert {p.column for p in outcome_b.probe_trail} == {"product_name"}, outcome_b.probe_trail
    assert outcome_b.attempted_sql == "SELECT period, region FROM sales WHERE region='EU-South'"
