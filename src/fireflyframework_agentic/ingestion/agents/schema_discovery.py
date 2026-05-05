# Copyright 2026 Firefly Software Solutions Inc
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

"""Schema discovery agent: infers a TargetSchema from a tabular file using Claude."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import openpyxl
from pydantic_ai import Agent

from fireflyframework_agentic.ingestion.domain.schema import TargetSchema

_SAMPLE_ROWS = 5
_agent: Agent[None, TargetSchema] | None = None


def _get_agent() -> Agent[None, TargetSchema]:
    global _agent
    if _agent is None:
        _agent = Agent(
            "anthropic:claude-sonnet-4-6",
            output_type=TargetSchema,
            system_prompt=(
                "You are a data engineer. Given a sample of tabular data, infer a TargetSchema "
                "with appropriate column names, types (string/integer/float/boolean/date/datetime/json), "
                "nullability, and a primary key. Use snake_case for the table name derived from the "
                "file name (without extension). Choose the most specific type that fits the sample values."
            ),
        )
    return _agent


def _read_sample(path: Path) -> tuple[list[str], list[list[Any]]]:
    """Read headers and up to _SAMPLE_ROWS sample rows from an Excel or CSV file."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            headers = next(reader, [])
            rows = [row for _, row in zip(range(_SAMPLE_ROWS), reader, strict=False)]
        return headers, rows
    if suffix in (".xlsx", ".xlsm"):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True)) if ws is not None else []
        wb.close()
        if not all_rows:
            return [], []
        headers = [str(c) if c is not None else "" for c in all_rows[0]]
        rows = [[str(c) if c is not None else "" for c in r] for r in all_rows[1 : _SAMPLE_ROWS + 1]]
        return headers, rows
    raise ValueError(f"Unsupported file type for schema discovery: {suffix!r}")


async def discover_schema(path: Path) -> TargetSchema:
    """Analyse a tabular file and return an inferred TargetSchema.

    Reads up to _SAMPLE_ROWS rows and calls Claude to infer column types.
    Requires ANTHROPIC_API_KEY in environment.
    """
    headers, rows = _read_sample(path)
    table_name = path.stem.lower().replace(" ", "_").replace("-", "_")
    sample_lines = ", ".join(headers)
    if rows:
        sample_lines += "\nSample rows:\n" + "\n".join(str(r) for r in rows)
    prompt = f"File: {path.name}\nTable name to use: {table_name}\nHeaders and sample:\n{sample_lines}"
    result = await _get_agent().run(prompt)
    return result.output
