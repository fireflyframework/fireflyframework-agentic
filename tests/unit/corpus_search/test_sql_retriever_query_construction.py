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

"""Replay-style regression tests for SQL agent query-construction fixes.

These tests pin the *expected* tool-call sequence the new prompt should
drive for each of the three failure modes documented in issues #161,
#162, #163. They are not LLM-driven — they fake the agent's run and
exercise the tools directly, asserting that when the tools are called
in the "expected" order, the resulting outcome carries the corrected
SQL and the correct downstream answer.

This guards against regressions: future prompt edits that break the
intended pattern would also break these tests if the corrected SQL
stops producing the corrected result. Whether the LLM actually follows
the new prompt is measured by the live E2E suite in
``tests/examples/corpus_search/``.
"""

from __future__ import annotations

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
    StructuredRetriever,
    _build_schema_context,
)

# ---- #161: discriminator filter on aggregate ----------------------------


def _finance_fact_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE finance_fact (year TEXT, market TEXT, metric_line TEXT, value REAL)")
    conn.executemany(
        "INSERT INTO finance_fact VALUES (?, ?, ?, ?)",
        [
            ("2024", "EU", "Total Revenue", 1000.0),
            ("2024", "EU", "Active Headcount", 320.0),
            ("2024", "EU", "Operating Expense", 800.0),
            ("2024", "EU", "Total Revenue", 200.0),
        ],
    )
    conn.commit()
    conn.close()
    return db


def _finance_fact_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="finance_fact",
                columns=[
                    ColumnSpec(name="year", type=ColumnType.string),
                    ColumnSpec(name="market", type=ColumnType.string),
                    ColumnSpec(name="metric_line", type=ColumnType.string),
                    ColumnSpec(name="value", type=ColumnType.float_),
                ],
            )
        ]
    )


def test_schema_context_flags_metric_line_as_low_cardinality(tmp_path: Path):
    """The cardinality annotation is the structural signal that drives the
    prompt's discriminator rule (#161). Without this signal the agent has no
    way to tell ``metric_line`` apart from ``market`` at schema-read time.
    """
    db = _finance_fact_db(tmp_path)
    ctx = _build_schema_context([_finance_fact_schema()], db)
    # 3 distinct metric_line values — clearly a discriminator.
    assert "metric_line (string, 3 distinct)" in ctx
    # Year and market are also annotated so the agent sees the contrast.
    assert "year (string, 1 distinct)" in ctx
    assert "market (string, 1 distinct)" in ctx


@pytest.mark.asyncio
async def test_discriminator_filter_pattern_yields_correct_aggregate(tmp_path: Path):
    """Replay the corrected pattern from #161 and assert the answer is 1200.

    The agent's expected sequence under the new prompt:
      1. inspect_table(finance_fact, metric_line, 'distinct_values') — see the 3 values.
      2. run_select(...) — SUM(value) with WHERE metric_line='Total Revenue'.

    Result must be 1200 (not 2320, which is what the un-filtered aggregate
    would produce).
    """
    db = _finance_fact_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_run(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["inspect_table"]("finance_fact", "metric_line", "distinct_values")
        await tools["run_select"](
            "SELECT SUM(value) FROM finance_fact WHERE year='2024' AND market='EU' AND metric_line='Total Revenue'"
        )
        return MagicMock(output="done")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_run)):
        outcome = await retriever.retrieve(
            "What is the 2024 revenue for market EU?",
            schemas=[_finance_fact_schema()],
        )

    assert outcome.outcome == "answered"
    assert outcome.attempted_sql is not None
    assert "metric_line='Total Revenue'" in outcome.attempted_sql
    assert outcome.result_markdown is not None
    # SUM = 1000 + 200 = 1200 (Total Revenue rows only).
    assert "1200" in outcome.result_markdown


# ---- #162: GROUP BY at parent level -------------------------------------


def _performance_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE performance (team_id INTEGER, team_name TEXT, business_unit TEXT, achievement_pct REAL)")
    conn.executemany(
        "INSERT INTO performance VALUES (?, ?, ?, ?)",
        [
            (1, "Alpha", "North", 105.8),
            (2, "Beta", "North", 78.5),
            (3, "Gamma", "South", 72.8),
            (4, "Delta", "South", 91.1),
        ],
    )
    conn.commit()
    conn.close()
    return db


def _performance_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="performance",
                columns=[
                    ColumnSpec(name="team_id", type=ColumnType.integer),
                    ColumnSpec(name="team_name", type=ColumnType.string),
                    ColumnSpec(name="business_unit", type=ColumnType.string),
                    ColumnSpec(name="achievement_pct", type=ColumnType.float_),
                ],
            )
        ]
    )


