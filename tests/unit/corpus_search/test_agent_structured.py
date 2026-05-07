from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.ingest import IngestionResult
from fireflyframework_agentic.rag.ingest.structured_schema import (  # noqa: F401
    ColumnSpec,
    ColumnType,
    SchemaFeedback,
    TableSpec,
    TargetSchema,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubEmbedder:
    async def embed(self, texts: list[str], **_kwargs: Any) -> EmbeddingResult:
        return EmbeddingResult(
            embeddings=[[0.0, 0.0, 0.0, 0.0] for _ in texts],
            model="stub",
            usage=None,
            dimensions=4,
        )

    async def embed_one(self, _text: str, **_kwargs: Any) -> list[float]:
        return [0.0, 0.0, 0.0, 0.0]


class _StubVectorStore:
    def __init__(self) -> None:
        self.docs: dict[str, Any] = {}

    async def upsert(self, documents: Sequence[Any], _namespace: str = "default") -> None:
        for d in documents:
            self.docs[d.id] = d

    async def delete(self, ids: Sequence[str], _namespace: str = "default") -> None:
        for i in ids:
            self.docs.pop(i, None)


def _make_agent(tmp_path: Path) -> Any:
    """Build a CorpusAgent with stub embedder and vector store (no LLM required)."""
    from fireflyframework_agentic.rag.agent import CorpusAgent

    return CorpusAgent(
        root=tmp_path / "corpus",
        embed_model="openai:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-3-5",
        answer_model="anthropic:claude-haiku-3-5",
        rerank_model="anthropic:claude-haiku-3-5",
        _embedder=_StubEmbedder(),
        _vector_store=_StubVectorStore(),
    )


def _stub_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, nullable=False, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_, nullable=True, primary_key=False),
                ],
            )
        ]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


_STUB_INGEST_OK = {"sales": {"status": "success", "inserted": 2, "errors": []}}


@pytest.mark.asyncio
async def test_ingest_one_structured_mode_calls_structured_pipeline(tmp_path: Path) -> None:
    """ingest_one with mode='structured' calls discover_schema and ingest_structured."""
    agent = _make_agent(tmp_path)
    csv_file = tmp_path / "sales.csv"
    csv_file.write_text("id,amount\n1,10.5\n2,20.0\n")

    schema = _stub_schema()

    with (
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema",
            new=AsyncMock(return_value=schema),
        ) as mock_discover,
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(return_value=_STUB_INGEST_OK),
        ) as mock_ingest_structured,
    ):
        result = await agent.ingest_one(csv_file, mode="structured")

    mock_discover.assert_awaited_once_with(csv_file, model="anthropic:claude-sonnet-4-6")
    mock_ingest_structured.assert_awaited_once()
    assert result.status == "success"
    assert result.n_chunks == 0


@pytest.mark.asyncio
async def test_ingest_one_structured_skips_on_second_call(tmp_path: Path) -> None:
    """ingest_one with mode='structured' skips a file that was already ingested."""
    agent = _make_agent(tmp_path)
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("id,value\n1,a\n")

    schema = _stub_schema()

    with (
        patch("fireflyframework_agentic.rag.agent.discover_schema", new=AsyncMock(return_value=schema)),
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(return_value=_STUB_INGEST_OK),
        ),
    ):
        first = await agent.ingest_one(csv_file, mode="structured")
        second = await agent.ingest_one(csv_file, mode="structured")

    assert first.status == "success"
    assert second.status == "skipped"


@pytest.mark.asyncio
async def test_ingest_one_structured_records_load_failed_on_exception(tmp_path: Path) -> None:
    """ingest_one with mode='structured' returns load_failed when discover_schema raises."""
    agent = _make_agent(tmp_path)
    csv_file = tmp_path / "broken.csv"
    csv_file.write_text("a,b\n1,2\n")

    with (
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema",
            new=AsyncMock(side_effect=RuntimeError("LLM error")),
        ),
        patch("fireflyframework_agentic.rag.agent.ingest_structured", new=AsyncMock()),
    ):
        result = await agent.ingest_one(csv_file, mode="structured")

    assert result.status == "load_failed"


@pytest.mark.asyncio
async def test_ingest_one_structured_records_load_failed_when_pipeline_reports_table_failure(
    tmp_path: Path,
) -> None:
    """If ingest_structured rolls a table back (e.g. PK collision), the agent
    must surface that as load_failed and skip schema-registry persistence —
    not silently report success against an empty SQLite table.
    """
    agent = _make_agent(tmp_path)
    csv_file = tmp_path / "products.csv"
    csv_file.write_text("id,name\n1,a\n1,b\n")

    schema = _stub_schema()
    failing_result = {
        "products": {
            "status": "failed",
            "inserted": 0,
            "errors": ["row 3: UNIQUE constraint failed: products.id"],
        }
    }

    with (
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema",
            new=AsyncMock(return_value=schema),
        ),
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(return_value=failing_result),
        ),
    ):
        result = await agent.ingest_one(csv_file, mode="structured")

    assert result.status == "load_failed", "partial-rollback (PK collision) must not be silently reported as success"


@pytest.mark.asyncio
async def test_ingest_one_unstructured_mode_still_works(tmp_path: Path) -> None:
    """ingest_one with mode='unstructured' (default) still delegates to the unstructured pipeline."""
    agent = _make_agent(tmp_path)
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Hello\n\nSome content.")

    with patch(
        "fireflyframework_agentic.rag.agent.ingest_one",
        new=AsyncMock(
            return_value=IngestionResult(
                doc_id="abc123",
                source_path=str(md_file),
                status="success",
                n_chunks=1,
            )
        ),
    ) as mock_ingest:
        result = await agent.ingest_one(md_file)

    mock_ingest.assert_awaited_once()
    assert result.status == "success"


@pytest.mark.asyncio
async def test_ingest_folder_structured_processes_all_files(tmp_path: Path) -> None:
    """ingest_folder with mode='structured' calls _ingest_structured_file for each file."""
    agent = _make_agent(tmp_path)
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "a.csv").write_text("x,y\n1,2\n")
    (folder / "b.csv").write_text("x,y\n3,4\n")

    schema = _stub_schema()

    with (
        patch("fireflyframework_agentic.rag.agent.discover_schema", new=AsyncMock(return_value=schema)),
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(return_value=_STUB_INGEST_OK),
        ),
    ):
        summary = await agent.ingest_folder(folder, mode="structured")

    assert len(summary.results) == 2
    assert all(r.status == "success" for r in summary.results)


@pytest.mark.asyncio
async def test_ingest_one_structured_calls_interactive_when_on_review_provided(tmp_path: Path) -> None:
    """When on_review is passed, ingest_one must call discover_schema_interactive, not discover_schema."""
    agent = _make_agent(tmp_path)
    csv_file = tmp_path / "sales.csv"
    csv_file.write_text("id,amount\n1,10.5\n")

    on_review = AsyncMock(return_value=SchemaFeedback(approved=True))
    schema = _stub_schema()

    with (
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema_interactive",
            new=AsyncMock(return_value=schema),
        ) as mock_interactive,
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema",
            new=AsyncMock(return_value=schema),
        ) as mock_one_shot,
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(return_value=_STUB_INGEST_OK),
        ),
    ):
        await agent.ingest_one(csv_file, mode="structured", on_review=on_review)

    mock_interactive.assert_awaited_once()
    mock_one_shot.assert_not_awaited()
