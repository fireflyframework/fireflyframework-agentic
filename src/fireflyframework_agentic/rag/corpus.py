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

import asyncio
import json
import logging
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


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

    Single file, WAL mode. Threadsafe via a per-instance asyncio lock.
    A single sqlite3 connection is held for the lifetime of the store
    and closed via :meth:`close`.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialise(self) -> None:
        await asyncio.to_thread(self._initialise_sync)

    def _initialise_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        self._conn = conn

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(self._query_sync, sql, params or {})

    def _query_sync(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        assert self._conn is not None
        cur = self._conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    async def upsert_chunks(self, chunks: Sequence[StoredChunk]) -> None:
        if not chunks:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_chunks_sync, list(chunks))

    def _upsert_chunks_sync(self, chunks: list[StoredChunk]) -> None:
        assert self._conn is not None
        cur = self._conn
        cur.execute("BEGIN")
        try:
            for c in chunks:
                cur.execute(
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
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    async def delete_by_doc_id(self, doc_id: str) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._delete_by_doc_id_sync, doc_id)

    def _delete_by_doc_id_sync(self, doc_id: str) -> int:
        assert self._conn is not None
        cur = self._conn
        cur.execute("BEGIN")
        try:
            n = cur.execute(
                "DELETE FROM chunks WHERE doc_id = :doc",
                {"doc": doc_id},
            ).rowcount
            cur.execute("COMMIT")
            return n
        except Exception:
            cur.execute("ROLLBACK")
            raise

    async def bm25_search(self, query: str, *, top_k: int = 30) -> list[ChunkHit]:
        async with self._lock:
            return await asyncio.to_thread(self._bm25_search_sync, query, top_k)

    def _bm25_search_sync(self, query: str, top_k: int) -> list[ChunkHit]:
        assert self._conn is not None
        # Sanitise free-text queries (questions with ``?``, names with ``-``,
        # phrases with quotes) into FTS5-safe MATCH syntax. Empty after
        # sanitisation -> no hits.
        match_expr = sanitize_fts_query(query)
        if not match_expr:
            return []
        try:
            cur = self._conn.execute(
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
            # Sanitisation should have prevented the common syntax-error
            # cases. Anything reaching this handler is a real fault
            # (corrupt index, missing table, disk full) — log it loudly
            # rather than silently dropping.
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
