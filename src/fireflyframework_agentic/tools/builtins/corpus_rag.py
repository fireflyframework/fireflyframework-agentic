# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Corpus RAG tools exposed via MCP.

Six tools:
    - list_corpora()
    - ingest_corpus_filesystem(corpus_id, root_path)
    - ingest_corpus_structured(corpus_id, path)
    - ingest_corpus_sharepoint(corpus_id, drive_id, root_folder?)
    - corpus_retrieve(corpus_id, question, top_k)
    - corpus_query(corpus_id, question, top_k)

Each call constructs a fresh CorpusAgent rooted at
``CORPUS_ROOT/<corpus_id>`` and delegates. No process-global registry; the
on-disk SqliteCorpus + SqliteVec carry continuity across requests.

Auth: SharePoint ingestion uses the framework's managed-identity token
provider against Microsoft Graph (zero-trust model — see
:mod:`fireflyframework_agentic.security.azure`).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)
from fireflyframework_agentic.rag import CorpusAgent, CorpusNotFoundError
from fireflyframework_agentic.tools.decorators import firefly_tool

_DEFAULT_CORPUS_ROOT = "/tmp/firefly/corpora"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def _corpus_root() -> Path:
    return Path(os.path.expandvars(os.environ.get("CORPUS_ROOT", _DEFAULT_CORPUS_ROOT)))


def _agent_for(corpus_id: str) -> CorpusAgent:
    """Construct an agent rooted at ``CORPUS_ROOT/<corpus_id>``."""
    return CorpusAgent(
        root=_corpus_root() / corpus_id,
        embed_model=os.environ["EMBEDDING_MODEL"],
        expansion_model=os.environ["EXPANSION_MODEL"],
        answer_model=os.environ["ANSWER_MODEL"],
        rerank_model=os.environ["RERANK_MODEL"],
    )


def _assert_corpus_exists(corpus_id: str) -> Path:
    """Raise CorpusNotFoundError if no SQLite file at the expected path."""
    sqlite_path = _corpus_root() / corpus_id / "corpus.sqlite"
    if not sqlite_path.exists():
        raise CorpusNotFoundError(corpus_id, str(sqlite_path))
    return sqlite_path


# ---------- discovery ------------------------------------------------------


@firefly_tool(
    "list_corpora",
    description=(
        "List every corpus_id available on this server. A corpus_id is the name "
        "of a subdirectory of CORPUS_ROOT that contains a corpus.sqlite file. "
        "Call this first when you don't know which corpus to query. Returns "
        "an empty list if CORPUS_ROOT does not exist or contains no corpora."
    ),
    tags=("rag", "discovery"),
)
async def list_corpora() -> dict[str, Any]:
    root = _corpus_root()
    corpora: list[dict[str, Any]] = []
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            sqlite_path = entry / "corpus.sqlite"
            if not (entry.is_dir() and sqlite_path.is_file()):
                continue
            st = sqlite_path.stat()
            corpora.append(
                {
                    "corpus_id": entry.name,
                    "size_bytes": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
                }
            )
    return {"corpus_root": str(root), "corpora": corpora}


# ---------- ingest ---------------------------------------------------------


@firefly_tool(
    "ingest_corpus_filesystem",
    description=(
        "Ingest every (non-hidden) file under root_path into the corpus identified "
        "by corpus_id. Idempotent: unchanged files are skipped via content-hash "
        "deduplication. Returns counts of ingested / skipped / failed documents."
    ),
    tags=("rag", "ingest", "filesystem"),
)
async def ingest_corpus_filesystem(corpus_id: str, root_path: str) -> dict[str, Any]:
    source = LocalFolderSource(LocalFolderSourceConfig(folder=Path(root_path)))
    async with _agent_for(corpus_id) as agent:
        summary = await agent.ingest_source(source)
    return {
        "corpus_id": corpus_id,
        "ingested": summary.ingested,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "cursor": summary.cursor,
    }


