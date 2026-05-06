from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.ingest.structured_registry import (
    discover_schema,
    discover_schema_interactive,
)
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    SchemaFeedback,
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

    with patch("fireflyframework_agentic.rag.ingest.structured_registry.create_extractor_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        result = await discover_schema(csv_file)

    assert result.tables[0].name == "sales"
    assert len(result.tables[0].columns) == 3


@pytest.mark.asyncio
async def test_discover_schema_passes_sample_to_agent(csv_file: Path):
    mock_result = MagicMock()
    mock_result.output = TargetSchema(
        tables=[TableSpec(name="sales", columns=[ColumnSpec(name="id", type=ColumnType.integer)])]
    )

    with patch("fireflyframework_agentic.rag.ingest.structured_registry.create_extractor_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        await discover_schema(csv_file)

    prompt = mock_agent.run.call_args[0][0]
    assert "sales.csv" in prompt
    assert "id" in prompt
    assert "amount" in prompt


def _stub_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="data",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                ],
            )
        ]
    )


@pytest.mark.asyncio
async def test_interactive_returns_immediately_when_approved(tmp_path: Path):
    """on_review returning approved=True on first call ends the loop after one round."""
    csv = tmp_path / "data.csv"
    csv.write_text("id\n1\n2\n")

    on_review = AsyncMock(return_value=SchemaFeedback(approved=True))

    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(return_value=_stub_schema()),
    ):
        result = await discover_schema_interactive(csv, on_review=on_review)

    assert result == _stub_schema()
    on_review.assert_awaited_once()


@pytest.mark.asyncio
async def test_interactive_refines_on_rejection(tmp_path: Path):
    """on_review returning approved=False triggers a second inference round."""
    csv = tmp_path / "data.csv"
    csv.write_text("id,name\n1,Alice\n")

    schema_v1 = _stub_schema()
    schema_v2 = TargetSchema(
        tables=[
            TableSpec(
                name="t",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                    ColumnSpec(name="name", type=ColumnType.string),
                ],
            )
        ]
    )

    on_review = AsyncMock(
        side_effect=[
            SchemaFeedback(approved=False, corrections="name column is missing"),
            SchemaFeedback(approved=True),
        ]
    )

    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(side_effect=[schema_v1, schema_v2]),
    ):
        result = await discover_schema_interactive(csv, on_review=on_review, max_rounds=3)

    assert result == schema_v2
    assert on_review.await_count == 2


@pytest.mark.asyncio
async def test_interactive_returns_last_schema_after_max_rounds(tmp_path: Path):
    """After max_rounds the last schema is returned even without approval."""
    csv = tmp_path / "data.csv"
    csv.write_text("id\n1\n")

    on_review = AsyncMock(return_value=SchemaFeedback(approved=False, corrections="still wrong"))

    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(return_value=_stub_schema()),
    ):
        result = await discover_schema_interactive(csv, on_review=on_review, max_rounds=2)

    assert result == _stub_schema()
    assert on_review.await_count == 2
