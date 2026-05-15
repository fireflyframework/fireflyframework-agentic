# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Corpus RAG tools exposed via MCP.

Eight tools:
    - list_corpora()
    - ingest_corpus_filesystem(corpus_id, root_path)
    - discover_corpus_schema(corpus_id, path)
    - ingest_corpus_structured(corpus_id, path, schema?)
    - knowledge_search(corpus_id, question, top_k)
    - corpus_query(corpus_id, question, top_k)
    - list_corpus_schemas(corpus_id)
    - corpus_sql(corpus_id, sql, params?, limit?)

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
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

# sqlglot is only required by ``corpus_sql`` — it ships in the
# ``corpus-search`` extra alongside the rest of this tool's runtime
# stack. Other tools in this module (``knowledge_search``,
# ``ingest_corpus_filesystem``, …) work without it, so we tolerate
# its absence at import time and surface a clear error inside the SQL
# tool's validator if a caller actually exercises that code path
# without the extra installed.
try:
    import sqlglot
    from sqlglot import exp as sqlglot_exp
    from sqlglot.errors import ParseError as _SqlglotParseError
except ImportError:  # pragma: no cover - exercised only when the extra is missing
    sqlglot = None  # type: ignore[assignment]
    sqlglot_exp = None  # type: ignore[assignment]
    _SqlglotParseError = Exception  # type: ignore[assignment,misc]

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

_AGENT_CACHE: dict[tuple[str, str], CorpusAgent] = {}
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


async def _agent_for(
    corpus_id: str,
    *,
    strategy: Literal["fast", "reasoning"] = "fast",
) -> CorpusAgent:
    """Return a process-wide CorpusAgent for *(corpus_id, strategy)*, creating
    one on first use.

    Sharing the agent means sharing its DatabaseStore / LocalBackend /
    SqliteCorpus connections so the asyncio.Lock inside the backend actually
    serialises writes from multiple tool calls in the same process.
    Construction is sync and does no I/O (no SQLite open until the agent's
    first ensure_corpus_ready) so holding _CACHE_LOCK across it is harmless.

    Cache key includes the strategy so the same process can serve both the
    fast and reasoning paths for the same corpus without one tearing down
    the other's lazily-constructed retrieval components.
    """
    key = (corpus_id, strategy)
    async with _CACHE_LOCK:
        if key not in _AGENT_CACHE:
            _AGENT_CACHE[key] = CorpusAgent(
                root=_corpus_root() / corpus_id,
                embed_model=os.environ["EMBEDDING_MODEL"],
                expansion_model=os.environ["EXPANSION_MODEL"],
                answer_model=os.environ["ANSWER_MODEL"],
                rerank_model=os.environ["RERANK_MODEL"],
                answer_strategy=strategy,
            )
        return _AGENT_CACHE[key]


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
    for (corpus_id, strategy), agent in items:
        try:
            await agent.close()
        except Exception:
            log.warning(
                "failed to close cached CorpusAgent corpus_id=%s strategy=%s during shutdown",
                corpus_id,
                strategy,
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
        "Run the corpus pipeline and return a grounded answer with inline "
        "citations. Raises if corpus_id is unknown.\n\n"
        "strategy='fast' (default): one-shot expand→retrieve→rerank→answer "
        "pipeline. Cheapest, one LLM call. Existing behaviour.\n\n"
        "strategy='reasoning': tool-using agent that plans its own retrieval "
        "and can call knowledge_search, sql_query, inspect_table, and a "
        "restricted python_compute sandbox. More LLM turns, more capable on "
        "multi-step / quantitative questions. The response includes a typed "
        "ReasoningTrace by default (include_trace=true) — every ActionStep "
        "carries tool_name + tool_args and can be re-executed manually to "
        "reproduce the answer. Pass include_trace=false to suppress it "
        "(smaller payload). The fast path never carries a trace regardless "
        "of include_trace, so existing fast-path response shapes are "
        "unchanged."
    ),
    tags=("rag", "query"),
)
async def corpus_query(
    corpus_id: str,
    question: str,
    top_k: int = 5,
    strategy: Literal["fast", "reasoning"] = "fast",
    include_trace: bool = True,
) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    agent = await _agent_for(corpus_id, strategy=strategy)
    answer = await agent.query(question, top_k=top_k, include_trace=include_trace)
    payload: dict[str, Any] = {
        "corpus_id": corpus_id,
        "question": question,
        "answer": answer.text,
        "citations": answer.citations,
        "cited_sources": [
            {"chunk_id": c.chunk_id, "source_path": c.source_path, "snippet": c.snippet} for c in answer.cited_sources
        ],
    }
    # Trace only attaches when the reasoning path produced one — on the fast
    # path ``answer.reasoning_trace`` is always None, so the legacy response
    # shape is preserved by construction.
    if include_trace and answer.reasoning_trace is not None:
        payload["reasoning_trace"] = answer.reasoning_trace.model_dump(mode="json")
    return payload


# ---------- structured-data introspection ----------------------------------

_CORPUS_SQL_DEFAULT_LIMIT = 100
_CORPUS_SQL_MAX_LIMIT = 1000


@firefly_tool(
    "list_corpus_schemas",
    description=(
        "List every structured table registered in the corpus via "
        "ingest_corpus_structured. Returns the column definitions (name, type, "
        "nullable, primary_key, foreign_key, unit) for each table. Returns an "
        "empty 'tables' list when the corpus contains only unstructured "
        "documents. Read-only; no LLM calls. Use this to discover what "
        "structured data is queryable via corpus_sql."
    ),
    tags=("rag", "structured", "discovery"),
)
async def list_corpus_schemas(corpus_id: str) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    agent = await _agent_for(corpus_id)
    schemas = await agent.list_schemas()
    tables: list[dict[str, Any]] = []
    for schema in schemas:
        for table in schema.tables:
            tables.append(table.model_dump(mode="json"))
    return {"corpus_id": corpus_id, "tables": tables}


