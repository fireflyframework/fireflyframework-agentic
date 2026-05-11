# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""End-to-end regression for parallel MCP tool calls on the same corpus.

This test exercises the real ``CorpusAgent`` + ``DatabaseStore`` +
structured pipeline against a real on-disk SQLite file. It mocks only the
embedding provider (to keep CI hermetic and fast) and the LLM-backed
schema-discovery agent (we pre-supply a ``TargetSchema``). Everything
else is live code.

Pre-fix this test would non-deterministically hit "database disk image is
malformed" or land an empty ``ingestions`` ledger; post-fix the parallel
ingest lands cleanly and ``PRAGMA integrity_check`` returns ``ok``.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.tools.builtins import corpus_rag

pytestmark = pytest.mark.integration


class _StubEmbedder:
    """Deterministic, hermetic stand-in for the real embedder.

    The corpus pipeline only cares that ``embed`` returns one vector per
    input with a stable dimensionality; the actual numeric values don't
    affect the assertions we make about parallel-write integrity.
    """

    async def embed(self, texts, **_kwargs):
        return EmbeddingResult(
            embeddings=[[0.0, 0.0, 0.0, 0.0] for _ in texts],
            model="stub",
            usage=None,
            dimensions=4,
        )

    async def embed_one(self, _text, **_kwargs):
        return [0.0, 0.0, 0.0, 0.0]


class _StubVectorStore:
    """In-memory vector store stand-in (no Azure / pgvector dependency)."""

    def __init__(self) -> None:
        self.docs: dict[str, Any] = {}

    async def upsert(self, documents, _namespace="default"):
        for d in documents:
            self.docs[d.id] = d

    async def delete(self, ids, _namespace="default"):
        for i in ids:
            self.docs.pop(i, None)


@pytest.fixture
def drop_folder(tmp_path: Path) -> Path:
    """Mixed unstructured + tabular corpus used by both ingest modes.

    The markdown bodies are intentionally long so the chunker actually
    emits chunks (short docs are filtered out, which would mask the
    regression we're guarding against).
    """
    drop = tmp_path / "drop"
    drop.mkdir()
    body = "This is a sentence with several words. " * 50
    (drop / "doc.md").write_text(f"# Title\n\n{body}\n\n## Section\n\n{body}\n")
    (drop / "doc2.md").write_text(f"# Other Title\n\n{body}\n\n## Notes\n\n{body}\n")
    (drop / "rows.csv").write_text("id,amount\n1,9.99\n2,19.99\n3,29.99\n")
    return drop


@pytest.fixture(autouse=True)
async def _isolated_corpus_root(monkeypatch, tmp_path: Path):
    """Clear module-level state and point CORPUS_ROOT at a fresh tmp dir.

    Async so the teardown ``await _shutdown_agents()`` runs on the live
    pytest-asyncio event loop without colliding with ``asyncio.run``.
    """
    corpus_rag._AGENT_CACHE.clear()
    corpus_rag._WRITE_LOCKS.clear()
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "corpora"))
    monkeypatch.setenv("EMBEDDING_MODEL", "openai:text-embedding-3-small")
    monkeypatch.setenv("EXPANSION_MODEL", "anthropic:claude-haiku-3-5")
    monkeypatch.setenv("ANSWER_MODEL", "anthropic:claude-haiku-3-5")
    monkeypatch.setenv("RERANK_MODEL", "anthropic:claude-haiku-3-5")
    yield
    await corpus_rag._shutdown_agents()


def _stub_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="rows",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_),
                ],
            )
        ]
    )


async def test_parallel_filesystem_and_structured_ingest_do_not_corrupt(
    drop_folder: Path,
) -> None:
    """Regression: structured + filesystem ingest in parallel on one corpus
    used to produce 'database disk image is malformed' and partial writes.
    After the fix, both succeed and ``PRAGMA integrity_check`` returns ok."""

    agent = await corpus_rag._agent_for("regression")
    agent._embedder = _StubEmbedder()
    agent._vector_store = _StubVectorStore()

    schema = _stub_schema()
    with patch(
        "fireflyframework_agentic.rag.agent.discover_schema_for_paths",
        new=AsyncMock(return_value=schema),
    ):
        results = await asyncio.gather(
            corpus_rag.ingest_corpus_filesystem.execute(
                corpus_id="regression",
                root_path=str(drop_folder),
            ),
            corpus_rag.ingest_corpus_structured.execute(
                corpus_id="regression",
                path=str(drop_folder),
                schema=schema.model_dump(mode="json"),
            ),
        )

    fs_result, st_result = results
    assert fs_result["failed"] == 0, f"filesystem ingest failed: {fs_result}"
    assert st_result["failed"] == 0, f"structured ingest failed: {st_result}"

    db_path = Path(corpus_rag._corpus_root()) / "regression" / "corpus.sqlite"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        assert integrity == ("ok",), f"integrity check failed: {integrity}"
        chunks = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        rows = conn.execute("SELECT count(*) FROM rows").fetchone()[0]
        assert chunks > 0, "filesystem ingest produced no chunks"
        assert rows == 3, f"structured ingest produced {rows} rows, expected 3"
    finally:
        conn.close()


async def test_parallel_writes_on_different_corpora_are_independent(
    drop_folder: Path,
) -> None:
    """Two corpora can write in parallel without serialising on each other."""

    a = await corpus_rag._agent_for("alpha")
    a._embedder, a._vector_store = _StubEmbedder(), _StubVectorStore()
    b = await corpus_rag._agent_for("beta")
    b._embedder, b._vector_store = _StubEmbedder(), _StubVectorStore()

    await asyncio.gather(
        corpus_rag.ingest_corpus_filesystem.execute(
            corpus_id="alpha",
            root_path=str(drop_folder),
        ),
        corpus_rag.ingest_corpus_filesystem.execute(
            corpus_id="beta",
            root_path=str(drop_folder),
        ),
    )

    for cid in ("alpha", "beta"):
        db = Path(corpus_rag._corpus_root()) / cid / "corpus.sqlite"
        assert db.exists()
        conn = sqlite3.connect(db)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        finally:
            conn.close()
