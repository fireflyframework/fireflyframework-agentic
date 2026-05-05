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

"""Tests for ingestion domain models (records and target schema)."""

from datetime import datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fireflyframework_agentic.ingestion.domain import (
    ColumnSpec,
    ForeignKeySpec,
    IngestionError,
    IngestionResult,
    RawFile,
    TableSpec,
    TargetSchema,
    TypedRecord,
)


def test_raw_file_minimum_fields():
    f = RawFile(
        source_id="sharepoint:Sales/Q1.xlsx",
        name="Q1.xlsx",
        fetched_at=datetime(2026, 1, 1),
        local_path=Path("/tmp/cache/Q1.xlsx"),
    )
    assert f.source_id == "sharepoint:Sales/Q1.xlsx"
    assert f.size_bytes == 0
    assert f.etag == ""
    assert f.mime_type == ""


def test_typed_record_holds_table_and_row():
    r = TypedRecord(table="sales", row={"date": "2026-01-01", "units": 5})
    assert r.table == "sales"
    assert r.row["units"] == 5


def test_ingestion_error_defaults():
    e = IngestionError(kind="NoMapperFound", message="no script matches Q3.xlsx")
    assert e.file_source_id is None
    assert e.details == {}


def test_ingestion_result_aggregates_counts():
    r = IngestionResult(
        files_processed=2,
        records_written={"sales": 10, "customers": 4},
        errors=[IngestionError(kind="X", message="y")],
    )
    assert r.files_processed == 2
    assert sum(r.records_written.values()) == 14
    assert len(r.errors) == 1


def test_table_spec_rejects_duplicate_columns():
    with pytest.raises(ValidationError, match="duplicate columns"):
        TableSpec(
            name="sales",
            columns=[
                ColumnSpec(name="id", type="integer"),
                ColumnSpec(name="id", type="string"),
            ],
        )


def test_table_spec_column_lookup():
    t = TableSpec(
        name="sales",
        columns=[ColumnSpec(name="id", type="integer"), ColumnSpec(name="name", type="string")],
    )
    assert t.column("id").type == "integer"
    with pytest.raises(KeyError):
        t.column("missing")


def test_target_schema_rejects_duplicate_table_names():
    with pytest.raises(ValidationError, match="duplicate table names"):
        TargetSchema(
            tables=[
                TableSpec(name="sales", columns=[ColumnSpec(name="id", type="integer")]),
                TableSpec(name="sales", columns=[ColumnSpec(name="id", type="integer")]),
            ]
        )


def test_target_schema_rejects_fk_to_missing_table():
    with pytest.raises(ValidationError, match="target table not in schema"):
        TargetSchema(
            tables=[
                TableSpec(
                    name="sales",
                    columns=[ColumnSpec(name="customer_id", type="integer")],
                    foreign_keys=[
                        ForeignKeySpec(
                            column="customer_id",
                            references_table="customers",
                            references_column="id",
                        )
                    ],
                )
            ]
        )


def test_target_schema_rejects_fk_to_missing_target_column():
    with pytest.raises(ValidationError, match="target column not in target table"):
        TargetSchema(
            tables=[
                TableSpec(name="customers", columns=[ColumnSpec(name="id", type="integer")]),
                TableSpec(
                    name="sales",
                    columns=[ColumnSpec(name="customer_id", type="integer")],
                    foreign_keys=[
                        ForeignKeySpec(
                            column="customer_id",
                            references_table="customers",
                            references_column="missing",
                        )
                    ],
                ),
            ]
        )


def test_target_schema_rejects_fk_with_unknown_local_column():
    with pytest.raises(ValidationError, match="local column not in table"):
        TargetSchema(
            tables=[
                TableSpec(name="customers", columns=[ColumnSpec(name="id", type="integer")]),
                TableSpec(
                    name="sales",
                    columns=[ColumnSpec(name="amount", type="float")],
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


def test_target_schema_table_lookup():
    s = TargetSchema(tables=[TableSpec(name="sales", columns=[ColumnSpec(name="id", type="integer")])])
    assert s.table("sales").name == "sales"
    with pytest.raises(KeyError):
        s.table("missing")


def test_target_schema_from_yaml(tmp_path: Path):
    spec = {
        "tables": [
            {
                "name": "customers",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
                    {"name": "name", "type": "string"},
                ],
            },
            {
                "name": "sales",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
                    {"name": "customer_id", "type": "integer"},
                    {"name": "amount", "type": "float"},
                ],
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "references_table": "customers",
                        "references_column": "id",
                    }
                ],
            },
        ]
    }
    p = tmp_path / "schema.yaml"
    p.write_text(yaml.safe_dump(spec))
    schema = TargetSchema.from_yaml(p)
    assert len(schema.tables) == 2
    assert schema.table("sales").foreign_keys[0].references_table == "customers"
