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
from pathlib import Path

from pydantic import BaseModel

from fireflyframework_agentic.agents.templates import create_extractor_agent
from fireflyframework_agentic.rag.ingest.structured_schema import TargetSchema

log = logging.getLogger(__name__)

_SYSTEM = """\
You generate a single SQLite SELECT statement to answer the user's question.
Rules:
- Output ONLY the SQL — no explanation, no markdown.
- Use only SELECT (no INSERT/UPDATE/DELETE/DROP/ALTER).
- Use the exact table and column names provided.
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
        schema_context = _build_schema_context(schemas)
        prompt = f"{schema_context}\n\nQuestion: {question}"
        try:
            result = await self._sql_agent.run(prompt)
            sql = result.output.sql.strip()
        except Exception as exc:
            log.warning("SQL generation failed: %s", exc)
            return None
        if not re.match(r"(?i)^\s*SELECT\b", sql):
            log.warning("rejected non-SELECT SQL: %.120s", sql)
            return None
        return _execute(self._db_path, sql)


def _build_schema_context(schemas: list[TargetSchema]) -> str:
    lines: list[str] = ["Available tables:"]
    for schema in schemas:
        for table in schema.tables:
            col_descs = ", ".join(f"{c.name} ({c.type.value})" for c in table.columns)
            lines.append(f"- {table.name}: {col_descs}")
    return "\n".join(lines)


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
