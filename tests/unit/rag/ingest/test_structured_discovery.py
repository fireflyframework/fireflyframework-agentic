from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.ingest.structured_registry import discover_schema
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "sales.csv"
    p.write_text("id,amount,date\n1,9.99,2026-01-01\n2,19.99,2026-01-02\n")
    return p


@pytest.mark.asyncio
async def test_discover_schema_csv(csv_file: Path):
    expected = TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_),
                    ColumnSpec(name="date", type=ColumnType.date),
                ],
            )
        ]
    )
    mock_result = MagicMock()
    mock_result.output = expected

    with patch("fireflyframework_agentic.rag.ingest.structured_registry._agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        result = await discover_schema(csv_file)

    assert result.tables[0].name == "sales"
    assert len(result.tables[0].columns) == 3


@pytest.mark.asyncio
async def test_discover_schema_passes_sample_to_agent(csv_file: Path):
    mock_result = MagicMock()
    mock_result.output = TargetSchema(
        tables=[TableSpec(name="sales", columns=[ColumnSpec(name="id", type=ColumnType.integer)])]
    )

    with patch("fireflyframework_agentic.rag.ingest.structured_registry._agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        await discover_schema(csv_file)

    prompt = mock_agent.run.call_args[0][0]
    assert "sales.csv" in prompt
    assert "id" in prompt
    assert "amount" in prompt