@firefly_tool(
    "ingest_corpus_structured",
    description=(
        "Ingest CSV / Excel files at path into the corpus identified by "
        "corpus_id as STRUCTURED data: schema is inferred via LLM, rows are "
        "loaded into normalised SQLite tables, and subsequent corpus_query "
        "calls run text-to-SQL alongside hybrid retrieval over the corpus's "
        "unstructured chunks. path may be a single file or a folder (the "
        "folder is walked recursively and every non-hidden file is treated "
        "as a tabular source). Idempotent: files already recorded in the "
        "ledger are skipped. Schema discovery and SQL generation issue real "
        "LLM calls so this tool is more expensive than ingest_corpus_filesystem."
    ),
    tags=("rag", "ingest", "filesystem", "structured"),
)
async def ingest_corpus_structured(corpus_id: str, path: str) -> dict[str, Any]:
    target = Path(path)
    async with _agent_for(corpus_id) as agent:
        if target.is_file():
            results = [await agent.ingest_one(target, mode="structured")]
        else:
            summary = await agent.ingest_folder(target, mode="structured")
            results = summary.results
    ingested = sum(1 for r in results if r.status == "success")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status not in {"success", "skipped"})
    return {
        "corpus_id": corpus_id,
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
    }


@firefly_tool(
    "ingest_corpus_sharepoint",
    description=(
        "Ingest every changed file from a SharePoint drive into the corpus "
        "identified by corpus_id. Auth uses the runtime's managed identity to "
        "obtain a Microsoft Graph token. Returns counts of ingested / skipped / "
        "failed documents and the new delta cursor."
    ),
    tags=("rag", "ingest", "sharepoint"),
)
async def ingest_corpus_sharepoint(
    corpus_id: str,
    drive_id: str,
    root_folder: str | None = None,
) -> dict[str, Any]:
    from azure.identity.aio import ManagedIdentityCredential

    from fireflyframework_agentic.content.sources.sharepoint import (
        SharePointSource,
        SharePointSourceConfig,
    )

    cache_dir = _corpus_root() / corpus_id / "sharepoint" / "cache"
    delta_file = _corpus_root() / corpus_id / "sharepoint" / "delta.json"
    cache_dir.mkdir(parents=True, exist_ok=True)

    config = SharePointSourceConfig(
        drive_id=drive_id,
        root_folder=root_folder,
        cache_dir=cache_dir,
        delta_file=delta_file,
    )
    credential = ManagedIdentityCredential()

    async def token_provider() -> str:
        token = await credential.get_token(_GRAPH_SCOPE)
        return token.token

    try:
        async with (
            SharePointSource(config, token_provider=token_provider) as source,
            _agent_for(corpus_id) as agent,
        ):
            summary = await agent.ingest_source(source)
    finally:
        await credential.close()

    return {
        "corpus_id": corpus_id,
        "ingested": summary.ingested,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "cursor": summary.cursor,
    }


# ---------- retrieve / query -----------------------------------------------


@firefly_tool(
    "corpus_retrieve",
    description=(
        "Run hybrid retrieval (BM25 + dense) with optional reranking over a "
        "corpus and return the top-K matching chunks with score, source path, "
        "and metadata. No LLM answer generation. Raises if corpus_id is unknown."
    ),
    tags=("rag", "query"),
)
async def corpus_retrieve(corpus_id: str, question: str, top_k: int = 5) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    async with _agent_for(corpus_id) as agent:
        hits = await agent.retrieve(question, top_k=top_k, rerank=True)
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


@firefly_tool(
    "corpus_query",
    description=(
        "Run the full corpus pipeline (expand → retrieve → rerank → answer) and "
        "return a grounded answer with inline citations. Raises if corpus_id is "
        "unknown."
    ),
    tags=("rag", "query"),
)
async def corpus_query(corpus_id: str, question: str, top_k: int = 5) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    async with _agent_for(corpus_id) as agent:
        answer = await agent.query(question, top_k=top_k)
    return {
        "corpus_id": corpus_id,
        "question": question,
        "answer": answer.text,
        "citations": answer.citations,
        "cited_sources": [
            {"chunk_id": c.chunk_id, "source_path": c.source_path, "snippet": c.snippet} for c in answer.cited_sources
        ],
    }


__all__ = [
    "corpus_query",
    "corpus_retrieve",
    "ingest_corpus_filesystem",
    "ingest_corpus_sharepoint",
    "ingest_corpus_structured",
    "list_corpora",
]