def test_schema_context_exposes_parent_child_cardinality_gap(tmp_path: Path):
    """The 2:4 distinct ratio between business_unit and team_name is what the
    prompt's GROUP-BY rule keys off (#162). The annotation makes it visible.
    """
    db = _performance_db(tmp_path)
    ctx = _build_schema_context([_performance_schema()], db)
    assert "business_unit (string, 2 distinct)" in ctx
    assert "team_name (string, 4 distinct)" in ctx


@pytest.mark.asyncio
async def test_group_by_parent_pattern_yields_two_rows(tmp_path: Path):
    """Replay the corrected pattern from #162 and assert one row per BU.

    The agent's expected sequence:
      run_select("SELECT business_unit, AVG(achievement_pct) "
                 "FROM performance GROUP BY business_unit")
    """
    db = _performance_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_run(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["run_select"]("SELECT business_unit, AVG(achievement_pct) FROM performance GROUP BY business_unit")
        return MagicMock(output="done")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_run)):
        outcome = await retriever.retrieve(
            "What is the average achievement by business_unit?",
            schemas=[_performance_schema()],
        )

    assert outcome.outcome == "answered"
    assert outcome.result_markdown is not None
    assert "GROUP BY business_unit" in (outcome.attempted_sql or "")
    # 2 BUs → 2 rows under the header+separator.
    lines = outcome.result_markdown.strip().split("\n")
    assert len(lines) == 4  # header, sep, North, South
    assert "North" in outcome.result_markdown
    assert "South" in outcome.result_markdown
    # North avg = (105.8 + 78.5) / 2 = 92.15; South avg = (72.8 + 91.1) / 2 = 81.95.
    # IEEE noise: SQLite returns 81.9499999... so match the leading prefix.
    assert "92.15" in outcome.result_markdown
    assert "81.94" in outcome.result_markdown or "81.95" in outcome.result_markdown


# ---- #163: sibling-column scan when obvious column is NULL --------------


def _employee_changes_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE employee_changes ("
        "employee_id INTEGER, name TEXT, recorded_movement TEXT, "
        "effective_date_of_route_change TEXT, role_change TEXT)"
    )
    conn.executemany(
        "INSERT INTO employee_changes VALUES (?, ?, ?, ?, ?)",
        [
            (42, "Test Person", None, "2024-07-01", "New region"),
            (43, "Other Person", "Promotion", None, None),
        ],
    )
    conn.commit()
    conn.close()
    return db


def _employee_changes_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="employee_changes",
                columns=[
                    ColumnSpec(name="employee_id", type=ColumnType.integer),
                    ColumnSpec(name="name", type=ColumnType.string),
                    ColumnSpec(name="recorded_movement", type=ColumnType.string),
                    ColumnSpec(name="effective_date_of_route_change", type=ColumnType.string),
                    ColumnSpec(name="role_change", type=ColumnType.string),
                ],
            )
        ]
    )


@pytest.mark.asyncio
async def test_sibling_column_scan_recovers_after_null(tmp_path: Path):
    """Replay the corrected pattern from #163: don't stop at first NULL.

    The agent's expected sequence under the new prompt:
      1. run_select first lookup on recorded_movement → NULL row.
      2. Notices NULL + sibling columns share semantic tokens with "change".
      3. run_select all three semantically-relevant columns → finds the data.
    """
    db = _employee_changes_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_run(prompt, **kwargs):
        tools = retriever._test_tools
        # First attempt — obvious column is NULL.
        await tools["run_select"]("SELECT recorded_movement FROM employee_changes WHERE employee_id=42")
        # Second attempt — scan siblings.
        await tools["run_select"](
            "SELECT recorded_movement, effective_date_of_route_change, role_change "
            "FROM employee_changes WHERE employee_id=42"
        )
        return MagicMock(output="done")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_run)):
        outcome = await retriever.retrieve(
            "Has there been any structural change for employee 42?",
            schemas=[_employee_changes_schema()],
        )

    # The terminal outcome is the *second* run_select, which carries the data.
    assert outcome.outcome == "answered"
    assert outcome.result_markdown is not None
    assert "2024-07-01" in outcome.result_markdown
    assert "New region" in outcome.result_markdown
    # The agent's last SQL is the multi-column one.
    assert "effective_date_of_route_change" in (outcome.attempted_sql or "")
    assert "role_change" in (outcome.attempted_sql or "")
