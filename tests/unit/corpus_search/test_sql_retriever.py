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


@pytest.mark.asyncio
async def test_retrieve_returns_none_for_empty_schemas(tmp_path: Path):
    retriever = StructuredRetriever(tmp_path / "corpus.sqlite")
    result = await retriever.retrieve("How many products?", schemas=[])
    assert result is None


@pytest.mark.asyncio
async def test_retrieve_returns_markdown_table(tmp_path: Path):
    db = _populated_db(tmp_path)
    retriever = StructuredRetriever(db)
    mock_result = MagicMock()
    mock_result.output.sql = "SELECT id, name FROM products"
    with patch.object(retriever, "_sql_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        result = await retriever.retrieve("List all products", schemas=[_schema()])
    assert result is not None
    assert "Widget" in result
    assert "Gadget" in result


@pytest.mark.asyncio
async def test_retrieve_rejects_non_select_sql(tmp_path: Path):
    db = _populated_db(tmp_path)
    retriever = StructuredRetriever(db)
    mock_result = MagicMock()
    mock_result.output.sql = "DROP TABLE products"
    with patch.object(retriever, "_sql_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        result = await retriever.retrieve("drop table", schemas=[_schema()])
    assert result is None


def test_build_schema_context():
    ctx = _build_schema_context([_schema()])
    assert "products" in ctx
    assert "id" in ctx
    assert "name" in ctx


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
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    with pytest.raises(ValueError, match="not in registered schemas"):
        await inspect("sqlite_master", "name", "distinct_values")


@pytest.mark.asyncio
async def test_inspect_table_rejects_unknown_column(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    with pytest.raises(ValueError, match="column 'phantom' not in"):
        await inspect("sales", "phantom", "distinct_values")
