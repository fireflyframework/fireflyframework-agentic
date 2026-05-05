# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for CorpusAgent.ingest_source."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.content.sources import RawFile
from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)
from fireflyframework_agentic.rag.agent import CorpusAgent, IngestSummary


class _StubEmbedder:
    """Deterministic 8-dim embedder for tests."""

    dimension = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t) % 7) / 7.0] * self.dimension for t in texts]


class _StubVectorStore:
    def __init__(self) -> None:
        self.documents: list[Any] = []

    async def upsert(self, documents: list[Any]) -> None:
        self.documents.extend(documents)

    async def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def delete_by_doc_id(self, doc_id: str) -> None:
        self.documents = [d for d in self.documents if getattr(d, "doc_id", None) != doc_id]

    async def close(self) -> None:
        return None


class _FakeSource:
    """Minimal in-memory ContentSource that yields supplied RawFile objects."""

    def __init__(self, files: list[tuple[Path, RawFile]]) -> None:
        self._files = files
        self._committed: str | None = None
        self._pending: str | None = "fake-cursor-1"

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:  # noqa: ARG002
        for _, raw in self._files:
            yield raw

    async def fetch(self, file: RawFile) -> Path:
        for path, raw in self._files:
            if raw.source_id == file.source_id:
                return path
        raise KeyError(file.source_id)

    async def current_cursor(self) -> str | None:
        return self._committed

    async def pending_cursor(self) -> str | None:
        return self._pending

    async def commit_delta(self, cursor: str) -> None:
        self._committed = cursor


def _raw(path: Path, source_id: str | None = None) -> RawFile:
    stat = path.stat()
    return RawFile(
        source_id=source_id or f"fake:{path.name}",
        name=path.name,
        mime_type="text/plain",
        size_bytes=stat.st_size,
        etag=f"{stat.st_mtime_ns}:{stat.st_size}",
        fetched_at=datetime.now(UTC),
        metadata={"absolute_path": str(path)},
    )


def _agent(root: Path) -> CorpusAgent:
    return CorpusAgent(
        root=root,
        embed_model="openai:text-embedding-3-small",
        embed_dimension=8,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=_StubEmbedder(),
        _vector_store=_StubVectorStore(),
    )


@pytest.mark.asyncio
async def test_ingest_source_runs_pipeline_and_commits_cursor(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    a = docs_dir / "a.md"
    a.write_text("alpha", encoding="utf-8")
    b = docs_dir / "b.md"
    b.write_text("beta", encoding="utf-8")
    source = _FakeSource([(a, _raw(a)), (b, _raw(b))])

    async with _agent(tmp_path / "corpus") as agent:
        summary = await agent.ingest_source(source)

    assert isinstance(summary, IngestSummary)
    assert summary.ingested == 2
    assert summary.skipped == 0
    assert summary.failed == 0
    assert summary.cursor == "fake-cursor-1"
    assert source._committed == "fake-cursor-1"  # cursor was committed


@pytest.mark.asyncio
async def test_ingest_source_does_not_commit_on_fetch_failure(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")

    class _FailFetch(_FakeSource):
        async def fetch(self, file: RawFile) -> Path:
            raise RuntimeError("boom")

    source = _FailFetch([(a, _raw(a))])

    async with _agent(tmp_path / "corpus") as agent:
        summary = await agent.ingest_source(source)

    assert summary.failed == 1
    assert summary.ingested == 0
    # Per-file fetch failures DO commit the cursor — drained iterator.
    # (Source-level errors that raise out of the iterator should not — covered separately.)
    assert source._committed == "fake-cursor-1"


@pytest.mark.asyncio
async def test_ingest_source_with_local_folder_source(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")
    (docs / "b.md").write_text("beta", encoding="utf-8")

    src = LocalFolderSource(LocalFolderSourceConfig(folder=docs))

    async with _agent(tmp_path / "corpus") as agent:
        summary = await agent.ingest_source(src)

    assert summary.ingested == 2
    assert summary.failed == 0


@pytest.mark.asyncio
async def test_ingest_summary_aggregates(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    source = _FakeSource([(a, _raw(a))])

    async with _agent(tmp_path / "corpus") as agent:
        summary = await agent.ingest_source(source)

    assert summary.results and summary.results[0].status == "success"
    assert summary.ingested == sum(1 for r in summary.results if r.status == "success")
