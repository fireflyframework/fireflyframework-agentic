# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration tests for ingest_from_source against a fake ContentSource."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.loaders import Document, MarkitdownLoader
from fireflyframework_agentic.content.sources import ContentSource, RawFile
from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.corpus import SqliteCorpus
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.pipeline import ingest_from_source

# --- Stubs ----------------------------------------------------------------


class _StubEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        self.calls.append(list(texts))
        return EmbeddingResult(
            embeddings=[[float(len(t)), 0.0, 0.0, 0.0] for t in texts],
            model="stub",
            usage=None,
            dimensions=4,
        )

    async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


class _PlainLoader(MarkitdownLoader):
    """Trivial loader that reads the file as text — avoids the markitdown optional dep."""

    def load(self, path: Path | str) -> Document:  # type: ignore[override]
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Source file not found: {p}")
        return Document(
            content=p.read_text(),
            metadata={"source_path": str(p.resolve()), "mime_type": "text/plain", "title": p.name},
        )


class _StubVectorStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def upsert(self, documents: Sequence[Any], namespace: str = "default") -> None:
        for d in documents:
            self.docs[d.id] = {"embedding": d.embedding, "text": d.text, "metadata": d.metadata}

    async def delete(self, ids: Sequence[str], namespace: str = "default") -> None:
        for i in ids:
            self.docs.pop(i, None)


class _FakeSource:
    """In-memory ContentSource over a list of pre-baked files on disk.

    The cursor advances per-yield; commit_delta records the most-recent value
    so tests can assert what (if anything) was committed.
    """

    def __init__(
        self,
        files: list[Path],
        *,
        raise_on_iter_at: int | None = None,
        raise_on_fetch_at: int | None = None,
    ) -> None:
        self._files = files
        self._raise_on_iter_at = raise_on_iter_at
        self._raise_on_fetch_at = raise_on_fetch_at
        self._pending: str | None = None
        self._committed: str | None = None
        self._committed_count = 0
        self._current: str | None = None

    @property
    def committed(self) -> str | None:
        return self._committed

    @property
    def commit_call_count(self) -> int:
        return self._committed_count

    def set_persisted_cursor(self, value: str | None) -> None:
        self._current = value

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:
        for i, p in enumerate(self._files):
            if self._raise_on_iter_at is not None and i == self._raise_on_iter_at:
                raise RuntimeError(f"iter boom at {i}")
            self._pending = f"cursor-{i}"
            yield RawFile(
                source_id=f"fake:{i}",
                name=p.name,
                mime_type="text/markdown",
                size_bytes=p.stat().st_size if p.exists() else 0,
                etag=f"etag-{i}",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
                metadata={"index": i},
            )

    async def fetch(self, file: RawFile) -> Path:
        idx = file.metadata["index"]
        if self._raise_on_fetch_at is not None and idx == self._raise_on_fetch_at:
            raise RuntimeError(f"fetch boom at {idx}")
        return self._files[idx]

    async def current_cursor(self) -> str | None:
        return self._current

    async def pending_cursor(self) -> str | None:
        return self._pending

    async def commit_delta(self, cursor: str) -> None:
        self._committed = cursor
        self._committed_count += 1


# --- Fixtures -------------------------------------------------------------


@pytest.fixture
async def setup(tmp_path: Path):
    corpus = SqliteCorpus(tmp_path / "corpus.sqlite")
    await corpus.initialise()
    ledger = IngestLedger(corpus)
    embedder = _StubEmbedder()
    vector_store = _StubVectorStore()
    chunker = TextChunker(chunk_size=80, chunk_overlap=10)
    loader = _PlainLoader()
    yield {
        "tmp_path": tmp_path,
        "corpus": corpus,
        "ledger": ledger,
        "embedder": embedder,
        "vector_store": vector_store,
        "chunker": chunker,
        "loader": loader,
    }
    await corpus.close()


def _write_files(folder: Path, n: int) -> list[Path]:
    paths: list[Path] = []
    for i in range(n):
        p = folder / f"doc{i}.md"
        p.write_text(f"# Doc {i}\n\nContent for document {i}.\n")
        paths.append(p)
    return paths


# --- Tests ----------------------------------------------------------------


async def test_fake_source_satisfies_protocol(setup: dict[str, Any]) -> None:
    paths = _write_files(setup["tmp_path"], 1)
    source = _FakeSource(paths)
    assert isinstance(source, ContentSource)


async def test_linear_ingests_all_files_and_commits_cursor(setup: dict[str, Any]) -> None:
    paths = _write_files(setup["tmp_path"], 3)
    source = _FakeSource(paths)
    results = await ingest_from_source(
        source=source,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=setup["embedder"],
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
        max_concurrency=1,
    )
    assert len(results) == 3
    assert all(r.status == "success" for r in results)
    assert source.committed == "cursor-2"
    assert source.commit_call_count == 1


async def test_concurrent_ingests_all_files_and_commits_cursor(setup: dict[str, Any]) -> None:
    paths = _write_files(setup["tmp_path"], 5)
    source = _FakeSource(paths)
    results = await ingest_from_source(
        source=source,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=setup["embedder"],
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
        max_concurrency=4,
    )
    assert len(results) == 5
    assert all(r.status == "success" for r in results)
    assert source.committed == "cursor-4"
    assert source.commit_call_count == 1


async def test_full_mode_ignores_persisted_cursor(setup: dict[str, Any]) -> None:
    paths = _write_files(setup["tmp_path"], 1)
    source = _FakeSource(paths)
    source.set_persisted_cursor("OLD-CURSOR")

    results = await ingest_from_source(
        source=source,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=setup["embedder"],
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
        mode="full",
    )
    assert len(results) == 1


