from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.ingest.structured_registry import (
    TABULAR_SUFFIXES,
    _csv_sample,
    _sample_for,
    discover_schema,
    discover_schema_for_paths,
    discover_schema_interactive,
    is_tabular_file,
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
async def test_discover_schema_for_paths_combines_samples(tmp_path: Path):
    """Multi-file discovery sends one prompt mentioning every file."""
    a = tmp_path / "customers.csv"
    a.write_text("id,name\n1,Alice\n")
    b = tmp_path / "orders.csv"
    b.write_text("id,customer_id,total\n1,1,9.99\n")

    expected = TargetSchema(
        tables=[
            TableSpec(
                name="customers",
                columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
            ),
            TableSpec(
                name="orders",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="customer_id", type=ColumnType.integer, foreign_key="customers.id"),
                ],
            ),
        ]
    )
    mock_result = MagicMock()
    mock_result.output = expected

    with patch("fireflyframework_agentic.rag.ingest.structured_registry.create_extractor_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        result = await discover_schema_for_paths([a, b])

    prompt = mock_agent.run.call_args[0][0]
    assert "customers.csv" in prompt
    assert "orders.csv" in prompt
    assert "foreign_key" in prompt
    assert len(result.tables) == 2


@pytest.mark.asyncio
async def test_discover_schema_for_paths_single_path_delegates(tmp_path: Path):
    """A single-file folder collapses to discover_schema (no multi-file prompt)."""
    p = tmp_path / "only.csv"
    p.write_text("id\n1\n")

    expected = TargetSchema(tables=[TableSpec(name="only", columns=[ColumnSpec(name="id", type=ColumnType.integer)])])
    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(return_value=expected),
    ) as mock_single:
        result = await discover_schema_for_paths([p])

    mock_single.assert_awaited_once()
    assert result == expected


@pytest.mark.asyncio
async def test_discover_schema_for_paths_with_corrections(tmp_path: Path):
    """Refinement on a multi-file folder echoes corrections + previous_schema."""
    a = tmp_path / "x.csv"
    a.write_text("id\n1\n")
    b = tmp_path / "y.csv"
    b.write_text("id\n2\n")
    prior = TargetSchema(
        tables=[
            TableSpec(name="x", columns=[ColumnSpec(name="id", type=ColumnType.integer)]),
            TableSpec(name="y", columns=[ColumnSpec(name="id", type=ColumnType.integer)]),
        ]
    )
    expected = TargetSchema(
        tables=[
            TableSpec(
                name="x",
                columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
            ),
            TableSpec(
                name="y",
                columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
            ),
        ]
    )
    mock_result = MagicMock()
    mock_result.output = expected

    with patch("fireflyframework_agentic.rag.ingest.structured_registry.create_extractor_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        await discover_schema_for_paths(
            [a, b],
            corrections="mark id as primary_key on every table",
            previous_schema=prior,
        )

    prompt = mock_agent.run.call_args[0][0]
    assert "User corrections" in prompt
    assert "mark id as primary_key" in prompt
    assert "Previous schema attempt" in prompt


def test_tabular_suffixes_contents() -> None:
    assert frozenset({".csv", ".xls", ".xlsx"}) == TABULAR_SUFFIXES


@pytest.mark.parametrize(
    "name,expected",
    [
        ("a.csv", True),
        ("a.CSV", True),
        ("a.xlsx", True),
        ("a.xls", True),
        ("a.pptx", False),
        ("a.pdf", False),
        ("a.docx", False),
        ("noext", False),
    ],
)
def test_is_tabular_file(tmp_path: Path, name: str, expected: bool) -> None:
    assert is_tabular_file(tmp_path / name) is expected


def test_sample_for_raises_on_unsupported_suffix(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"PK\x03\x04binary-zip-bytes")
    with pytest.raises(ValueError, match="unsupported file type"):
        _sample_for(pptx)


def test_csv_sample_wraps_decoding_error_with_hint(tmp_path: Path) -> None:
    """A Latin-1 CSV (Windows export) should fail with a hint, not a raw UnicodeDecodeError."""
    p = tmp_path / "sales.csv"
    # \xba is the masculine ordinal in Latin-1 / CP1252 — invalid in UTF-8.
    p.write_bytes(b"id,producto\n1,Caf\xbae\n")
    with pytest.raises(ValueError, match="UTF-8|Latin-1|CP1252"):
        _csv_sample(p)


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
