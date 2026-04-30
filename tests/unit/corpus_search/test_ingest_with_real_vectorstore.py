# Copyright 2026 Firefly Software Solutions Inc
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

"""Integration test: ingest_one against the framework's SqliteVecVectorStore.

This is the regression test for the `_VectorDoc.content` vs `VectorDocument.text`
bug — the previous duck-type stub silently accepted whatever attribute name the
pipeline produced; the real framework `BaseVectorStore._upsert` accesses
``doc.text`` and would raise `AttributeError` if the field name drifts.

Pairing the unit-level stub tests with at least one test that drives the
*real* `BaseVectorStore` shape catches integration mismatches that pure stubs
miss.
"""

from __future__ import annotations

from typing import Any

import pytest

from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.corpus import SqliteCorpus
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.pipeline import ingest_one
from fireflyframework_agentic.vectorstores.sqlite_vec_store import SqliteVecVectorStore


class _DeterministicEmbedder:
    """Deterministic 4-d vectors keyed off text length — no API call."""

    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        return EmbeddingResult(
            embeddings=[[float(len(t)), 0.0, 0.0, 0.0] for t in texts],
            model="stub",
            usage=None,
            dimensions=4,
        )

    async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


@pytest.fixture
async def deps(tmp_path):
    corpus = SqliteCorpus(tmp_path / "corpus.sqlite")
    await corpus.initialise()
    ledger = IngestLedger(corpus)
    embedder = _DeterministicEmbedder()
    vector_store = SqliteVecVectorStore(db_path=tmp_path / "corpus.sqlite", dimension=4)
    chunker = TextChunker(chunk_size=80, chunk_overlap=10)
    loader = MarkitdownLoader()
    yield {
        "corpus": corpus,
        "ledger": ledger,
        "embedder": embedder,
        "vector_store": vector_store,
        "chunker": chunker,
        "loader": loader,
    }
    await corpus.close()


async def test_ingest_one_works_against_real_inmemory_vectorstore(deps, tmp_path):
    """Regression test: VectorDocument upsert through BaseVectorStore.

    Previously the pipeline produced a duck-typed object with a `.content`
    attribute, but the framework's `BaseVectorStore._upsert` reads `.text`.
    The framework would raise `'_VectorDoc' object has no attribute 'text'`.
    Driving the real `InMemoryVectorStore` catches this kind of attribute drift.
    """
    src = tmp_path / "drop"
    src.mkdir()
    f = src / "doc.txt"
    f.write_text("Hello world. Sam Altman runs OpenAI. The approval workflow is straightforward.")

    result = await ingest_one(
        path=f,
        corpus=deps["corpus"],
        vector_store=deps["vector_store"],
        embedder=deps["embedder"],
        ledger=deps["ledger"],
        chunker=deps["chunker"],
        loader=deps["loader"],
    )

    assert result.status == "success"
    assert result.n_chunks >= 1

    # Vector store actually accepted the upsert and exposes the documents back.
    chunk_rows = await deps["corpus"].query("SELECT chunk_id FROM chunks")
    chunk_ids = sorted(r["chunk_id"] for r in chunk_rows)
    assert len(chunk_ids) == result.n_chunks

    # Round-trip search confirms the vector store accepted the upsert and
    # returns the correct chunk IDs. SqliteVecVectorStore stores only embeddings
    # (text is re-fetched from SqliteCorpus in the RAG path), so we check IDs only.
    qvec = await deps["embedder"].embed_one("hello")
    hits = await deps["vector_store"].search(qvec, top_k=10)
    assert len(hits) >= 1
    for hit in hits:
        assert hit.document.id in chunk_ids
