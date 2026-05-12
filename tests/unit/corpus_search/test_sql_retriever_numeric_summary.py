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

"""Tests for the ``numeric_summary`` inspect_table op.

Reproduces and fixes a class of analytical errors where the SQL agent
averaged a numeric column whose source spreadsheet used blank cells to
mean "zero". SQLite ``AVG()`` excludes NULLs, so the reported mean was
the mean of the non-blank rows rather than the mean of the full
population. The new op exposes both interpretations so the agent (or a
caller in tests) can choose the right one.

All test fixtures use synthetic data — no values are taken from any
real corpus.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.sql import (
    _build_inspect_tool,
    _LoopContext,
)


def _synthetic_field_days_db(tmp_path: Path) -> Path:
    """Build a fictional ``team_days`` table with the JP14 shape.

    Eighteen synthetic reps. Six have non-zero ``time_off_days`` recorded;
    twelve are *blank* in the source spreadsheet — the data-entry
    convention is "blank means zero days off". When that arrives in
    SQLite the blanks become NULL.

    With blanks-as-NULL:
      ``AVG(time_off_days)`` = mean over 6 rows = 4.0
    With blanks-as-zero (the convention the analysts use):
      ``SUM(time_off_days) / COUNT(*)`` = 24 / 18 ≈ 1.333

    The exact 4.0 vs 1.333 split mirrors the discrepancy the reviewer
    flagged, but the values themselves are invented for this test.
    """
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE team_days (rep_id INTEGER, time_off_days INTEGER)")
    # Six non-blank rows summing to 24.
    nonblank = [(1, 2), (2, 4), (3, 1), (4, 8), (5, 6), (6, 3)]
    # Twelve blank rows — modelled as NULL the way openpyxl + ingest produce.
    blanks = [(rid, None) for rid in range(7, 19)]
    conn.executemany("INSERT INTO team_days VALUES (?, ?)", nonblank + blanks)
    conn.commit()
    conn.close()
    return db


def _schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="team_days",
                columns=[
                    ColumnSpec(name="rep_id", type=ColumnType.integer),
                    ColumnSpec(name="time_off_days", type=ColumnType.integer),
                ],
            )
        ]
    )


def test_baseline_avg_excludes_blanks_documenting_the_bug(tmp_path: Path):
    """Lock in SQLite's native ``AVG`` semantics so we know what we're fixing.

    This is the surface a naive LLM-authored SELECT hits today: the
    agent writes ``AVG(time_off_days)``, SQLite excludes NULLs, and the
    answer is computed off a smaller denominator than the analyst
    intended. The test documents that this is *expected SQL behaviour*,
    not a bug in our code — the fix lives in giving the agent a
    diagnostic so it knows when to override it.
    """
    db = _synthetic_field_days_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        avg_excluding_blanks = conn.execute("SELECT AVG(time_off_days) FROM team_days").fetchone()[0]
        avg_blanks_as_zero = conn.execute("SELECT AVG(COALESCE(time_off_days, 0)) FROM team_days").fetchone()[0]
    finally:
        conn.close()
    assert avg_excluding_blanks == pytest.approx(4.0)
    assert avg_blanks_as_zero == pytest.approx(24 / 18)
    # The two means differ; that gap is exactly what the new op surfaces.
    assert avg_excluding_blanks != pytest.approx(avg_blanks_as_zero)


@pytest.mark.asyncio
async def test_numeric_summary_exposes_null_counts_and_both_means(tmp_path: Path):
    """The op must return both AVG variants so the agent can pick.

    Asserts the exact counts and means produced by the synthetic dataset:
    18 total rows, 6 non-null, 12 null, mean-excluding-null 4.0, mean
    with blanks coerced to zero 24/18.
    """
    ctx = _LoopContext(db_path=_synthetic_field_days_db(tmp_path), schemas=[_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("team_days", "time_off_days", "numeric_summary")
    assert "rows=18" in result
    assert "non_null=6" in result
    assert "nulls=12" in result
    assert "sum=24" in result
    assert "mean_excluding_nulls=4.0" in result
    # 24/18 ≈ 1.3333... — format with enough precision that the assertion
    # is robust to representation but still pinned to the correct value.
    assert "mean_blanks_as_zero=1.333" in result
    # And a probe-trail entry was recorded for observability parity with
    # the other ops.
    assert len(ctx.probe_trail) == 1
    assert ctx.probe_trail[0].op == "numeric_summary"


@pytest.mark.asyncio
async def test_numeric_summary_handles_all_null_column_without_crashing(tmp_path: Path):
    """Edge case: a column whose every row is blank.

    With every cell NULL, ``mean_excluding_nulls`` is undefined and
    ``mean_blanks_as_zero`` is 0. The op should report this cleanly
    rather than crashing on a division-by-zero or returning a confusing
    NULL string.
    """
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE team_days (rep_id INTEGER, time_off_days INTEGER)")
    conn.executemany(
        "INSERT INTO team_days VALUES (?, ?)",
        [(rid, None) for rid in range(1, 6)],
    )
    conn.commit()
    conn.close()
    ctx = _LoopContext(db_path=db, schemas=[_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("team_days", "time_off_days", "numeric_summary")
    assert "rows=5" in result
    assert "non_null=0" in result
    assert "nulls=5" in result
    assert "mean_excluding_nulls=undefined" in result
    assert "mean_blanks_as_zero=0.0" in result


@pytest.mark.asyncio
async def test_numeric_summary_rejects_unknown_column(tmp_path: Path):
    """Same allow-list guard as the existing ops — typos must surface
    as a ModelRetry so the LLM can recover, not as a SQL error."""
    from pydantic_ai.exceptions import ModelRetry

    ctx = _LoopContext(db_path=_synthetic_field_days_db(tmp_path), schemas=[_schema()])
    inspect = _build_inspect_tool(ctx)
    with pytest.raises(ModelRetry, match="column 'phantom' not in"):
        await inspect("team_days", "phantom", "numeric_summary")
