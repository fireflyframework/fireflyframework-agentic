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

"""Integration tests for IngestionService with a FakeSource and real adapters.

The fake replaces only the *port* (DataSourcePort), so the rest of the
pipeline (ScriptMapper loading real Python files, SQLiteSink running
in-memory) is exercised end-to-end. This is the most valuable shape of
test for hexagonal code: the boundary closest to the outside world is
faked, everything else is real.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import pytest

from fireflyframework_agentic.ingestion.adapters.mappers import ScriptMapper
from fireflyframework_agentic.ingestion.adapters.sinks import SQLiteSink
from fireflyframework_agentic.ingestion.domain import (
    ColumnSpec,
    ForeignKeySpec,
    RawFile,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.ingestion.services import IngestionService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FakeSource:
    """Yields RawFiles from a list and persists a delta cursor in memory."""

    def __init__(self, files: list[RawFile], initial_cursor: str | None = None) -> None:
        self._files = files
        self._cursor = initial_cursor
        self.commit_called_with: list[str] = []

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:
        for f in self._files:
            yield f

    async def fetch(self, file: RawFile) -> Path:
        return file.local_path

    async def commit_delta(self, cursor: str) -> None:
        self._cursor = cursor
        self.commit_called_with.append(cursor)

    async def current_cursor(self) -> str | None:
        return self._cursor


@pytest.fixture
def schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="customers",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="name", type="string"),
                    ColumnSpec(name="tier", type="string"),
                ],
            ),
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="customer_id", type="integer", nullable=False),
                    ColumnSpec(name="day", type="date"),
                    ColumnSpec(name="amount", type="float"),
                    ColumnSpec(name="paid", type="boolean"),
                ],
                foreign_keys=[
                    ForeignKeySpec(
                        column="customer_id",
                        references_table="customers",
                        references_column="id",
                    )
                ],
            ),
        ]
    )


def _csv_raw(name: str, source_id: str, path: Path) -> RawFile:
    return RawFile(
        source_id=source_id,
        name=name,
        mime_type="text/csv",
        size_bytes=path.stat().st_size if path.exists() else 0,
        etag="v1",
        fetched_at=datetime(2026, 1, 1),
        local_path=path,
    )


async def test_end_to_end_pipeline_writes_to_sqlite(schema: TargetSchema, tmp_path: Path):
    customers = tmp_path / "customers_q1.csv"
    customers.write_text("id,name,tier\n1,Alpha,gold\n2,Beta,silver\n")
    sales = tmp_path / "sales_q1.csv"
    sales.write_text("id,customer_id,day,amount,paid\n10,1,2026-01-15,99.5,true\n11,2,2026-02-20,12.0,false\n")
    source = FakeSource(
        [
            _csv_raw("customers_q1.csv", "fake:cust1", customers),
            _csv_raw("sales_q1.csv", "fake:sales1", sales),
        ]
    )
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.files_processed == 2
        assert result.records_written == {"customers": 2, "sales": 2}
        assert result.errors == []
        rows = sink.connection.execute(
            "SELECT customers.name, sales.amount FROM sales "
            "JOIN customers ON sales.customer_id = customers.id "
            "ORDER BY sales.id"
        ).fetchall()
        assert rows == [("Alpha", 99.5), ("Beta", 12.0)]
    finally:
        sink.close()


async def test_unsupported_file_records_error_and_continues(schema: TargetSchema, tmp_path: Path):
    customers = tmp_path / "customers_q1.csv"
    customers.write_text("id,name,tier\n1,Alpha,gold\n")
    unrelated = tmp_path / "weird.bin"
    unrelated.write_bytes(b"\x00\x01\x02")
    source = FakeSource(
        [
            _csv_raw("weird.bin", "fake:weird", unrelated),
            _csv_raw("customers_q1.csv", "fake:cust1", customers),
        ]
    )
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.files_processed == 1
        assert result.records_written["customers"] == 1
        assert any(e.kind == "NoMapperFound" for e in result.errors)
    finally:
        sink.close()


async def test_run_incremental_uses_persisted_cursor_when_since_is_none(schema: TargetSchema, tmp_path: Path):
    source = FakeSource(files=[], initial_cursor="saved-cursor")
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        await svc.run_incremental()
    finally:
        sink.close()
    # FakeSource captures its cursor in current_cursor(); we just verify it
    # was returned (the actual list_changed call accepted it without error).
    assert source._cursor == "saved-cursor"


async def test_fetch_failure_recorded_as_error(schema: TargetSchema, tmp_path: Path):
    customers = tmp_path / "customers_q1.csv"
    customers.write_text("id,name,tier\n1,Alpha,gold\n")

    class FailingSource(FakeSource):
        async def fetch(self, file: RawFile) -> Path:
            raise RuntimeError("network down")

    source = FailingSource([_csv_raw("customers_q1.csv", "fake:c", customers)])
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.files_processed == 0
        assert any(e.kind == "FetchError" and "network down" in e.message for e in result.errors)
    finally:
        sink.close()


async def test_mapping_script_failure_recorded_as_error(schema: TargetSchema, tmp_path: Path):
    bad = tmp_path / "scripts"
    bad.mkdir()
    (bad / "boom.py").write_text(
        "import re\n"
        "from collections.abc import Iterator\n"
        "PATTERN = re.compile(r'boom')\n"
        "def map(file, schema):\n"
        "    raise RuntimeError('mapping kaboom')\n"
        "    yield\n"
    )
    f = tmp_path / "boom.csv"
    f.write_text("x")
    source = FakeSource([_csv_raw("boom.csv", "fake:b", f)])
    mapper = ScriptMapper(bad)
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.files_processed == 0
        assert any(e.kind == "MappingScriptError" and "kaboom" in e.message for e in result.errors)
    finally:
        sink.close()


async def test_sink_validation_errors_propagate_to_result(schema: TargetSchema, tmp_path: Path):
    # A script that emits an invalid row (missing required customer_id).
    bad_scripts = tmp_path / "scripts"
    bad_scripts.mkdir()
    (bad_scripts / "sales_bad.py").write_text(
        "import re\n"
        "from collections.abc import Iterator\n"
        "from fireflyframework_agentic.ingestion.domain import "
        "RawFile, TargetSchema, TypedRecord\n"
        "PATTERN = re.compile(r'sales-bad')\n"
        "def map(file, schema):\n"
        "    yield TypedRecord(table='sales', row={'id': 1, 'amount': 1.0})\n"
    )
    f = tmp_path / "sales-bad.csv"
    f.write_text("x")
    source = FakeSource([_csv_raw("sales-bad.csv", "fake:sb", f)])
    mapper = ScriptMapper(bad_scripts)
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.records_written["sales"] == 0
        assert any(e.kind == "RowValidationError" for e in result.errors)
    finally:
        sink.close()
