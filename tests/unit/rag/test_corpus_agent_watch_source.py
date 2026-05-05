# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit test: watch_source polls list_changed at the given interval."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fireflyframework_agentic.content.sources import RawFile
from fireflyframework_agentic.rag.agent import CorpusAgent


class _StubEmbedder:
    dimension = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class _StubVectorStore:
    async def upsert(self, documents: list) -> None:
        pass

    async def search(self, *args, **kwargs) -> list:
        return []

    async def delete_by_doc_id(self, doc_id: str) -> None:
        pass

    async def close(self) -> None:
        pass


class _PollingSource:
    """Yields a different file each tick to verify the polling loop."""

    def __init__(self, files: list[Path]) -> None:
        self._files = list(files)
        self._committed: str | None = None

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:  # noqa: ARG002
        if not self._files:
            return
        path = self._files.pop(0)
        stat = path.stat()
        yield RawFile(
            source_id=f"poll:{path.name}",
            name=path.name,
            mime_type="text/plain",
            size_bytes=stat.st_size,
            etag=f"{stat.st_mtime_ns}:{stat.st_size}",
            fetched_at=datetime.now(UTC),
            metadata={"absolute_path": str(path)},
        )

    async def fetch(self, file: RawFile) -> Path:
        return Path(file.metadata["absolute_path"])

    async def current_cursor(self) -> str | None:
        return self._committed

    async def pending_cursor(self) -> str | None:
        return f"after-{self._committed}"

    async def commit_delta(self, cursor: str) -> None:
        self._committed = cursor


@pytest.mark.asyncio
async def test_watch_source_polls_until_cancelled(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("beta", encoding="utf-8")

    agent = CorpusAgent(
        root=tmp_path / "corpus",
        embed_model="openai:text-embedding-3-small",
        embed_dimension=8,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=_StubEmbedder(),
        _vector_store=_StubVectorStore(),
    )
    source = _PollingSource([a, b])

    seen: list[str] = []
    async with agent:

        async def consume() -> None:
            async for result in agent.watch_source(source, interval=0.01):
                seen.append(result.source_path)
                if len(seen) >= 2:
                    raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await consume()

    assert len(seen) == 2
    # Cursor was committed at least once during the loop
    assert source._committed is not None
