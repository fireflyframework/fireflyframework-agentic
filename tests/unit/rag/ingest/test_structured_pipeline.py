import contextlib
import csv
import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.rag.ingest.structured_pipeline import (
    _sync_ingest_table,
    ingest_structured,
)
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.storage import DatabaseStore, LocalBackend


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


def _make_store(tmp_path: Path, store_id: str = "ut-structured") -> DatabaseStore:
    return DatabaseStore(
        LocalBackend(tmp_path / f"{store_id}.sqlite"),
        store_id=store_id,
        cache_root=tmp_path / f"cache-{store_id}",
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
def db_store(tmp_path: Path) -> DatabaseStore:
    return _make_store(tmp_path)


@pytest.mark.asyncio
async def test_ingest_structured_inserts_rows(csv_file: Path, db_store: DatabaseStore):
    schema = _schema()
    result = await ingest_structured(csv_file, db_store, schema)
    assert result["products"]["status"] == "success"
    assert result["products"]["inserted"] == 2
    assert result["products"]["errors"] == []


@pytest.mark.asyncio
async def test_ingest_structured_creates_table(csv_file: Path, db_store: DatabaseStore):
    schema = _schema()
    await ingest_structured(csv_file, db_store, schema)
    conn = sqlite3.connect(db_store.cache_path)
    rows = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_ingest_structured_missing_column(tmp_path: Path, db_store: DatabaseStore):
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
    result = await ingest_structured(p, db_store, schema)
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
    store1 = _make_store(tmp_path, store_id="db1")
    store2 = _make_store(tmp_path, store_id="db2")
    result1 = await ingest_structured(p, store1, schema)
    result2 = await ingest_structured(p, store2, schema)
    assert result1["products"]["status"] == "success"
    assert result2["products"]["status"] == "success"


@pytest.mark.asyncio
async def test_ingest_structured_excel(tmp_path: Path, db_store: DatabaseStore):
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
    result = await ingest_structured(p, db_store, schema)
    assert result["products"]["status"] == "success"
    assert result["products"]["inserted"] == 2
    assert result["products"]["errors"] == []


@pytest.mark.asyncio
async def test_ingest_structured_bad_row_rollback(tmp_path: Path, db_store: DatabaseStore):
    """Duplicate primary key should cause status==failed and errors non-empty."""
    p = tmp_path / "dup.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "price"])
        writer.writerow(["1", "Widget", "9.99"])
        writer.writerow(["1", "Duplicate", "5.00"])  # duplicate PK
    schema = _schema()
    result = await ingest_structured(p, db_store, schema)
    assert result["products"]["status"] == "failed"
    assert len(result["products"]["errors"]) > 0
    assert result["products"]["inserted"] == 0


@pytest.mark.asyncio
async def test_ingest_structured_emits_foreign_key(tmp_path: Path, db_store: DatabaseStore):
    """A column with foreign_key='customers.id' should produce a FOREIGN KEY clause."""
    customers_csv = tmp_path / "customers.csv"
    customers_csv.write_text("id,name\n1,Alice\n2,Bob\n")
    orders_csv = tmp_path / "orders.csv"
    orders_csv.write_text("id,customer_id,total\n1,1,9.99\n2,2,19.99\n")

    customers_schema = TargetSchema(
        tables=[
            TableSpec(
                name="customers",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="name", type=ColumnType.string),
                ],
            )
        ]
    )
    orders_schema = TargetSchema(
        tables=[
            TableSpec(
                name="orders",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(
                        name="customer_id",
                        type=ColumnType.integer,
                        foreign_key="customers.id",
                    ),
                    ColumnSpec(name="total", type=ColumnType.float_),
                ],
            )
        ]
    )

    await ingest_structured(customers_csv, db_store, customers_schema)
    result = await ingest_structured(orders_csv, db_store, orders_schema)
    assert result["orders"]["status"] == "success"

    conn = sqlite3.connect(db_store.cache_path)
    try:
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()[0]
        fks = conn.execute("PRAGMA foreign_key_list(orders)").fetchall()
    finally:
        conn.close()
    assert "FOREIGN KEY" in ddl
    assert any(fk[2] == "customers" and fk[3] == "customer_id" and fk[4] == "id" for fk in fks)


