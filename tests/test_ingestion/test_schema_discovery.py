"""Tests for schema discovery agent (LLM call is patched)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import openpyxl
import pytest

from fireflyframework_agentic.ingestion.agents.schema_discovery import (
    _read_sample,
    discover_schema,
)
from fireflyframework_agentic.ingestion.domain import ColumnSpec, TableSpec, TargetSchema


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    f = tmp_path / "orders.csv"
    f.write_text("id,customer,amount\n1,Alice,99.5\n2,Bob,12.0\n")
    return f


@pytest.fixture
def xlsx_file(tmp_path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["product_id", "name", "price"])
    ws.append([1, "Widget", 9.99])
    ws.append([2, "Gadget", 19.99])
    wb.save(tmp_path / "products.xlsx")
    return tmp_path / "products.xlsx"


def test_read_sample_csv(csv_file: Path):
    headers, rows = _read_sample(csv_file)
    assert headers == ["id", "customer", "amount"]
    assert rows == [["1", "Alice", "99.5"], ["2", "Bob", "12.0"]]


def test_read_sample_xlsx(xlsx_file: Path):
    headers, rows = _read_sample(xlsx_file)
    assert headers == ["product_id", "name", "price"]
    assert len(rows) == 2
    assert rows[0][1] == "Widget"


def test_read_sample_unsupported_raises(tmp_path: Path):
    f = tmp_path / "data.parquet"
    f.write_bytes(b"PAR1")
    with pytest.raises(ValueError, match="Unsupported file type"):
        _read_sample(f)


async def test_discover_schema_returns_target_schema(csv_file: Path):
    expected = TargetSchema(
        tables=[
            TableSpec(
                name="orders",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="customer", type="string"),
                    ColumnSpec(name="amount", type="float"),
                ],
            )
        ]
    )
    mock_result = AsyncMock()
    mock_result.output = expected

    with patch(
        "fireflyframework_agentic.ingestion.agents.schema_discovery._get_agent",
        return_value=AsyncMock(run=AsyncMock(return_value=mock_result)),
    ):
        result = await discover_schema(csv_file)

    assert result == expected
    assert result.tables[0].name == "orders"
