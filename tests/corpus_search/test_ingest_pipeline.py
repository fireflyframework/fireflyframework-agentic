from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from examples.corpus_search.corpus import SqliteCorpus
from examples.corpus_search.ingest.ledger import IngestLedger
from examples.corpus_search.ingest.pipeline import (
    IngestionResult,
    ingest_one,
)
from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.embeddings.types import EmbeddingResult

# --- Stubs ----------------------------------------------------------------


class _StubEmbedder:
    """Returns deterministic 4-dim vectors based on text length."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.fail = False

    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        if self.fail:
            raise RuntimeError("embed boom")
        self.calls.append(list(texts))
        return EmbeddingResult(
            embeddings=[[float(len(t)), 0.0, 0.0, 0.0] for t in texts],
            model="stub",
            usage=None,
            dimensions=4,
        )

    async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


class _StubVectorStore:
    """In-memory vector store recording upsert/delete calls."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.upsert_calls: list[list[str]] = []
        self.delete_calls: list[list[str]] = []

    async def upsert(self, documents: Sequence[Any], namespace: str = "default") -> None:
        ids = []
        for d in documents:
            # Match the framework's VectorDocument shape — `.text`, not `.content`.
            self.docs[d.id] = {
                "embedding": d.embedding,
                "text": d.text,
                "metadata": d.metadata,
            }
            ids.append(d.id)
        self.upsert_calls.append(ids)

    async def delete(self, ids: Sequence[str], namespace: str = "default") -> None:
        for i in ids:
            self.docs.pop(i, None)
        self.delete_calls.append(list(ids))


# --- Fixtures -------------------------------------------------------------


@pytest.fixture
async def setup(tmp_path):
    corpus = SqliteCorpus(tmp_path / "corpus.sqlite")
    await corpus.initialise()
    ledger = IngestLedger(corpus)
    embedder = _StubEmbedder()
    vector_store = _StubVectorStore()
    chunker = TextChunker(chunk_size=80, chunk_overlap=10)
    loader = MarkitdownLoader()
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


def _write_md(folder: Path, name: str, content: str) -> Path:
    p = folder / name
    p.write_text(content)
    return p


# --- Tests ----------------------------------------------------------------


async def test_ingest_one_writes_chunks_and_vectors_and_ledger(setup):
    path = _write_md(setup["tmp_path"], "doc.txt", "Hello world. This is a small text.")
    result = await ingest_one(
        path=path,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=setup["embedder"],
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
    )
    assert isinstance(result, IngestionResult)
    assert result.status == "success"
    assert result.n_chunks >= 1

    chunk_rows = await setup["corpus"].query("SELECT chunk_id, doc_id FROM chunks")
    assert len(chunk_rows) == result.n_chunks
    assert all(r["doc_id"] == result.doc_id for r in chunk_rows)

    # Vector store has one entry per chunk
    assert len(setup["vector_store"].docs) == result.n_chunks

    # Ledger row written
    ingestions = await setup["corpus"].query(
        "SELECT status, content_hash FROM ingestions WHERE doc_id = :id",
        {"id": result.doc_id},
    )
    assert ingestions[0]["status"] == "success"


async def test_re_ingest_same_hash_returns_skipped(setup):
    path = _write_md(setup["tmp_path"], "doc.txt", "Stable content here.")
    first = await ingest_one(path=path, **{k: setup[k] for k in ("corpus", "vector_store", "embedder", "ledger", "chunker", "loader")})
    assert first.status == "success"
    second = await ingest_one(path=path, **{k: setup[k] for k in ("corpus", "vector_store", "embedder", "ledger", "chunker", "loader")})
    assert second.status == "skipped"
    assert second.n_chunks == 0