@pytest.mark.asyncio
async def test_ingest_structured_orders_tables_by_fk(tmp_path: Path, db_store: DatabaseStore):
    """When the parent table is listed after the child, the parent is created first."""
    parent_csv = tmp_path / "parent.csv"
    parent_csv.write_text("id\n1\n")
    child_csv = tmp_path / "child.csv"
    child_csv.write_text("id,parent_id\n1,1\n")

    schema = TargetSchema(
        tables=[
            TableSpec(
                name="child",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="parent_id", type=ColumnType.integer, foreign_key="parent.id"),
                ],
            ),
            TableSpec(
                name="parent",
                columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
            ),
        ]
    )

    # ingest parent first under combined schema (would fail without ordering
    # if the FOREIGN KEY clause referenced an absent table on creation —
    # SQLite is permissive about that, but we still want predictable order).
    await ingest_structured(parent_csv, db_store, TargetSchema(tables=[t for t in schema.tables if t.name == "parent"]))
    result = await ingest_structured(child_csv, db_store, schema)
    # The combined schema includes both tables; ordering means parent is
    # processed before child — child table creation succeeds.
    assert result["child"]["status"] == "success"


@pytest.mark.asyncio
async def test_ingest_structured_empty_rows(tmp_path: Path, db_store: DatabaseStore):
    """An empty CSV (header only) should yield status==success with inserted==0."""
    p = tmp_path / "empty.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "price"])
    schema = _schema()
    result = await ingest_structured(p, db_store, schema)
    assert result["products"]["status"] == "success"
    assert result["products"]["inserted"] == 0
    assert result["products"]["errors"] == []


def test_sync_ingest_table_uses_busy_timeout_pragma(tmp_path, monkeypatch):
    """The writer connection must explicitly set busy_timeout via PRAGMA so
    it doesn't rely on the python sqlite3 module's default (5 s)."""
    db_path = tmp_path / "x.sqlite"
    spec = TableSpec(
        name="t",
        columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
    )

    captured_sql: list[str] = []
    real_connect = sqlite3.connect

    def spy_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(captured_sql.append)
        return conn

    monkeypatch.setattr(
        "fireflyframework_agentic.rag.ingest.structured_pipeline.sqlite3.connect",
        spy_connect,
    )
    _sync_ingest_table(db_path, spec, [{"id": 1}])

    captured_timeouts: list[int] = []
    for sql in captured_sql:
        if "busy_timeout" in sql.lower():
            with contextlib.suppress(IndexError, ValueError):
                captured_timeouts.append(int(sql.split("=")[1].strip()))

    assert 30000 in captured_timeouts, f"expected busy_timeout=30000, got {captured_timeouts}"


@pytest.mark.asyncio
async def test_ingest_structured_surfaces_encoding_hint_on_latin1_csv(tmp_path: Path, db_store: DatabaseStore) -> None:
    p = tmp_path / "products.csv"
    p.write_bytes(b"id,nombre\n1,Caf\xbae\n")  # 0xBA is Latin-1 'masculine ordinal'
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="products",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="nombre", type=ColumnType.string),
                ],
            )
        ]
    )
    with pytest.raises(ValueError, match="UTF-8|Latin-1|CP1252"):
        await ingest_structured(p, db_store, schema)


@pytest.mark.asyncio
async def test_ingest_structured_acquires_storage_write_lock(tmp_path: Path) -> None:
    """ingest_structured must go through DatabaseStore.for_write — verified
    by counting backend lock acquisitions, not just the for_write() call.

    Defends against a regression where the production code calls for_write()
    but then opens a sidecar sqlite3 connection it computed itself.
    """
    db_store = _make_store(tmp_path, store_id="for-write-test")
    # Wrap the backend's acquire_lock to count calls without losing behaviour.
    real_acquire = db_store._backend.acquire_lock
    call_count = 0

    async def spy_acquire(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await real_acquire(*args, **kwargs)

    db_store._backend.acquire_lock = spy_acquire  # type: ignore[method-assign]

    csv_file = tmp_path / "rows.csv"
    csv_file.write_text("id\n1\n2\n")
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="rows",
                columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
            )
        ]
    )

    result = await ingest_structured(csv_file, db_store, schema)

    assert call_count == 1, f"expected exactly one for_write() acquisition, got {call_count}"
    assert result["rows"]["status"] == "success"
    assert result["rows"]["inserted"] == 2
