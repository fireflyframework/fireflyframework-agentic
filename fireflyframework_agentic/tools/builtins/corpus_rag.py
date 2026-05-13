# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Corpus RAG tools exposed via MCP.

Six tools:
    - list_corpora()
    - ingest_corpus_filesystem(corpus_id, root_path)
    - discover_corpus_schema(corpus_id, path)
    - ingest_corpus_structured(corpus_id, path, schema?)
    - knowledge_search(corpus_id, question, top_k)
    - corpus_query(corpus_id, question, top_k)

Each tool resolves a process-wide cached :class:`CorpusAgent` via
``_agent_for(corpus_id)`` so every call against a given corpus shares one
DatabaseStore / LocalBackend / SqliteCorpus (and one ``asyncio.Lock``)
instance. Write tools additionally serialise on a per-corpus
``asyncio.Lock`` from ``_WRITE_LOCKS`` as belt-and-braces against
concurrent writers in the same process. Read tools (``corpus_query`` /
``knowledge_search``) stay lock-free and rely on SQLite WAL for concurrent
reader semantics. Cached agents are torn down via ``_shutdown_agents``,
which the MCP server's lifespan hook is expected to call on shutdown.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)
from fireflyframework_agentic.rag import CorpusAgent, CorpusNotFoundError
from fireflyframework_agentic.rag.ingest import TargetSchema
from fireflyframework_agentic.rag.ingest.structured_registry import is_tabular_file
from fireflyframework_agentic.tools.decorators import firefly_tool

log = logging.getLogger(__name__)

_DEFAULT_CORPUS_ROOT = "/tmp/firefly/corpora"

_AGENT_CACHE: dict[str, CorpusAgent] = {}
_WRITE_LOCKS: dict[str, asyncio.Lock] = {}
_CACHE_LOCK = asyncio.Lock()


def _corpus_root() -> Path:
    return Path(os.path.expandvars(os.environ.get("CORPUS_ROOT", _DEFAULT_CORPUS_ROOT)))


# Populated by CorpusAuthMiddleware when per-corpus auth is enabled. A value
# of ``None`` means "no auth in effect" — discovery returns every corpus on
# disk. A tuple means "the caller is authorised for exactly these corpora";
# discovery filters its output to that set.
authorised_corpora_var: contextvars.ContextVar[tuple[str, ...] | None] = contextvars.ContextVar(
    "authorised_corpora", default=None
)


async def _agent_for(corpus_id: str) -> CorpusAgent:
    """Return a process-wide CorpusAgent for *corpus_id*, creating one on
    first use.

    Sharing the agent means sharing its DatabaseStore / LocalBackend /
    SqliteCorpus connections so the asyncio.Lock inside the backend
    actually serialises writes from multiple tool calls in the same
    process. Construction is sync and does no I/O (no SQLite open until
    the agent's first ensure_corpus_ready) so holding _CACHE_LOCK across
    it is harmless.
    """
    async with _CACHE_LOCK:
        if corpus_id not in _AGENT_CACHE:
            _AGENT_CACHE[corpus_id] = CorpusAgent(
                root=_corpus_root() / corpus_id,
                embed_model=os.environ["EMBEDDING_MODEL"],
                expansion_model=os.environ["EXPANSION_MODEL"],
                answer_model=os.environ["ANSWER_MODEL"],
                rerank_model=os.environ["RERANK_MODEL"],
            )
        return _AGENT_CACHE[corpus_id]


def _write_lock_for(corpus_id: str) -> asyncio.Lock:
    """Return the per-corpus write lock, creating one on first use.

    Belt-and-braces serialisation for write tools at the MCP layer. Reads
    (corpus_query / knowledge_search) do NOT take this lock — they rely on
    SQLite's WAL mode for concurrent reader semantics.

    We can't assume every future writer goes through DatabaseStore.for_write
    (e.g. a sidecar tool opening a raw sqlite3 connection); this lock is at
    the tool boundary so that assumption is no longer load-bearing.

    Uses ``setdefault`` so two concurrent callers with a fresh corpus_id
    converge on a single Lock instance even if a future change introduces
    an ``await`` between the check and the assign.
    """
    return _WRITE_LOCKS.setdefault(corpus_id, asyncio.Lock())


