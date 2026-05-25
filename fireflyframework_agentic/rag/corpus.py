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

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fireflyframework_agentic.storage import DatabaseStore, LocalBackend, StorageBackend

if TYPE_CHECKING:
    from fireflyframework_agentic.storage import WriteSession

log = logging.getLogger(__name__)

_DEFAULT_CORPUS_ROOT = "/tmp/firefly/corpora"
_CORPUS_SQLITE_NAME = "corpus.sqlite"


_FTS5_NON_WORD = re.compile(r"[^\w\s]", flags=re.UNICODE)


def sanitize_fts_query(query: str) -> str:
    """Convert a free-text query into a safe FTS5 ``MATCH`` expression.

    FTS5 reserves a number of characters as query syntax (``"``, ``(``, ``)``,
    ``:``, ``*``, ``+``, ``-``, ``^``, ``?``, ``!``, ``,``, ``.``, ``;`` ...).
    A natural-language question like ``"What is the best region?"`` raises
    ``sqlite3.OperationalError: fts5: syntax error near '?'``.

    Strategy:
    - Replace every non-alphanumeric, non-whitespace character with a space.
    - Tokenise on whitespace; drop empty tokens.
    - Wrap each token in double quotes (FTS5 phrase syntax for a single token
      = literal token; cheap insurance against any tokens that happen to match
      reserved keywords like ``OR`` / ``AND`` / ``NOT``).
    - Join with `` OR `` so any doc containing any of the words can match;
      BM25 ranks by relevance, so common stopwords sink naturally via IDF.

    Returns an empty string if no tokens survive — callers must treat that
    as "no FTS hits" rather than passing the empty string to ``MATCH``.
    """
    if not query:
        return ""
    cleaned = _FTS5_NON_WORD.sub(" ", query)
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id      TEXT PRIMARY KEY,
  doc_id        TEXT NOT NULL,
  source_path   TEXT NOT NULL,
  index_in_doc  INTEGER NOT NULL,
  content       TEXT NOT NULL,
  metadata      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  content,
  content='chunks',
  content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
  INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE IF NOT EXISTS ingestions (
  doc_id              TEXT PRIMARY KEY,
  source_path         TEXT NOT NULL,
  content_hash        TEXT NOT NULL,
  status              TEXT NOT NULL,
  ingested_at         TEXT NOT NULL,
  attempt             INTEGER NOT NULL DEFAULT 1
);
"""


@dataclass(slots=True)
class StoredChunk:
    chunk_id: str
    doc_id: str
    source_path: str
    index_in_doc: int
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChunkHit:
    chunk_id: str
    score: float
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    doc_id: str = ""


class SqliteCorpus:
    """SQLite-backed chunk store with FTS5 (BM25) over content.

    Constructor accepts either a path (back-compat: wrapped in a
    ``LocalBackend``-backed ``DatabaseStore`` automatically) or a
    pre-built ``DatabaseStore`` (preferred for Azure / remote storage).

    Read methods refresh the underlying connection when the
    DatabaseStore reports a new generation; write methods participate
    in a shared batch via the optional ``session`` kwarg.
    """

    def __init__(self, path_or_store: str | Path | DatabaseStore) -> None:
        if isinstance(path_or_store, DatabaseStore):
            self._store = path_or_store
        else:
            p = Path(path_or_store)
            self._store = DatabaseStore(
                LocalBackend(p),
                store_id=f"local:{p.resolve()}",
            )
        # Long-lived cached connection on the local cache file.
        # Serialised via _lock for both reads and writes; reopened when
        # the DatabaseStore reports a new generation (cache file
        # replaced under us).
        self._conn: sqlite3.Connection | None = None
        self._generation: int = -1
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        # Back-compat shim — some callers introspect this. Returns the
        # local cache path managed by the DatabaseStore.
        return self._store.cache_path

    async def initialise(self) -> None:
        async with self._store.for_write() as session:
            await asyncio.to_thread(self._init_schema_sync, session.path)

    def _init_schema_sync(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await asyncio.to_thread(self._conn.close)
                self._conn = None
        await self._store.close()

    async def _ensure_conn(self) -> sqlite3.Connection:
        """Return the cached conn, reopening if the cache file was
        replaced. MUST be called with ``self._lock`` held."""
        path, generation = await self._store.ensure_fresh()
        if self._conn is None or generation != self._generation:
            if self._conn is not None:
                await asyncio.to_thread(self._conn.close)
            self._conn = await asyncio.to_thread(_open_corpus_conn, path)
            self._generation = generation
        return self._conn

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            conn = await self._ensure_conn()
            return await asyncio.to_thread(self._query_sync, conn, sql, params or {})

    @staticmethod
    def _query_sync(conn: sqlite3.Connection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    async def upsert_chunks(
        self,
        chunks: Sequence[StoredChunk],
        *,
        session: WriteSession | None = None,
    ) -> None:
        if not chunks:
            return
        if session is None:
            async with self._store.for_write() as session:
                await self._upsert_in_session(session, list(chunks))
        else:
            await self._upsert_in_session(session, list(chunks))

    async def _upsert_in_session(self, session: WriteSession, chunks: list[StoredChunk]) -> None:
        async with self._lock:
            conn = await self._ensure_conn()
            await asyncio.to_thread(self._upsert_chunks_sync, conn, chunks)

    @staticmethod
    def _upsert_chunks_sync(conn: sqlite3.Connection, chunks: list[StoredChunk]) -> None:
        conn.execute("BEGIN")
        try:
            for c in chunks:
                conn.execute(
                    """INSERT OR REPLACE INTO chunks
                       (chunk_id, doc_id, source_path, index_in_doc, content, metadata)
                       VALUES (:chunk_id, :doc_id, :source_path, :index_in_doc, :content, :metadata)""",
                    {
                        "chunk_id": c.chunk_id,
                        "doc_id": c.doc_id,
                        "source_path": c.source_path,
                        "index_in_doc": c.index_in_doc,
                        "content": c.content,
                        "metadata": json.dumps(c.metadata),
                    },
                )
            conn.execute("COMMIT")
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    async def delete_by_doc_id(
        self,
        doc_id: str,
        *,
        session: WriteSession | None = None,
    ) -> int:
        if session is None:
            async with self._store.for_write() as session:
                return await self._delete_by_doc_id_in_session(doc_id)
        return await self._delete_by_doc_id_in_session(doc_id)

    async def _delete_by_doc_id_in_session(self, doc_id: str) -> int:
        async with self._lock:
            conn = await self._ensure_conn()
            return await asyncio.to_thread(self._delete_by_doc_id_sync, conn, doc_id)

    @staticmethod
    def _delete_by_doc_id_sync(conn: sqlite3.Connection, doc_id: str) -> int:
        conn.execute("BEGIN")
        try:
            n = conn.execute(
                "DELETE FROM chunks WHERE doc_id = :doc",
                {"doc": doc_id},
            ).rowcount
            conn.execute("COMMIT")
            return n
        except Exception:
            conn.execute("ROLLBACK")
            raise

    async def bm25_search(self, query: str, *, top_k: int = 30) -> list[ChunkHit]:
        async with self._lock:
            conn = await self._ensure_conn()
            return await asyncio.to_thread(self._bm25_search_sync, conn, query, top_k)

    @staticmethod
    def _bm25_search_sync(conn: sqlite3.Connection, query: str, top_k: int) -> list[ChunkHit]:
        match_expr = sanitize_fts_query(query)
        if not match_expr:
            return []
        try:
            cur = conn.execute(
                """SELECT c.chunk_id, c.content, c.metadata, c.doc_id, c.source_path,
                          bm25(chunks_fts) AS score
                   FROM chunks_fts
                   JOIN chunks c ON c.rowid = chunks_fts.rowid
                   WHERE chunks_fts MATCH :q
                   ORDER BY score
                   LIMIT :k""",
                {"q": match_expr, "k": top_k},
            )
        except sqlite3.OperationalError as exc:
            log.warning("bm25_search returned no results due to OperationalError: %s", exc)
            return []
        return [
            ChunkHit(
                chunk_id=r["chunk_id"],
                score=float(r["score"]),
                content=r["content"],
                metadata=json.loads(r["metadata"]),
                source_path=r["source_path"],
                doc_id=r["doc_id"],
            )
            for r in cur.fetchall()
        ]

    async def clear_all(self) -> None:
        """Delete all chunks, ingestions, and structured data.

        Drops every table recorded in ``_schemas``, then purges the
        ``chunks``, ``ingestions``, and ``_schemas`` tables. FTS5 triggers
        fire on chunk deletes, keeping the index consistent. The database
        file stays open and ready for new ingestion.
        """
        try:
            schema_rows = await self.query("SELECT name FROM _schemas")
            for row in schema_rows:
                quoted = row["name"].replace('"', '""')
                await self.query(f'DROP TABLE IF EXISTS "{quoted}"')
            await self.query("DELETE FROM _schemas")
        except Exception as exc:
            log.warning("clear_all: could not drop structured tables: %s", exc)
        await self.query("DELETE FROM chunks")
        await self.query("DELETE FROM ingestions")

    async def get_chunks(self, chunk_ids: list[str]) -> list[StoredChunk]:
        if not chunk_ids:
            return []
        placeholders = ",".join(f":id{i}" for i in range(len(chunk_ids)))
        params = {f"id{i}": cid for i, cid in enumerate(chunk_ids)}
        rows = await self.query(
            f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})",
            params,
        )
        return [
            StoredChunk(
                chunk_id=r["chunk_id"],
                doc_id=r["doc_id"],
                source_path=r["source_path"],
                index_in_doc=r["index_in_doc"],
                content=r["content"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]


def _open_corpus_conn(path: Path) -> sqlite3.Connection:
    # ``timeout=30`` is the Python sqlite3 module's busy timeout — it
    # waits up to 30s for the writer slot when another connection is
    # mid-write, instead of failing fast with "database is locked".
    # The PRAGMA equivalent is overridden by this argument on the
    # Python side, so we set it here.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


# ---------- corpus discovery / pluggable storage ----------------------------
#
# Below this point is the layer that decides *which* corpus to open, not how
# to read one. The MCP corpus tools (list_corpora, _assert_corpus_exists,
# corpus_query, …) need two operations: lookup a StorageBackend for a given
# corpus_id, and enumerate every corpus the server can see. Bundling both
# behind one :class:`CorpusBackendRegistry` keeps them consistent — the
# local registry walks CORPUS_ROOT for both; a remote registry talks to one
# container for both.
#
# The framework ships :class:`LocalCorpusBackendRegistry`. Non-filesystem
# implementations (Azure Blob, S3, GCS) live in ``examples/`` so the
# framework stays vendor-neutral. Selection at runtime is via the
# ``CORPUS_BACKEND_REGISTRY_FACTORY`` env var, parsed by
# :func:`resolve_registry_factory`, mirroring the
# ``FIREFLY_MCP_TOKEN_STORE_FACTORY`` pattern used by the MCP auth layer.


@runtime_checkable
class CorpusBackendRegistry(Protocol):
    """How the MCP corpus tools find the storage for a given corpus."""

    @property
    def source(self) -> str:
        """Human-readable source label.

        Surfaced in :func:`list_corpora`'s ``corpus_root`` field so an
        operator can tell at a glance whether the server is reading from
        a local directory, a blob container, or something else. Free-
        form; no parser depends on it.
        """
        ...

    def backend_for(self, corpus_id: str) -> StorageBackend:
        """Return the :class:`StorageBackend` for *corpus_id*.

        Called from :func:`_agent_for` once per corpus and cached. The
        same instance is reused for the lifetime of the process, so an
        implementation can hold long-lived clients / credentials in the
        returned backend.
        """
        ...

    async def list_corpora(self) -> list[dict[str, Any]]:
        """Return every corpus this registry can serve.

        Each entry must carry ``corpus_id`` (str), ``size_bytes``
        (int or None), ``modified`` (ISO-8601 str or None). Caller
        sorts and filters the result; implementations don't apply the
        authorisation contextvar themselves.
        """
        ...


class LocalCorpusBackendRegistry:
    """Filesystem-backed registry: each corpus is a directory under
    ``CORPUS_ROOT`` containing ``corpus.sqlite``.

    The directory layout matches what shipped with the original MCP
    server, so existing on-disk state is forward-compatible.

    Args:
        root: Optional override for the filesystem root. ``None`` reads
            from ``CORPUS_ROOT`` env var, falling back to
            ``/tmp/firefly/corpora`` to match the framework's default.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root_override = root

    @property
    def root(self) -> Path:
        if self._root_override is not None:
            return self._root_override
        return Path(os.path.expandvars(os.environ.get("CORPUS_ROOT", _DEFAULT_CORPUS_ROOT)))

    @property
    def source(self) -> str:
        return str(self.root)

    def backend_for(self, corpus_id: str) -> StorageBackend:
        return LocalBackend(self.root / corpus_id / _CORPUS_SQLITE_NAME)

    async def list_corpora(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        root = self.root
        if not root.is_dir():
            return out
        for entry in sorted(root.iterdir()):
            sqlite_path = entry / _CORPUS_SQLITE_NAME
            if not (entry.is_dir() and sqlite_path.is_file()):
                continue
            st = sqlite_path.stat()
            out.append(
                {
                    "corpus_id": entry.name,
                    "size_bytes": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
                }
            )
        return out


def resolve_registry_factory(spec: str):
    """Resolve a ``"module.path:callable"`` factory string.

    The callable must take no arguments and return a
    :class:`CorpusBackendRegistry`. Errors carry enough context for an
    operator to fix the env var without source-diving (the alternative
    — a bare ``ImportError`` at first tool call — makes ops debugging
    painful, matching the pattern in
    :mod:`fireflyframework_agentic.exposure.mcp.http_cli`).
    """
    module_path, _, attr = spec.partition(":")
    if not module_path or not attr:
        raise RuntimeError(f"CORPUS_BACKEND_REGISTRY_FACTORY must look like 'pkg.mod:callable', got {spec!r}")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise RuntimeError(
            f"Cannot import corpus backend registry factory module {module_path!r}: {exc}. "
            "Check the module is installed and importable from the server's "
            "Python path. For Azure-backed corpora install the corpus_search "
            "example deps and point at "
            "'examples.corpus_search.azure_backend:build_registry'."
        ) from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise RuntimeError(f"Factory {spec!r} resolved to a module without attribute {attr!r}") from exc