def _structured_table_names(schemas: list[TargetSchema]) -> set[str]:
    """Return the names of every table registered by structured ingestion."""
    return {t.name for s in schemas for t in s.tables}


def _validate_select(sql: str, allowed_tables: set[str]) -> tuple[Any, list[str]] | str:
    """Parse *sql* and ensure it is a single SELECT against allowed tables.

    Returns the parsed expression and the list of referenced table names on
    success, or a human-readable error string on rejection. We use the
    'sqlite' dialect so SQLite-specific syntax (e.g. ``UNION``, window
    functions, JSON1 operators) parses without spurious errors.

    Rejections are all read-only safety nets — the connection itself is
    opened in ``mode=ro`` so writes physically cannot land — but they
    surface clear errors to the caller instead of an opaque SQLite
    ``attempt to write a readonly database``.
    """
    if sqlglot is None or sqlglot_exp is None:
        return (
            "sqlglot is required for corpus_sql; install the `corpus-search` "
            "extra (e.g. `pip install 'fireflyframework-agentic[corpus-search]'`)"
        )
    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except _SqlglotParseError as exc:
        return f"SQL parse error: {exc}"
    statements = [s for s in statements if s is not None]
    if not statements:
        return "SQL must contain exactly one statement; got none."
    if len(statements) > 1:
        return f"SQL must contain exactly one statement; got {len(statements)}."
    root = statements[0]
    if not isinstance(root, sqlglot_exp.Select):
        return f"Only SELECT statements are allowed; got {type(root).__name__.upper()}."
    referenced: list[str] = []
    for table in root.find_all(sqlglot_exp.Table):
        # ``table.name`` strips quoting; ``table.db`` would carry a schema
        # qualifier (none expected for sqlite single-DB) and we reject it
        # for predictability.
        if table.db:
            return f"Schema-qualified table references are not allowed: {table.sql()}"
        name = table.name
        if name not in allowed_tables:
            return (
                f"Table '{name}' is not part of this corpus's structured "
                f"schema. Allowed tables: {sorted(allowed_tables) or '(none — corpus has no structured data)'}"
            )
        referenced.append(name)
    return root, referenced


def _execute_select_readonly(db_path: Path, sql: str, params: dict[str, Any] | None, limit: int) -> dict[str, Any]:
    """Run *sql* against a read-only connection and return shaped results.

    The connection is opened via ``mode=ro`` so SQLite refuses any write,
    regardless of what the parser missed. Returns rows as ``list[dict]``
    and signals truncation when more rows than *limit* matched.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params or {})
        # Pull limit+1 so we can tell the caller whether they hit the cap
        # without re-running a COUNT query.
        fetched = cur.fetchmany(limit + 1)
        truncated = len(fetched) > limit
        kept = fetched[:limit]
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(r) for r in kept]
    finally:
        conn.close()
    return {"columns": columns, "rows": rows, "truncated": truncated}


@firefly_tool(
    "corpus_sql",
    description=(
        "Run a single SELECT statement against the corpus's structured "
        "tables (the ones registered via ingest_corpus_structured) and return "
        "raw rows. No LLM involvement: results are deterministic.\n\n"
        "Safety:\n"
        "  - The connection is opened read-only (SQLite mode=ro); INSERT / "
        "UPDATE / DELETE / DDL physically cannot land.\n"
        "  - Only SELECT is accepted; the SQL is parsed with sqlglot.\n"
        "  - Only tables registered via ingest_corpus_structured are "
        "queryable. Internal tables (chunks, _schemas, ingestions, etc.) "
        "are rejected. Call list_corpus_schemas first to see what tables "
        "are available.\n"
        "  - Bind variables via the optional `params` dict (named or "
        "qmark style) — do not interpolate user input into the SQL string.\n"
        "  - At most `limit` rows are returned (default 100, max 1000); "
        "the response carries `truncated=true` if more matched."
    ),
    tags=("rag", "structured", "query"),
)
async def corpus_sql(
    corpus_id: str,
    sql: str,
    params: dict[str, Any] | None = None,
    limit: int = _CORPUS_SQL_DEFAULT_LIMIT,
) -> dict[str, Any]:
    sqlite_path = _assert_corpus_exists(corpus_id)
    if limit <= 0:
        raise ValueError("limit must be positive")
    capped_limit = min(limit, _CORPUS_SQL_MAX_LIMIT)
    agent = await _agent_for(corpus_id)
    schemas = await agent.list_schemas()
    allowed = _structured_table_names(schemas)
    validation = _validate_select(sql, allowed)
    if isinstance(validation, str):
        raise ValueError(validation)
    _, referenced_tables = validation
    result = await asyncio.to_thread(_execute_select_readonly, sqlite_path, sql, params, capped_limit)
    return {
        "corpus_id": corpus_id,
        "sql": sql,
        "tables": sorted(set(referenced_tables)),
        **result,
    }


__all__ = [
    "corpus_query",
    "corpus_sql",
    "discover_corpus_schema",
    "ingest_corpus_filesystem",
    "ingest_corpus_structured",
    "knowledge_search",
    "list_corpora",
    "list_corpus_schemas",
]