async def _shutdown_agents() -> None:
    """Close every cached agent. Called by the MCP server's lifespan hook.

    Clears the registries BEFORE awaiting close so a tool call that sneaks
    in during shutdown gets a fresh agent rather than a half-closed one.
    """
    items = list(_AGENT_CACHE.items())
    _AGENT_CACHE.clear()
    _WRITE_LOCKS.clear()
    log.debug("shutting down %d cached corpus agent(s)", len(items))
    for corpus_id, agent in items:
        try:
            await agent.close()
        except Exception:
            log.warning(
                "failed to close cached CorpusAgent corpus_id=%s during shutdown",
                corpus_id,
                exc_info=True,
            )


def _assert_corpus_exists(corpus_id: str) -> Path:
    """Raise CorpusNotFoundError if no SQLite file at the expected path."""
    # TODO: this LocalBackend-shaped existence check assumes the corpus.sqlite
    # on disk is canonical. Under AzureBlobBackend the canonical artifact
    # lives in the blob; existence should route through _db_store.ensure_fresh()
    # before consulting the local cache.
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
        "an empty list if CORPUS_ROOT does not exist or contains no corpora. "
        "When per-corpus auth is enabled, the response is filtered to the "
        "corpora the caller's bearer token authorises."
    ),
    tags=("rag", "discovery"),
)
async def list_corpora() -> dict[str, Any]:
    root = _corpus_root()
    corpora: list[dict[str, Any]] = []
    allowed = authorised_corpora_var.get()
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            # TODO: walking the local filesystem assumes LocalBackend
            # semantics where each entry / "corpus.sqlite" is the canonical
            # artifact. Under AzureBlobBackend the source of truth is the
            # blob container; enumeration should query the backend directly
            # rather than CORPUS_ROOT.
            sqlite_path = entry / "corpus.sqlite"
            if not (entry.is_dir() and sqlite_path.is_file()):
                continue
            if allowed is not None and entry.name not in allowed:
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
        "Ingest UNSTRUCTURED documents (PDF, DOCX, PPTX, MD, TXT, HTML, etc.) "
        "under root_path into the corpus identified by corpus_id. "
        "Tabular files (CSV, XLS, XLSX) are EXCLUDED by this tool — for tabular "
        "data call ingest_corpus_structured instead, after discover_corpus_schema. "
        "\n\n"
        "When a folder mixes both kinds (e.g. PPTX decks alongside Excel "
        "workbooks), you must call BOTH this tool (for the documents) AND "
        "ingest_corpus_structured (for the spreadsheets) — neither alone "
        "covers a mixed folder. Order doesn't matter; each tool ignores the "
        "files the other handles. "
        "\n\n"
        "Idempotent: unchanged files are skipped via content-hash deduplication. "
        "Returns counts of ingested / skipped / failed documents."
    ),
    tags=("rag", "ingest", "filesystem"),
)
async def ingest_corpus_filesystem(corpus_id: str, root_path: str) -> dict[str, Any]:
    async with _write_lock_for(corpus_id):
        source = LocalFolderSource(
            LocalFolderSourceConfig(
                folder=Path(root_path),
                exclude_predicate=is_tabular_file,
            )
        )
        agent = await _agent_for(corpus_id)
        summary = await agent.ingest_source(source)
    return {
        "corpus_id": corpus_id,
        "ingested": summary.ingested,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "cursor": summary.cursor,
    }


