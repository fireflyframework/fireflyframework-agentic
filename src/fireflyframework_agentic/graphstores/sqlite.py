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
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fireflyframework_agentic.graphstores.types import Edge, Node


_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nodes (
  source_doc_id   TEXT NOT NULL,
  label           TEXT NOT NULL,
  key             TEXT NOT NULL,
  properties      TEXT NOT NULL,
  extractor_name  TEXT NOT NULL,
  chunk_ids       TEXT NOT NULL,
  PRIMARY KEY (source_doc_id, label, key)
);
CREATE INDEX IF NOT EXISTS idx_nodes_doc       ON nodes(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_nodes_label     ON nodes(label);
CREATE INDEX IF NOT EXISTS idx_nodes_label_key ON nodes(label, key);

CREATE TABLE IF NOT EXISTS edges (
  source_doc_id   TEXT NOT NULL,
  label           TEXT NOT NULL,
  source_label    TEXT NOT NULL,
  source_key      TEXT NOT NULL,
  target_label    TEXT NOT NULL,
  target_key      TEXT NOT NULL,
  properties      TEXT NOT NULL,
  extractor_name  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_doc                ON edges(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_edges_endpoints          ON edges(source_label, source_key, target_label, target_key);
CREATE INDEX IF NOT EXISTS idx_edges_endpoints_reverse  ON edges(target_label, target_key, source_label, source_key);

CREATE TABLE IF NOT EXISTS node_chunks (
  source_doc_id  TEXT NOT NULL,
  label          TEXT NOT NULL,
  key            TEXT NOT NULL,
  chunk_id       TEXT NOT NULL,
  PRIMARY KEY (chunk_id, source_doc_id, label, key)
);
CREATE INDEX IF NOT EXISTS idx_node_chunks_node ON node_chunks(source_doc_id, label, key);

CREATE TABLE IF NOT EXISTS ingestions (
  doc_id              TEXT PRIMARY KEY,
  source_path         TEXT NOT NULL,
  content_hash        TEXT NOT NULL,
  status              TEXT NOT NULL,
  partial_extractors  TEXT,
  ingested_at         TEXT NOT NULL,
  attempt             INTEGER NOT NULL DEFAULT 1
);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
  source_doc_id  UNINDEXED,
  label          UNINDEXED,
  key,
  text,
  tokenize='unicode61 remove_diacritics 2'
);

CREATE VIRTUAL TABLE IF NOT EXISTS edges_fts USING fts5(
  source_doc_id  UNINDEXED,
  label          UNINDEXED,
  source_label   UNINDEXED,
  source_key     UNINDEXED,
  target_label   UNINDEXED,
  target_key     UNINDEXED,
  text,
  tokenize='unicode61 remove_diacritics 2'
);
"""


def _node_fts_text(node: Node) -> str:
    """Materialise the FTS searchable text from key + aliases + description."""
    parts: list[str] = [node.key]
    description = node.properties.get("description")
    if description:
        parts.append(str(description))
    aliases = node.properties.get("aliases") or []
    parts.extend(str(a) for a in aliases)
    return " ".join(parts)


def _edge_fts_text(edge: Edge) -> str:
    """Materialise FTS searchable text from edge label + property strings."""
    parts: list[str] = [edge.label]
    for value in edge.properties.values():
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts)


class SqliteGraphStore:
    """SQLite-backed GraphStoreProtocol implementation.

    Single file, WAL mode. Threadsafe via a per-instance asyncio lock around
    each connection use; a single sqlite3 connection is held for the lifetime
    of the store and closed via :meth:`close`.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialise(self) -> None:
        """Open the connection and run the schema DDL."""
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

    async def query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(self._query_sync, sql, params or {})

    def _query_sync(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        assert self._conn is not None, "store not initialised"
        cursor = self._conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    async def upsert_nodes(self, nodes: Sequence[Node]) -> None:
        if not nodes:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_nodes_sync, list(nodes))

    def _upsert_nodes_sync(self, nodes: list[Node]) -> None:
        assert self._conn is not None
        cur = self._conn
        cur.execute("BEGIN")
        try:
            for n in nodes:
                cur.execute(
                    """INSERT OR REPLACE INTO nodes
                       (source_doc_id, label, key, properties, extractor_name, chunk_ids)
                       VALUES (:source_doc_id, :label, :key, :properties, :extractor_name, :chunk_ids)""",
                    {
                        "source_doc_id": n.source_doc_id,
                        "label": n.label,
                        "key": n.key,
                        "properties": json.dumps(n.properties),
                        "extractor_name": n.extractor_name,
                        "chunk_ids": json.dumps(n.chunk_ids),
                    },
                )
                cur.execute(
                    "DELETE FROM node_chunks WHERE source_doc_id=:doc AND label=:lbl AND key=:k",
                    {"doc": n.source_doc_id, "lbl": n.label, "k": n.key},
                )
                for cid in n.chunk_ids:
                    cur.execute(
                        """INSERT INTO node_chunks (source_doc_id, label, key, chunk_id)
                           VALUES (:doc, :lbl, :k, :cid)""",
                        {"doc": n.source_doc_id, "lbl": n.label, "k": n.key, "cid": cid},
                    )
                cur.execute(
                    """DELETE FROM nodes_fts
                       WHERE source_doc_id = :doc AND label = :lbl AND key = :k""",
                    {"doc": n.source_doc_id, "lbl": n.label, "k": n.key},
                )
                cur.execute(
                    """INSERT INTO nodes_fts (source_doc_id, label, key, text)
                       VALUES (:doc, :lbl, :k, :text)""",
                    {
                        "doc": n.source_doc_id,
                        "lbl": n.label,
                        "k": n.key,
                        "text": _node_fts_text(n),
                    },
                )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    async def upsert_edges(self, edges: Sequence[Edge]) -> None:
        if not edges:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_edges_sync, list(edges))

    def _upsert_edges_sync(self, edges: list[Edge]) -> None:
        assert self._conn is not None
        cur = self._conn
        cur.execute("BEGIN")
        try:
            for e in edges:
                cur.execute(
                    """INSERT INTO edges
                       (source_doc_id, label, source_label, source_key, target_label, target_key,
                        properties, extractor_name)
                       VALUES (:source_doc_id, :label, :source_label, :source_key,
                               :target_label, :target_key, :properties, :extractor_name)""",
                    {
                        "source_doc_id": e.source_doc_id,
                        "label": e.label,
                        "source_label": e.source_label,
                        "source_key": e.source_key,
                        "target_label": e.target_label,
                        "target_key": e.target_key,
                        "properties": json.dumps(e.properties),
                        "extractor_name": e.extractor_name,
                    },
                )
                cur.execute(
                    """INSERT INTO edges_fts
                       (source_doc_id, label, source_label, source_key,
                        target_label, target_key, text)
                       VALUES (:source_doc_id, :label, :source_label, :source_key,
                               :target_label, :target_key, :text)""",
                    {
                        "source_doc_id": e.source_doc_id,
                        "label": e.label,
                        "source_label": e.source_label,
                        "source_key": e.source_key,
                        "target_label": e.target_label,
                        "target_key": e.target_key,
                        "text": _edge_fts_text(e),
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
            n_nodes = cur.execute(
                "DELETE FROM nodes WHERE source_doc_id = :doc",
                {"doc": doc_id},
            ).rowcount
            n_edges = cur.execute(
                "DELETE FROM edges WHERE source_doc_id = :doc",
                {"doc": doc_id},
            ).rowcount
            cur.execute("DELETE FROM node_chunks WHERE source_doc_id = :doc", {"doc": doc_id})
            cur.execute("DELETE FROM nodes_fts WHERE source_doc_id = :doc", {"doc": doc_id})
            cur.execute("DELETE FROM edges_fts WHERE source_doc_id = :doc", {"doc": doc_id})
            cur.execute("COMMIT")
            return n_nodes + n_edges
        except Exception:
            cur.execute("ROLLBACK")
            raise
