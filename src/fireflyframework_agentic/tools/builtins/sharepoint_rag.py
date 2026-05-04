# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""SharePoint → RAG tools exposed via MCP.

Two tools:

- ``ingest_sharepoint``: pull all changed files from a SharePoint drive and
  ingest them into a corpus (chunk → embed → upsert).
- ``query_corpus``: hybrid retrieval (BM25 + dense) over a corpus, returning
  the matching chunks with citations.

State note: the in-memory vector store is per-process and ephemeral. When
the blob-backed vector store lands (Javi's work) this module should swap
it in. Likewise, ``ingest_sharepoint`` becomes useful only once the
SharePoint source merges to ``main`` — until then the import-guard at the
top of the file marks it unavailable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from azure.identity.aio import ManagedIdentityCredential

from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.embeddings.providers.openai import OpenAIEmbedder
from fireflyframework_agentic.rag.corpus import SqliteCorpus
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.pipeline import ingest_one
from fireflyframework_agentic.rag.retrieval.hybrid import HybridRetriever
from fireflyframework_agentic.tools.decorators import firefly_tool
from fireflyframework_agentic.vectorstores.memory_store import InMemoryVectorStore

try:
    from fireflyframework_agentic.content.sources.sharepoint import (  # pyright: ignore[reportMissingImports]
        SharePointSource,
        SharePointSourceConfig,
    )

    _SHAREPOINT_AVAILABLE = True
except ImportError:  # pragma: no cover — branch not yet merged
    SharePointSource = None  # type: ignore[assignment,misc]
    SharePointSourceConfig = None  # type: ignore[assignment,misc]
    _SHAREPOINT_AVAILABLE = False

log = logging.getLogger(__name__)


# In-process registry of corpus_id → (corpus, vector_store, ledger).
# Replace the InMemoryVectorStore with the blob-backed one once it lands.
_CORPORA: dict[str, tuple[SqliteCorpus, InMemoryVectorStore, IngestLedger]] = {}
_CORPUS_ROOT = Path("/tmp/firefly/corpora")
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


async def _get_or_create(corpus_id: str) -> tuple[SqliteCorpus, InMemoryVectorStore, IngestLedger]:
    if corpus_id in _CORPORA:
        return _CORPORA[corpus_id]
    _CORPUS_ROOT.mkdir(parents=True, exist_ok=True)
    corpus = SqliteCorpus(_CORPUS_ROOT / f"{corpus_id}.db")
    await corpus.initialise()
    store = InMemoryVectorStore()
    ledger = IngestLedger(corpus)
    _CORPORA[corpus_id] = (corpus, store, ledger)
    return _CORPORA[corpus_id]


def _embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder(model="text-embedding-3-small")


@firefly_tool(
    "ingest_sharepoint",
    description=(
        "Ingest all changed files from a SharePoint drive into a corpus. "
        "Auth uses the Container App's managed identity to obtain a Microsoft "
        "Graph token. Returns counts of ingested, skipped, and failed documents."
    ),
    tags=("rag", "sharepoint", "ingest"),
)
async def ingest_sharepoint(
    drive_id: str,
    corpus_id: str,
    root_folder: str | None = None,
) -> dict[str, Any]:
    if not _SHAREPOINT_AVAILABLE:
        raise RuntimeError(
            "SharePointSource is not yet available in this build. Pending merge "
            "of feat/content-sources-sharepoint into main."
        )

    corpus, store, ledger = await _get_or_create(corpus_id)
    chunker = TextChunker(chunk_size=4000, chunk_overlap=200)
    loader = MarkitdownLoader()
    embedder = _embedder()

    cache_dir = _CORPUS_ROOT / corpus_id / "cache"
    delta_file = _CORPUS_ROOT / corpus_id / "delta.json"
    config = SharePointSourceConfig(  # type: ignore[misc]
        drive_id=drive_id,
        root_folder=root_folder,
        cache_dir=cache_dir,
        delta_file=delta_file,
    )

    credential = ManagedIdentityCredential()

    async def token_provider() -> str:
        token = await credential.get_token(_GRAPH_SCOPE)
        return token.token

    counts = {"ingested": 0, "skipped": 0, "failed": 0}
    async with SharePointSource(config, token_provider=token_provider) as source:  # type: ignore[misc]
        cursor = await source.current_cursor()
        async for raw in source.list_changed(cursor):
            try:
                local_path = await source.fetch(raw)
            except Exception as exc:  # noqa: BLE001
                log.warning("fetch failed for %s: %s", raw, exc)
                counts["failed"] += 1
                continue

            result = await ingest_one(
                path=local_path,
                corpus=corpus,
                vector_store=store,
                embedder=embedder,
                ledger=ledger,
                chunker=chunker,
                loader=loader,
            )
            if result.status == "success":
                counts["ingested"] += 1
            elif result.status == "skipped":
                counts["skipped"] += 1
            else:
                counts["failed"] += 1

        new_cursor = await source.pending_cursor()
        if new_cursor:
            await source.commit_delta(new_cursor)

    await credential.close()
    return {"corpus_id": corpus_id, **counts}


@firefly_tool(
    "query_corpus",
    description=(
        "Run a hybrid (BM25 + dense vector) retrieval over a corpus and return "
        "the top-K matching chunks with their source path, score, and metadata."
    ),
    tags=("rag", "query"),
)
async def query_corpus(
    corpus_id: str,
    question: str,
    top_k: int = 5,
) -> dict[str, Any]:
    if corpus_id not in _CORPORA:
        return {"corpus_id": corpus_id, "hits": [], "warning": "corpus not found"}

    corpus, store, _ = _CORPORA[corpus_id]
    retriever = HybridRetriever(corpus=corpus, vector_store=store, embedder=_embedder())
    hits = await retriever.retrieve([question], top_k_final=top_k)
    return {
        "corpus_id": corpus_id,
        "question": question,
        "hits": [
            {
                "chunk_id": h.chunk_id,
                "score": h.score,
                "content": h.content,
                "source_path": h.source_path,
                "metadata": h.metadata,
            }
            for h in hits
        ],
    }


__all__ = ["ingest_sharepoint", "query_corpus"]
