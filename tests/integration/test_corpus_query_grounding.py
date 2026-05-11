# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Regression: SQL retriever can ground itself when labels mismatch the query.

Reproduces the 'synonym + column-name overload' failure mode on a synthetic
sales fixture. Before the inspect-loop change, a question that used an
operator-shorthand label and referred to year-prefix columns would generate
a SELECT that ran cleanly but matched 0 rows. After the change, the agent
inspects the columns first and finds the canonical values.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.sql import StructuredRetriever


def _grounding_fixture(tmp_path: Path) -> tuple[Path, TargetSchema]:
    """A schema with two failure shapes baked in.

    - ``product_name`` contains ``'MX-3000 Wireless Mouse'``, not ``'wireless
      mouse'`` (so a naive LIKE ``'%wireless mouse%'`` filter would miss).
    - ``period`` is TEXT (``'2025-Q4'``), ``period_revenue`` is REAL
      (``4200.0``). The column names overlap, so a thin-context LLM is liable
      to filter on ``period_revenue = 2025`` and find nothing.
    """
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sales (period TEXT, region TEXT, product_name TEXT, revenue REAL, period_revenue REAL)")
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?, ?, ?, ?)",
        [
            ("2025-Q4", "EU-North", "MX-3000 Wireless Mouse", 1200.0, 4200.0),
            ("2025-Q4", "EU-South", "MX-3000 Wireless Mouse", 800.0, 4200.0),
            ("2025-Q4", "EU-South", "K10 Keyboard", 600.0, 4200.0),
            ("2025-Q3", "NA", "MX-3000 Wireless Mouse", 950.0, 3100.0),
        ],
    )
    conn.commit()
    conn.close()
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="period", type=ColumnType.string),
                    ColumnSpec(name="region", type=ColumnType.string),
                    ColumnSpec(name="product_name", type=ColumnType.string),
                    ColumnSpec(name="revenue", type=ColumnType.float_),
                    ColumnSpec(name="period_revenue", type=ColumnType.float_),
                ],
            )
        ]
    )
    return db, schema


@pytest.mark.asyncio
async def test_inspect_loop_recovers_from_synonym_and_overload(tmp_path: Path):
    """End-to-end on the fixture: agent inspects, finds canonical values, runs the right SELECT."""
    db, schema = _grounding_fixture(tmp_path)
    retriever = StructuredRetriever(db)

    # Replay the agent's tool-call sequence deterministically. This is the
    # pattern a correctly-functioning Haiku agent would follow on this
    # fixture: probe the ambiguous columns, then run the disambiguated SELECT.
    async def replay(prompt, **kwargs):
        tools = retriever._test_tools
        # 1. The agent doesn't know what product_name values exist — probe.
        await tools["inspect_table"]("sales", "product_name", "distinct_values")
        # 2. period column is text — probe its format.
        await tools["inspect_table"]("sales", "period", "distinct_values")
        # 3. region prefix is unclear — probe.
        await tools["inspect_table"]("sales", "region", "distinct_values")
        # 4. Final SELECT using the correct column (revenue, not period_revenue)
        #    and the canonical product name found via inspection.
        await tools["run_select"](
            "SELECT product_name, SUM(revenue) FROM sales "
            "WHERE period='2025-Q4' AND region LIKE 'EU-%' "
            "AND product_name LIKE '%Wireless Mouse%' "
            "GROUP BY product_name"
        )
        return type("R", (), {"output": "done"})()

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=replay)):
        outcome = await retriever.retrieve("wireless mouse revenue in Europe last quarter", schemas=[schema])

    assert outcome.outcome == "answered", (
        f"expected 'answered' but got {outcome.outcome}; "
        f"attempted={outcome.attempted_sql}; probes={len(outcome.probe_trail)}"
    )
    assert outcome.result_markdown is not None
    assert "MX-3000 Wireless Mouse" in outcome.result_markdown
    # Combined revenue for EU regions in 2025-Q4 is 2000.0 (1200 + 800).
    assert "2000" in outcome.result_markdown
    # The trail records the three probes we drove.
    assert {p.column for p in outcome.probe_trail} == {"product_name", "period", "region"}


@pytest.mark.asyncio
async def test_inspect_loop_reports_empty_when_data_truly_absent(tmp_path: Path):
    """A query for data the corpus doesn't contain produces outcome='empty', not 'unsupported'."""
    db, schema = _grounding_fixture(tmp_path)
    retriever = StructuredRetriever(db)

    async def replay(prompt, **kwargs):
        tools = retriever._test_tools
        await tools["inspect_table"]("sales", "region", "distinct_values")
        await tools["run_select"]("SELECT * FROM sales WHERE region='Antarctica'")
        return type("R", (), {"output": "no rows"})()

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=replay)):
        outcome = await retriever.retrieve("Antarctica sales last quarter", schemas=[schema])

    assert outcome.outcome == "empty"
    assert outcome.attempted_sql == "SELECT * FROM sales WHERE region='Antarctica'"
    assert len(outcome.probe_trail) == 1