async def test_invalid_max_concurrency_raises(setup: dict[str, Any]) -> None:
    source = _FakeSource([])
    with pytest.raises(ValueError, match="max_concurrency"):
        await ingest_from_source(
            source=source,
            corpus=setup["corpus"],
            vector_store=setup["vector_store"],
            embedder=setup["embedder"],
            ledger=setup["ledger"],
            chunker=setup["chunker"],
            loader=setup["loader"],
            max_concurrency=0,
        )


async def test_iter_exception_skips_commit_linear(setup: dict[str, Any]) -> None:
    paths = _write_files(setup["tmp_path"], 3)
    source = _FakeSource(paths, raise_on_iter_at=2)
    with pytest.raises(RuntimeError, match="iter boom"):
        await ingest_from_source(
            source=source,
            corpus=setup["corpus"],
            vector_store=setup["vector_store"],
            embedder=setup["embedder"],
            ledger=setup["ledger"],
            chunker=setup["chunker"],
            loader=setup["loader"],
            max_concurrency=1,
        )
    assert source.committed is None
    assert source.commit_call_count == 0


async def test_iter_exception_skips_commit_concurrent(setup: dict[str, Any]) -> None:
    paths = _write_files(setup["tmp_path"], 5)
    source = _FakeSource(paths, raise_on_iter_at=2)
    with pytest.raises(RuntimeError, match="iter boom"):
        await ingest_from_source(
            source=source,
            corpus=setup["corpus"],
            vector_store=setup["vector_store"],
            embedder=setup["embedder"],
            ledger=setup["ledger"],
            chunker=setup["chunker"],
            loader=setup["loader"],
            max_concurrency=3,
        )
    assert source.committed is None
    assert source.commit_call_count == 0


async def test_fetch_exception_skips_commit_concurrent(setup: dict[str, Any]) -> None:
    paths = _write_files(setup["tmp_path"], 4)
    source = _FakeSource(paths, raise_on_fetch_at=1)
    with pytest.raises(RuntimeError, match="fetch boom"):
        await ingest_from_source(
            source=source,
            corpus=setup["corpus"],
            vector_store=setup["vector_store"],
            embedder=setup["embedder"],
            ledger=setup["ledger"],
            chunker=setup["chunker"],
            loader=setup["loader"],
            max_concurrency=2,
        )
    assert source.committed is None
    assert source.commit_call_count == 0


async def test_per_file_failure_does_not_block_commit(setup: dict[str, Any]) -> None:
    """ingest_one returning status='load_failed' MUST NOT prevent the cursor commit.

    Per-file failures live in the ledger; they're retried via ledger replay,
    not delta replay. The cursor advances past them.
    """
    paths = _write_files(setup["tmp_path"], 2)
    # Replace one file with a path that does not exist so MarkitdownLoader
    # raises FileNotFoundError, which the pipeline encodes as load_failed.
    missing = setup["tmp_path"] / "missing.md"
    paths[1] = missing  # never written

    source = _FakeSource(paths)
    results = await ingest_from_source(
        source=source,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=setup["embedder"],
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
        max_concurrency=1,
    )
    statuses = sorted(r.status for r in results)
    assert "load_failed" in statuses
    assert source.committed == "cursor-1"
    assert source.commit_call_count == 1


async def test_concurrent_actually_overlaps_work(setup: dict[str, Any]) -> None:
    """Sanity check that bounded concurrency lets work overlap.

    We instrument the embedder to track in-flight count and assert it
    reaches >1 at some point. Avoids wall-clock timing flakes.
    """
    paths = _write_files(setup["tmp_path"], 4)
    source = _FakeSource(paths)

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    class _ConcurrencyTrackingEmbedder:
        async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            try:
                # Yield control so other tasks can also enter and bump in_flight.
                await asyncio.sleep(0.01)
                return EmbeddingResult(
                    embeddings=[[1.0, 0.0, 0.0, 0.0] for _ in texts],
                    model="track",
                    usage=None,
                    dimensions=4,
                )
            finally:
                async with lock:
                    in_flight -= 1

        async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
            return [1.0, 0.0, 0.0, 0.0]

    results = await ingest_from_source(
        source=source,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=_ConcurrencyTrackingEmbedder(),
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
        max_concurrency=4,
    )
    assert len(results) == 4
    assert max_in_flight > 1, f"expected overlap, max_in_flight={max_in_flight}"
    assert max_in_flight <= 4, f"semaphore breach, max_in_flight={max_in_flight}"


async def test_concurrency_does_not_exceed_bound(setup: dict[str, Any]) -> None:
    """With max_concurrency=2, no more than 2 ingestions run simultaneously."""
    paths = _write_files(setup["tmp_path"], 8)
    source = _FakeSource(paths)

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    class _BoundedEmbedder:
        async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            try:
                await asyncio.sleep(0.005)
                return EmbeddingResult(
                    embeddings=[[1.0, 0.0, 0.0, 0.0] for _ in texts],
                    model="b",
                    usage=None,
                    dimensions=4,
                )
            finally:
                async with lock:
                    in_flight -= 1

        async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
            return [1.0, 0.0, 0.0, 0.0]

    await ingest_from_source(
        source=source,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=_BoundedEmbedder(),
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
        max_concurrency=2,
    )
    assert max_in_flight <= 2, f"exceeded max_concurrency: {max_in_flight}"
