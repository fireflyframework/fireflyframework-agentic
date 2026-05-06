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

"""Schema registry and schema discovery for structured ingestion.

``SchemaRegistry`` stores and retrieves ``TargetSchema`` objects in a
``_schemas`` table inside the corpus SQLite file.

``discover_schema`` uses ``create_extractor_agent`` (Claude) to infer a
``TargetSchema`` from headers and sample rows of a CSV or Excel file.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from fireflyframework_agentic.agents.templates import create_extractor_agent
from fireflyframework_agentic.rag.corpus import SqliteCorpus

from .structured_schema import TargetSchema

try:
    import openpyxl as _openpyxl

    _HAS_OPENPYXL = True
except ImportError:
    _openpyxl = None  # type: ignore[assignment]
    _HAS_OPENPYXL = False

log = logging.getLogger(__name__)

_SAMPLE_ROWS = 5

_SKILL = (
    "You are a data schema analyst. Given tabular data (headers + sample rows), "
    "infer the best relational schema.\n\n"
    "**Naming:** Use snake_case for table and column names. "
    "For CSV files: table name = filename stem in snake_case. "
    "For Excel: each sheet becomes one table; table name = sheet name in snake_case.\n\n"
    "**Type inference:**\n"
    "- Integers only → integer\n"
    "- Numbers with decimals → float\n"
    "- true/false, yes/no, 0/1 → boolean\n"
    "- ISO dates, DD/MM/YYYY, MM-DD-YYYY → date\n"
    "- Datetimes with time component → datetime\n"
    "- Structured text (JSON-like) → json\n"
    "- Everything else → string\n\n"
    "**Nullability & primary keys:**\n"
    "- nullable: false only if every sample row has a non-empty value.\n"
    "- primary_key: true if the column looks like a unique identifier "
    "(named 'id' or ending in '_id', sequential integers with no duplicates).\n"
    "- At most one primary key per table.\n\n"
    "**Multi-sheet Excel:** One TableSpec per sheet. Skip sheets where all sample rows are empty."
)

_DEFAULT_SCHEMA_MODEL = "anthropic:claude-sonnet-4-6"


class SchemaRegistry:
    """Stores and retrieves ``TargetSchema`` objects in the corpus SQLite file."""

    def __init__(self, corpus: SqliteCorpus) -> None:
        self._corpus = corpus

    async def initialise(self) -> None:
        await self._corpus.query(
            "CREATE TABLE IF NOT EXISTS _schemas (name TEXT PRIMARY KEY, schema_json TEXT NOT NULL)"
        )

    async def save(self, schema: TargetSchema) -> None:
        for table in schema.tables:
            single = TargetSchema(tables=[table])
            await self._corpus.query(
                "INSERT INTO _schemas (name, schema_json) VALUES (:name, :json) "
                "ON CONFLICT(name) DO UPDATE SET schema_json = excluded.schema_json",
                {"name": table.name, "json": single.model_dump_json()},
            )

    async def list_schemas(self) -> list[TargetSchema]:
        rows = await self._corpus.query("SELECT schema_json FROM _schemas")
        return [TargetSchema.model_validate_json(r["schema_json"]) for r in rows]


def _csv_sample(path: Path) -> str:
    with open(path, newline="") as f:
        rows = list(csv.reader(f))[: _SAMPLE_ROWS + 1]
    name = path.stem.replace(" ", "_").replace("-", "_").lower()
    lines = [f"Table: {name}", f"Headers: {rows[0]}"]
    lines += [f"  {r}" for r in rows[1:]]
    return "\n".join(lines)


def _excel_sample(path: Path) -> str:
    if not _HAS_OPENPYXL:
        raise RuntimeError("openpyxl is required for Excel files: pip install openpyxl")
    wb = _openpyxl.load_workbook(path, read_only=True, data_only=True)  # type: ignore[union-attr]
    parts: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))[: _SAMPLE_ROWS + 1]
        if not rows or all(v is None for v in rows[0]):
            continue
        name = sheet_name.replace(" ", "_").replace("-", "_").lower()
        lines = [f"Sheet (table): {name}", f"Headers: {list(rows[0])}"]
        lines += [f"  {list(r)}" for r in rows[1:]]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def discover_schema(path: Path, *, model: str = _DEFAULT_SCHEMA_MODEL) -> TargetSchema:
    """Infer a ``TargetSchema`` from *path* (CSV or Excel)."""
    agent = create_extractor_agent(
        TargetSchema,
        name="schema_discovery",
        model=model,
        extra_instructions=_SKILL,
        auto_register=False,
    )
    suffix = path.suffix.lower()
    sample = _excel_sample(path) if suffix in (".xls", ".xlsx") else _csv_sample(path)
    result = await agent.run(f"File: {path.name}\n\n{sample}")
    return result.output
