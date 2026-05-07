import csv
import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.rag.ingest.structured_pipeline import ingest_structured
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)


def _schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="products",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="name", type=ColumnType.string, nullable=False),
                    ColumnSpec(name="price", type=ColumnType.float_),
                ],
            )
        ]
    )


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "products.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "price"])
        writer.writerow(["1", "Widget", "9.99"])
        writer.writerow(["2", "Gadget", "19.99"])
    return p


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "corpus.sqlite"


@pytest.mark.asyncio
async def test_ingest_structured_inserts_rows(csv_file: Path, db_path: Path):
    schema = _schema()
    result = await ingest_structured(csv_file, db_path, schema)
    assert result["products"]["status"] == "success"
    assert result["products"]["inserted"] == 2
    assert result["products"]["errors"] == []


@pytest.mark.asyncio
async def test_ingest_structured_creates_table(csv_file: Path, db_path: Path):
    schema = _schema()
    await ingest_structured(csv_file, db_path, schema)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_ingest_structured_missing_column(tmp_path: Path, db_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("id,name\n1,Widget\n")
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="bad",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                    ColumnSpec(name="name", type=ColumnType.string),
                    ColumnSpec(name="missing_col", type=ColumnType.string),
                ],
            )
        ]
    )
    result = await ingest_structured(p, db_path, schema)
    assert result["bad"]["status"] == "failed"
    assert result["bad"]["inserted"] == 0
    assert result["bad"]["errors"]


@pytest.mark.asyncio
async def test_ingest_structured_idempotent(tmp_path: Path):
    """Running ingest twice on separate DBs both succeed (CREATE TABLE IF NOT EXISTS is idempotent)."""
    p = tmp_path / "products.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "price"])
        writer.writerow(["1", "Widget", "9.99"])
    schema = _schema()
    db1 = tmp_path / "db1.sqlite"
    db2 = tmp_path / "db2.sqlite"
    result1 = await ingest_structured(p, db1, schema)
    result2 = await ingest_structured(p, db2, schema)
    assert result1["products"]["status"] == "success"
    assert result2["products"]["status"] == "success"


@pytest.mark.asyncio
async def test_ingest_structured_excel(tmp_path: Path, db_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "products.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "products"
    ws.append(["id", "name", "price"])
    ws.append([1, "Widget", 9.99])
    ws.append([2, "Gadget", 19.99])
    wb.save(p)
    schema = _schema()
    result = await ingest_structured(p, db_path, schema)
    assert result["products"]["status"] == "success"
    assert result["products"]["inserted"] == 2
    assert result["products"]["errors"] == []


@pytest.mark.asyncio
async def test_ingest_structured_bad_row_rollback(tmp_path: Path, db_path: Path):
    """Duplicate primary key should cause status==failed and errors non-empty."""
    p = tmp_path / "dup.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "price"])
        writer.writerow(["1", "Widget", "9.99"])
        writer.writerow(["1", "Duplicate", "5.00"])  # duplicate PK
    schema = _schema()
    result = await ingest_structured(p, db_path, schema)
    assert result["products"]["status"] == "failed"
    assert len(result["products"]["errors"]) > 0
    assert result["products"]["inserted"] == 0


@pytest.mark.asyncio
async def test_ingest_structured_empty_rows(tmp_path: Path, db_path: Path):
    """An empty CSV (header only) should yield status==success with inserted==0."""
    p = tmp_path / "empty.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "price"])
    schema = _schema()
    result = await ingest_structured(p, db_path, schema)
    assert result["products"]["status"] == "success"
    assert result["products"]["inserted"] == 0
    assert result["products"]["errors"] == []
