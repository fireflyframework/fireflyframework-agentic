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

"""Tests for SQLiteSink against a real in-memory SQLite instance."""

import json
import sqlite3
from datetime import date

import pytest

from fireflyframework_agentic.ingestion.adapters.sinks import SQLiteSink
from fireflyframework_agentic.ingestion.domain import (
    ColumnSpec,
    ForeignKeySpec,
    TableSpec,
    TargetSchema,
    TypedRecord,
)


@pytest.fixture
def sales_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="customers",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="name", type="string"),
                    ColumnSpec(
                        name="tier",
                        type="string",
                        enum_values=["bronze", "silver", "gold"],
                    ),
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


@pytest.fixture
def sink() -> SQLiteSink:
    s = SQLiteSink()
    yield s
    s.close()


def test_begin_creates_tables(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    rows = sink.connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    assert [r[0] for r in rows] == ["customers", "sales"]


def test_begin_is_idempotent(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write([TypedRecord(table="customers", row={"id": 1, "name": "A", "tier": "gold"})])
    sink.begin(sales_schema)  # second begin must drop & recreate
    counts = sink.finalize()
    assert counts == {"customers": 0, "sales": 0}


def test_write_inserts_valid_rows(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write(
        [
            TypedRecord(table="customers", row={"id": 1, "name": "Alpha", "tier": "gold"}),
            TypedRecord(table="customers", row={"id": 2, "name": "Beta", "tier": "silver"}),
            TypedRecord(
                table="sales",
                row={
                    "id": 100,
                    "customer_id": 1,
                    "day": date(2026, 1, 5),
                    "amount": 99.95,
                    "paid": True,
                },
            ),
        ]
    )
    counts = sink.finalize()
    assert counts == {"customers": 2, "sales": 1}
    rows = sink.connection.execute("SELECT id, name, tier FROM customers ORDER BY id").fetchall()
    assert rows == [(1, "Alpha", "gold"), (2, "Beta", "silver")]


def test_write_skips_row_with_unknown_table(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write([TypedRecord(table="ghost", row={"id": 1})])
    assert sink.finalize() == {"customers": 0, "sales": 0}
    assert any(e.kind == "UnknownTable" for e in sink.validation_errors)


def test_write_skips_row_with_missing_required_column(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write([TypedRecord(table="sales", row={"id": 1, "day": date(2026, 1, 1)})])  # missing customer_id
    assert sink.finalize() == {"customers": 0, "sales": 0}
    err = sink.validation_errors[0]
    assert err.kind == "RowValidationError"
    assert "customer_id" in err.message


def test_write_skips_row_with_unknown_column(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write(
        [
            TypedRecord(
                table="customers",
                row={"id": 1, "name": "A", "tier": "gold", "extra": "x"},
            )
        ]
    )
    assert sink.finalize()["customers"] == 0
    assert any(e.kind == "RowValidationError" and "unknown columns" in e.message for e in sink.validation_errors)


def test_write_skips_row_outside_enum(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write([TypedRecord(table="customers", row={"id": 1, "name": "A", "tier": "platinum"})])
    assert sink.finalize()["customers"] == 0
    assert any(e.kind == "RowValidationError" and "enum" in e.message for e in sink.validation_errors)


def test_coerces_string_date_to_iso_text(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write(
        [
            TypedRecord(table="customers", row={"id": 1, "name": "A", "tier": "gold"}),
            TypedRecord(
                table="sales",
                row={
                    "id": 1,
                    "customer_id": 1,
                    "day": "2026-04-15",
                    "amount": 1.0,
                    "paid": True,
                },
            ),
        ]
    )
    rows = sink.connection.execute("SELECT day FROM sales").fetchall()
    assert rows[0][0] == "2026-04-15"


def test_coerces_string_boolean(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write(
        [
            TypedRecord(table="customers", row={"id": 1, "name": "A", "tier": "gold"}),
            TypedRecord(
                table="sales",
                row={
                    "id": 1,
                    "customer_id": 1,
                    "day": "2026-04-15",
                    "amount": 1.0,
                    "paid": "yes",
                },
            ),
        ]
    )
    rows = sink.connection.execute("SELECT paid FROM sales").fetchall()
    assert rows[0][0] == 1


def test_rejects_bool_for_integer_column(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write([TypedRecord(table="customers", row={"id": True, "name": "A", "tier": "gold"})])
    assert sink.finalize()["customers"] == 0


def test_finalize_returns_per_table_counts(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    sink.write(
        [
            TypedRecord(table="customers", row={"id": 1, "name": "A", "tier": "gold"}),
            TypedRecord(table="customers", row={"id": 2, "name": "B", "tier": "silver"}),
        ]
    )
    assert sink.finalize() == {"customers": 2, "sales": 0}


def test_json_column_serialized_as_text():
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="events",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="payload", type="json"),
                ],
            )
        ]
    )
    sink = SQLiteSink()
    try:
        sink.begin(schema)
        sink.write([TypedRecord(table="events", row={"id": 1, "payload": {"k": [1, 2, 3]}})])
        rows = sink.connection.execute("SELECT id, payload FROM events").fetchall()
        assert rows == [(1, json.dumps({"k": [1, 2, 3]}))]
    finally:
        sink.close()


def test_unsafe_table_name_rejected_at_begin():
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="users; DROP TABLE other",
                columns=[ColumnSpec(name="id", type="integer", primary_key=True, nullable=False)],
            )
        ]
    )
    sink = SQLiteSink()
    try:
        with pytest.raises(ValueError, match="Unsafe SQL identifier"):
            sink.begin(schema)
    finally:
        sink.close()


def test_foreign_key_constraint_enforced(sink: SQLiteSink, sales_schema: TargetSchema):
    sink.begin(sales_schema)
    # Insert a sale whose customer_id has no matching customer row.
    with pytest.raises(sqlite3.IntegrityError):
        sink.write(
            [
                TypedRecord(
                    table="sales",
                    row={
                        "id": 1,
                        "customer_id": 999,
                        "day": date(2026, 1, 1),
                        "amount": 1.0,
                        "paid": True,
                    },
                )
            ]
        )


def test_persists_to_disk(tmp_path):
    db = tmp_path / "test.sqlite"
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="t",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="v", type="string"),
                ],
            )
        ]
    )
    sink = SQLiteSink(str(db))
    try:
        sink.begin(schema)
        sink.write([TypedRecord(table="t", row={"id": 1, "v": "hello"})])
        sink.finalize()
    finally:
        sink.close()

    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT id, v FROM t").fetchall()
    conn.close()
    assert rows == [(1, "hello")]
