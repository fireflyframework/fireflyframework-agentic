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

from __future__ import annotations

import contextlib
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.loaders import Document, MarkitdownLoader
from fireflyframework_agentic.embeddings.base import EmbeddingProtocol
from fireflyframework_agentic.rag.corpus import SqliteCorpus, StoredChunk
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.retry import embed_with_retry
from fireflyframework_agentic.vectorstores.base import VectorStoreProtocol
from fireflyframework_agentic.vectorstores.types import VectorDocument

log = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionResult:
    doc_id: str
    source_path: str
    status: str  # 'success' | 'failed' | 'load_failed' | 'skipped'
    n_chunks: int = 0


def _doc_id_for(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(64 * 1024), b""):
            h.update(block)
    return h.hexdigest()


async def ingest_one(
    *,
    path: Path,
    corpus: SqliteCorpus,
    vector_store: VectorStoreProtocol,
    embedder: EmbeddingProtocol,
    ledger: IngestLedger,
    chunker: TextChunker,
    loader: MarkitdownLoader,
) -> IngestionResult:
    """Ingest one document into the corpus + vector store.

    Linear pipeline: load -> hash -> skip-check -> chunk -> reset -> embed
    -> store -> ledger. Each error branch records a status in the ledger and
    returns; cleanup on storage failure attempts to leave a clean state.
    """
    doc_id = _doc_id_for(path)
    source_path = str(path.resolve())

    # 1. Load
    try:
        document: Document = loader.load(path)
    except FileNotFoundError as exc:
        log.warning("load_failed (file not found) for %s: %s", path, exc)
        await ledger.upsert(doc_id, source_path, "", status="load_failed")
        return IngestionResult(doc_id=doc_id, source_path=source_path, status="load_failed", n_chunks=0)
    except Exception as exc:
        log.warning("load_failed for %s: %s", path, exc)
        # Best-effort hash for the ledger entry
        try:
            content_hash = _hash_file(path)
        except Exception:
            content_hash = ""
        await ledger.upsert(doc_id, source_path, content_hash, status="load_failed")
        return IngestionResult(doc_id=doc_id, source_path=source_path, status="load_failed", n_chunks=0)

    # 2. Hash
    content_hash = _hash_file(path)

    # 3. Skip check
    if await ledger.should_skip(doc_id, content_hash):
        return IngestionResult(doc_id=doc_id, source_path=source_path, status="skipped", n_chunks=0)

    # 4. Chunk
    chunks = chunker.chunk(document.content)
    stored_chunks = [
        StoredChunk(
            chunk_id=f"{doc_id}-{i}",
            doc_id=doc_id,
            source_path=source_path,
            index_in_doc=i,
            content=c.content,
            metadata={**document.metadata, "index_in_doc": i},
        )
        for i, c in enumerate(chunks)
    ]

    # 5–7. Reset existing state, embed, upsert. Wrap to clean up on failure.
    try:
        # Pull prior chunk_ids so we can delete them from the vector store.
        prior = await corpus.query(
            "SELECT chunk_id FROM chunks WHERE doc_id = :id",
            {"id": doc_id},
        )
        prior_ids = [r["chunk_id"] for r in prior]
        # The corpus is the source of truth: delete its chunks first, then
        # best-effort the vector store. If the vector store delete blips,
        # we log a warning and proceed — orphan vectors are harmless (they
        # get overwritten on the next successful re-ingest of this doc),
        # whereas leaving the corpus in the prior state would block
        # re-extraction.
        await corpus.delete_by_doc_id(doc_id)
        if prior_ids:
            try:
                await vector_store.delete(prior_ids)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "vector store cleanup failed for prior chunks of doc %s: %s",
                    doc_id,
                    exc,
                )

        if not stored_chunks:
            # No content -> still succeed but with zero chunks.
            await ledger.upsert(doc_id, source_path, content_hash, status="success")
            return IngestionResult(doc_id=doc_id, source_path=source_path, status="success", n_chunks=0)

        emb_result = await embed_with_retry(
            embedder,
            [c.content for c in stored_chunks],
            max_attempts=5,
            initial_delay=1.0,
            max_delay=60.0,
        )
        embeddings = emb_result.embeddings

        await corpus.upsert_chunks(stored_chunks)

        vector_docs = [
            VectorDocument(
                id=c.chunk_id,
                text=c.content,
                embedding=embeddings[i],
                metadata={
                    "doc_id": c.doc_id,
                    "chunk_id": c.chunk_id,
                    "source_path": c.source_path,
                    "index_in_doc": c.index_in_doc,
                },
            )
            for i, c in enumerate(stored_chunks)
        ]
        await vector_store.upsert(vector_docs)

        await ledger.upsert(doc_id, source_path, content_hash, status="success")
        return IngestionResult(
            doc_id=doc_id,
            source_path=source_path,
            status="success",
            n_chunks=len(stored_chunks),
        )

    except Exception as exc:
        log.warning("ingest failed for %s: %s", path, exc)
        # Best-effort cleanup so we don't leave partial state.
        with contextlib.suppress(Exception):
            await corpus.delete_by_doc_id(doc_id)
        ids_to_drop = [c.chunk_id for c in stored_chunks]
        if ids_to_drop:
            with contextlib.suppress(Exception):
                await vector_store.delete(ids_to_drop)
        await ledger.upsert(doc_id, source_path, content_hash, status="failed")
        return IngestionResult(doc_id=doc_id, source_path=source_path, status="failed", n_chunks=0)
