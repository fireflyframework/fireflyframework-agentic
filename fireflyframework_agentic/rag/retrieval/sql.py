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

"""Text-to-SQL retriever for structured data ingested into corpus.sqlite."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from fireflyframework_agentic.agents.templates import create_extractor_agent
from fireflyframework_agentic.rag.ingest.structured_schema import TargetSchema

log = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ProbeRecord:
    """Record of a single ``inspect_table`` tool call.

    ``result`` is the markdown string the tool returned to the LLM, truncated
    to ~500 chars to keep observability payloads bounded.
    """

    table: str
    column: str
    op: str
    result: str


@dataclass(slots=True, frozen=True)
class SqlRetrievalOutcome:
    """Structured result of running the agentic SQL retrieval loop.

    States:
      - ``answered``: ``run_select`` returned >=1 row. ``result_markdown`` is
        the markdown table; ``attempted_sql`` is the SELECT that produced it.
      - ``empty``: ``run_select`` ran cleanly but returned 0 rows on the last
        attempt. ``result_markdown=None``; ``attempted_sql`` is the last
        SELECT; ``probe_trail`` records what the LLM inspected.
      - ``unsupported``: cap exhausted, sentinel ``SELECT 1 WHERE 1=0``, every
        attempt errored, or ``schemas`` was empty.
    """

    outcome: Literal["answered", "empty", "unsupported"]
    result_markdown: str | None
    attempted_sql: str | None
    probe_trail: list[ProbeRecord] = field(default_factory=list)


MAX_ROWS_IN_RESULT = 100
MAX_ROWS_PER_PROBE = 20


@dataclass(slots=True)
class _LoopContext:
    """Mutable per-query state shared between the loop tools.

    Built fresh on each :meth:`StructuredRetriever.retrieve` call. Tools close
    over this object; the loop driver reads its final state to build the
    :class:`SqlRetrievalOutcome`.
    """

    db_path: Path
    schemas: list[TargetSchema]
    probe_trail: list[ProbeRecord] = field(default_factory=list)
    attempted_sql: str | None = None
    last_result_markdown: str | None = None
    last_result_was_empty: bool = False
    last_result_was_sentinel: bool = False
    run_select_call_count: int = 0


_SENTINEL_SQL_PATTERN = re.compile(r"^\s*SELECT\s+1\s+WHERE\s+1\s*=\s*0\s*;?\s*$", re.IGNORECASE)


def _allowed_columns(schemas: list[TargetSchema]) -> dict[str, set[str]]:
    """Build a {table_name: {column_names}} allow-list from the registered schemas."""
    allowed: dict[str, set[str]] = {}
    for schema in schemas:
        for table in schema.tables:
            allowed[table.name] = {c.name for c in table.columns}
    return allowed


def _build_inspect_tool(ctx: _LoopContext) -> Any:
    """Return an async ``inspect_table(table, column, op)`` tool bound to *ctx*.

    The tool runs parametric SQL — table/column are validated against the
    schema allow-list and quoted; ``op`` selects one of four fixed queries.
    The LLM never composes SQL at inspect time, so injection risk is zero
    by construction.
    """

    allowed = _allowed_columns(ctx.schemas)

    async def inspect_table(
        table: str,
        column: str,
        op: Literal["distinct_values", "count", "sample_rows", "value_range"],
    ) -> str:
        """Peek at the corpus DB before composing the final SELECT.

        Ops:
          - ``distinct_values``: up to MAX_ROWS_PER_PROBE distinct values of *column*
          - ``count``: COUNT(*) of *table*
          - ``sample_rows``: first 5 rows of *table*
          - ``value_range``: MIN/MAX of *column*

        Raises ValueError if *table* or *column* is not in the registered
        schemas (this is surfaced back to the LLM as a tool error).
        """
        if table not in allowed:
            raise ValueError(f"table '{table}' not in registered schemas; available tables: {sorted(allowed)}")
        cols = allowed[table]
        if op != "count" and column not in cols:
            raise ValueError(f"column '{column}' not in '{table}'; available: {sorted(cols)}")
        # Identifier quoting: sqlite uses "..." for identifiers; double up any
        # embedded quote chars. Allow-list already gates non-existent names,
        # so this is belt-and-braces.
        t = '"' + table.replace('"', '""') + '"'
        c = '"' + column.replace('"', '""') + '"'
        if op == "distinct_values":
            sql = f"SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL LIMIT {MAX_ROWS_PER_PROBE}"
        elif op == "count":
            sql = f"SELECT COUNT(*) FROM {t}"
        elif op == "sample_rows":
            sql = f"SELECT * FROM {t} LIMIT 5"
        elif op == "value_range":
            sql = f"SELECT MIN({c}), MAX({c}) FROM {t}"
        else:
            raise ValueError(f"unknown op '{op}'")
        result = _execute(ctx.db_path, sql) or "(no rows)"
        ctx.probe_trail.append(ProbeRecord(table=table, column=column, op=op, result=result[:500]))
        return result

    return inspect_table


def _build_run_select_tool(ctx: _LoopContext) -> Any:
    """Return an async ``run_select(sql)`` tool bound to *ctx*.

    Each call updates ``ctx.attempted_sql`` and ``ctx.last_result_*`` so the
    loop driver can read the terminal state when the agent stops.
    """

    async def run_select(sql: str) -> str:
        """Execute the final SELECT statement against the corpus DB.

        - Must start with SELECT (case-insensitive, leading whitespace
          allowed). Returns ``'SQL must start with SELECT.'`` on violation —
          the LLM can revise and retry.
        - Returns ``'SQL error: ...'`` on sqlite3 errors so the LLM can self-
          correct (the loop is not terminated on a single error).
        - Returns ``'Query returned 0 rows.'`` on a clean run with no matches —
          this marks the outcome as 'empty' if it's the last SELECT.
        - Otherwise returns a markdown table, capped at MAX_ROWS_IN_RESULT.
        """
        ctx.attempted_sql = sql
        ctx.run_select_call_count += 1
        # Reset per-call flags so the *last* run_select determines the outcome.
        ctx.last_result_was_empty = False
        ctx.last_result_was_sentinel = False
        ctx.last_result_markdown = None
        if _SENTINEL_SQL_PATTERN.match(sql):
            ctx.last_result_was_sentinel = True
            return "Acknowledged: no answer is possible from this schema."
        if not re.match(r"(?i)^\s*SELECT\b", sql):
            return "SQL must start with SELECT. Other statements are not allowed."
        result = _execute(ctx.db_path, sql)
        if result is None:
            ctx.last_result_was_empty = True
            return "Query returned 0 rows."
        if result.startswith("SQL error:"):
            # Don't store as result; let the LLM retry.
            return result
        ctx.last_result_markdown = result
        return result

    return run_select


_SYSTEM = """\
You generate a single SQLite SELECT statement to answer the user's question.
Rules:
- Output ONLY the SQL — no explanation, no markdown.
- Use only SELECT (no INSERT/UPDATE/DELETE/DROP/ALTER).
- Use the exact table and column names provided.
- When filtering a text column, use LIKE with % wildcards (e.g. WHERE line_item LIKE '%Total Revenue%') \
unless you can see the exact value in the sample rows.
- If the question cannot be answered from the schema, output: SELECT 1 WHERE 1=0
"""


class SQLQuery(BaseModel):
    sql: str


_DEFAULT_SQL_MODEL = "anthropic:claude-haiku-4-5-20251001"


class StructuredRetriever:
    def __init__(self, db_path: Path, *, sql_model: str = _DEFAULT_SQL_MODEL) -> None:
        self._db_path = db_path
        self._sql_agent = create_extractor_agent(
            SQLQuery,
            name="text_to_sql",
            model=sql_model,
            extra_instructions=_SYSTEM,
            auto_register=False,
        )

    async def retrieve(
        self,
        question: str,
        schemas: list[TargetSchema],
    ) -> str | None:
        """Return a markdown table of SQL results, or None on failure/empty schemas."""
        if not schemas:
            return None
        schema_context = _build_schema_context(schemas, db_path=self._db_path)
        prompt = f"{schema_context}\n\nQuestion: {question}"
        try:
            result = await self._sql_agent.run(prompt)
            sql = result.output.sql.strip()
        except Exception as exc:
            log.warning("SQL generation failed: %s", exc)
            return None
        log.debug("generated SQL: %s", sql)
        if not re.match(r"(?i)^\s*SELECT\b", sql):
            log.warning("rejected non-SELECT SQL: %.120s", sql)
            return None
        query_result = _execute(self._db_path, sql)
        log.debug("SQL result: %s", query_result[:200] if query_result else None)
        return query_result


def _build_schema_context(schemas: list[TargetSchema], db_path: Path | None = None) -> str:
    lines: list[str] = ["Available tables:"]
    for schema in schemas:
        for table in schema.tables:
            col_descs = ", ".join(f"{c.name} ({c.type.value})" for c in table.columns)
            lines.append(f"- {table.name}: {col_descs}")
            if db_path is not None:
                # Include sample values for the first string column so the LLM
                # knows which label values exist and can filter accurately.
                first_str_col = next((c.name for c in table.columns if c.type.value == "string"), None)
                if first_str_col:
                    samples = _sample_values(db_path, table.name, first_str_col)
                    if samples:
                        lines.append(f"  sample {first_str_col} values: {samples}")
    return "\n".join(lines)


def _sample_values(db_path: Path, table: str, column: str, limit: int = 8) -> list[str]:
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT {limit}'
            ).fetchall()
        return [str(r[0]) for r in rows]
    except sqlite3.Error:
        return []


def _execute(db_path: Path, sql: str) -> str | None:
    """Execute *sql* and return a markdown table.

    Returns:
      - markdown table (possibly with a truncation footer) on success with rows
      - None if the SELECT ran successfully but matched 0 rows
      - a human-readable message starting with ``SQL error:`` on failure

    The 'error string vs None vs table' distinction lets the caller decide what
    state to record on the outcome: an error means the LLM should retry; None
    means the caller marks ``outcome='empty'``; a table means ``outcome=
    'answered'``.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            col_names = [d[0] for d in cur.description] if cur.description else []
    except sqlite3.Error as exc:
        log.warning("SQL execution failed: %s", exc)
        return f"SQL error: {exc}"
    if not rows:
        return None
    truncated_count = max(0, len(rows) - MAX_ROWS_IN_RESULT)
    kept = rows[:MAX_ROWS_IN_RESULT]
    header = " | ".join(col_names)
    sep = " | ".join("---" for _ in col_names)
    body = "\n".join(" | ".join(str(v) for v in row) for row in kept)
    table = f"{header}\n{sep}\n{body}"
    if truncated_count:
        table += f"\n(+{truncated_count} more rows; result capped at {MAX_ROWS_IN_RESULT})"
    return table