async def test_re_ingest_changed_hash_replaces_chunks(setup):
    path = _write_md(setup["tmp_path"], "doc.txt", "Original content.")
    first = await ingest_one(path=path, **{k: setup[k] for k in ("corpus", "vector_store", "embedder", "ledger", "chunker", "loader")})
    assert first.status == "success"

    # Change file -> different hash
    path.write_text("Brand new content that is much longer to produce different chunks.")
    second = await ingest_one(path=path, **{k: setup[k] for k in ("corpus", "vector_store", "embedder", "ledger", "chunker", "loader")})
    assert second.status == "success"
    # Old chunks gone, only new ones in corpus
    rows = await setup["corpus"].query("SELECT chunk_id FROM chunks WHERE doc_id = :id", {"id": second.doc_id})
    assert len(rows) == second.n_chunks
    # Vector store re-populated, no leftover from first run
    assert len(setup["vector_store"].docs) == second.n_chunks


async def test_load_failed_records_in_ledger_and_returns(setup):
    missing = setup["tmp_path"] / "does-not-exist.pdf"
    result = await ingest_one(
        path=missing,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=setup["embedder"],
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
    )
    assert result.status == "load_failed"
    assert result.n_chunks == 0
    rows = await setup["corpus"].query("SELECT status FROM ingestions WHERE doc_id = :id", {"id": result.doc_id})
    assert rows[0]["status"] == "load_failed"
    # No chunks or vectors written
    assert await setup["corpus"].query("SELECT * FROM chunks") == []
    assert setup["vector_store"].docs == {}


async def test_embed_failure_marks_failed_and_cleans_up(setup):
    path = _write_md(setup["tmp_path"], "doc.txt", "Some content for embedding.")
    setup["embedder"].fail = True
    result = await ingest_one(
        path=path,
        corpus=setup["corpus"],
        vector_store=setup["vector_store"],
        embedder=setup["embedder"],
        ledger=setup["ledger"],
        chunker=setup["chunker"],
        loader=setup["loader"],
    )
    assert result.status == "failed"
    assert await setup["corpus"].query("SELECT * FROM chunks") == []
    assert setup["vector_store"].docs == {}
    rows = await setup["corpus"].query("SELECT status FROM ingestions WHERE doc_id = :id", {"id": result.doc_id})
    assert rows[0]["status"] == "failed"


# --- Regression: vector-store delete failure during re-ingest -----------


class _FlakyDeleteVectorStore(_StubVectorStore):
    """Vector store whose ``delete`` raises the first time but lets ``upsert``
    succeed. Simulates a transient vector-store failure during re-ingest
    cleanup of prior chunks (Issue 8 from the code review)."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_failures = 1

    async def delete(self, ids, namespace: str = "default") -> None:
        if self.delete_failures > 0:
            self.delete_failures -= 1
            raise RuntimeError("simulated vector-store delete blip")
        await super().delete(ids, namespace)


async def test_re_ingest_proceeds_when_prior_vector_delete_fails(tmp_path):
    """If the vector store's delete-of-prior-chunks blips during re-ingest,
    the corpus should still be reset and re-ingest should still complete.
    Orphan vectors are acceptable (they get overwritten by the new upsert)."""
    corpus = SqliteCorpus(tmp_path / "corpus.sqlite")
    await corpus.initialise()
    try:
        ledger = IngestLedger(corpus)
        embedder = _StubEmbedder()
        vector_store = _FlakyDeleteVectorStore()
        chunker = TextChunker(chunk_size=80, chunk_overlap=10)
        loader = MarkitdownLoader()

        path = tmp_path / "doc.txt"
        path.write_text("Original content.")
        first = await ingest_one(
            path=path, corpus=corpus, vector_store=vector_store,
            embedder=embedder, ledger=ledger, chunker=chunker, loader=loader,
        )
        assert first.status == "success"

        # Re-ingest with changed content. The flaky delete will raise once,
        # but the pipeline should log and proceed, not propagate.
        path.write_text("Brand new content here.")
        second = await ingest_one(
            path=path, corpus=corpus, vector_store=vector_store,
            embedder=embedder, ledger=ledger, chunker=chunker, loader=loader,
        )
        assert second.status == "success"

        # Corpus reflects the new content (no leftover from the original).
        rows = await corpus.query("SELECT content FROM chunks WHERE doc_id = :id", {"id": second.doc_id})
        assert len(rows) >= 1
        assert "Brand new content" in rows[0]["content"]
    finally:
        await corpus.close()
