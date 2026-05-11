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
from typing import Literal

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
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            col_names = [d[0] for d in cur.description] if cur.description else []
    except sqlite3.Error as exc:
        log.warning("SQL execution failed: %s", exc)
        return None
    if not rows:
        return None
    header = " | ".join(col_names)
    sep = " | ".join("---" for _ in col_names)
    body = "\n".join(" | ".join(str(v) for v in row) for row in rows)
    return f"{header}\n{sep}\n{body}"