@firefly_tool(
    "discover_corpus_schema",
    description=(
        "STEP 1 of structured ingestion. Infer a relational schema for the "
        "CSV / Excel file or folder at path WITHOUT ingesting any data. "
        "After calling this tool you MUST present the proposed schema to "
        "the user and ask them to review it — DO NOT pass the result "
        "straight to ingest_corpus_structured without giving the user a "
        "chance to correct it. Schema inference is non-deterministic and "
        "frequently misses domain context (currency on amount columns, "
        "primary/foreign keys spanning sheets, headers that look like data "
        "but aren't, etc.). Reviewed schemas produce far better answers; "
        "unreviewed schemas produce confidently-wrong ones."
        "\n\n"
        "What the user should check:\n"
        "  - Column types (integer / float / boolean / date / datetime / "
        "json / string)\n"
        "  - Primary keys and foreign keys, especially across multiple "
        "sheets or files\n"
        '  - The `unit` field on numeric columns (e.g. "USD", "EUR", '
        '"percent", "headcount", "days"). The discovery LLM only '
        "sets this from clear signals (parenthesised hints, currency "
        "suffixes, etc.); when your data carries an implicit unit the "
        "headers don't spell out, add or correct it manually."
        "\n\n"
        "After the user reviews:\n"
        "  - If they want changes, call this tool AGAIN with "
        "previous_schema=<the prior output> and corrections=<their "
        "free-text feedback>, e.g. 'rename amount to total_due', 'set "
        "unit to USD on revenue', 'mark customer_id as foreign_key to "
        "customers.id', 'date should be date, not string'. Show the new "
        "schema and re-ask for review.\n"
        "  - Once they approve, call ingest_corpus_structured("
        "corpus_id, path, schema=<approved_schema>)."
        "\n\n"
        "For folders, discovery runs across every non-hidden file in one "
        "LLM call so cross-file foreign keys can be proposed. corpus_id "
        "selects which model / config the discovery agent runs under; no "
        "rows or schemas are written to the corpus by this tool."
    ),
    tags=("rag", "ingest", "structured", "schema"),
)
async def discover_corpus_schema(
    corpus_id: str,
    path: str,
    corrections: str = "",
    previous_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = Path(path)
    prior = TargetSchema.model_validate(previous_schema) if previous_schema is not None else None
    agent = await _agent_for(corpus_id)
    schema = await agent.discover_schema(target, corrections=corrections, previous_schema=prior)
    return {
        "corpus_id": corpus_id,
        "path": str(target),
        "schema": schema.model_dump(mode="json"),
    }


@firefly_tool(
    "ingest_corpus_structured",
    description=(
        "STEP 2 of structured ingestion. Ingest CSV / Excel files at path "
        "into the corpus identified by corpus_id as STRUCTURED data: rows "
        "are loaded into normalised SQLite tables, and subsequent "
        "corpus_query calls run text-to-SQL alongside hybrid retrieval "
        "over the corpus's unstructured chunks."
        "\n\n"
        "REQUIRED workflow from an interactive context (chat, MCP host): "
        "ALWAYS pass a user-reviewed schema via the `schema` argument. "
        "The flow is:\n"
        "  1. Call discover_corpus_schema(corpus_id, path).\n"
        "  2. Show the proposed schema to the user.\n"
        "  3. If they want changes, call discover_corpus_schema again "
        "with previous_schema + corrections; loop until they approve.\n"
        "  4. Call this tool with schema=<approved_schema>."
        "\n\n"
        "Calling this tool WITHOUT a schema falls back to running "
        "discovery internally — the result is whatever the LLM infers, "
        "unreviewed, and frequently misses units, types, or foreign "
        "keys. That mode is provided only for non-interactive scripts "
        "where there's no human to review. From a chat or any other "
        "interactive context, you should ALWAYS go through "
        "discover_corpus_schema first so the user can correct the schema."
        "\n\n"
        "path may be a single file or a folder (the folder is walked "
        "recursively and every non-hidden tabular file is treated as a "
        "source). Idempotent: files already recorded in the ledger are "
        "skipped. Schema discovery and SQL generation issue real LLM "
        "calls so this tool is more expensive than ingest_corpus_filesystem. "
        "\n\n"
        "Note on mixed folders: this tool only handles CSV/XLS/XLSX. "
        "For documents (PDF, DOCX, PPTX, MD, …) in the same folder, "
        "you must ALSO call ingest_corpus_filesystem; each tool "
        "ignores the files the other handles."
    ),
    tags=("rag", "ingest", "filesystem", "structured"),
)
async def ingest_corpus_structured(
    corpus_id: str,
    path: str,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with _write_lock_for(corpus_id):
        target = Path(path)
        target_schema = TargetSchema.model_validate(schema) if schema is not None else None
        agent = await _agent_for(corpus_id)
        if target.is_file():
            results = [await agent.ingest_one(target, mode="structured", schema=target_schema)]
        else:
            summary = await agent.ingest_folder(target, mode="structured", schema=target_schema)
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


# ---------- retrieve / query -----------------------------------------------


@firefly_tool(
    "knowledge_search",
    description=(
        "Run hybrid retrieval (BM25 + dense) with optional reranking over a "
        "corpus and return the top-K matching chunks with score, source path, "
        "and metadata. No LLM answer generation. Raises if corpus_id is unknown."
    ),
    tags=("rag", "query"),
)
async def knowledge_search(corpus_id: str, question: str, top_k: int = 5) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    agent = await _agent_for(corpus_id)
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
    agent = await _agent_for(corpus_id)
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
    "discover_corpus_schema",
    "ingest_corpus_filesystem",
    "ingest_corpus_structured",
    "knowledge_search",
    "list_corpora",
]
