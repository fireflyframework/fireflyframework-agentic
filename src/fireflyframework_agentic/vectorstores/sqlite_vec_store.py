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

"""SQLite-vec backed vector store using the vec0 virtual table."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any

try:
    import sqlite_vec
    from sqlite_vec import serialize_float32
except ImportError:
    sqlite_vec = None  # type: ignore[assignment]
    serialize_float32 = None  # type: ignore[assignment]

from fireflyframework_agentic.vectorstores.base import BaseVectorStore
from fireflyframework_agentic.vectorstores.types import SearchFilter, SearchResult, VectorDocument

logger = logging.getLogger(__name__)


class SqliteVecVectorStore(BaseVectorStore):
    """sqlite-vec backed vector store co-residing in an existing SQLite file.

    Uses a vec0 virtual table (distance_metric=cosine) for KNN search and a
    shadow table that maps string IDs to integer rowids and stores namespace.
    Opens its own sqlite3 connection so it can safely share the file with
    SqliteCorpus under SQLite WAL mode.

    Parameters:
        db_path: Path to the SQLite file (may already contain SqliteCorpus tables).
        dimension: Embedding dimension — must match the embedder used at ingest time.
        table_name: Name of the vec0 virtual table (default: ``vec_chunks``).
    """

    def __init__(
        self,
        db_path: Path | str,
        dimension: int,
        *,
        table_name: str = "vec_chunks",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._db_path = Path(db_path)
        self._dim = dimension
        self._tbl = table_name
        self._shadow = f"{table_name}_shadow"
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._ready = False

    # ------------------------------------------------------------------
    # Initialisation (lazy, called with lock held)
    # ------------------------------------------------------------------

    def _initialise_sync(self) -> None:
        if sqlite_vec is None:
            raise ImportError(
                "sqlite-vec is required for SqliteVecVectorStore. "
                "Install with: pip install 'fireflyframework-agentic[vectorstores-sqlite-vec]'"
            )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._shadow} (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                id    TEXT UNIQUE NOT NULL,
                ns    TEXT NOT NULL DEFAULT 'default'
            )
        """)
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {self._tbl}
            USING vec0(embedding float[{self._dim}] distance_metric=cosine)
        """)
        self._conn = conn
        self._ready = True

    async def _ensure_ready(self) -> None:
        """Must be called with self._lock held."""
        if not self._ready:
            await asyncio.to_thread(self._initialise_sync)

    # ------------------------------------------------------------------
    # BaseVectorStore interface
    # ------------------------------------------------------------------

    async def _upsert(self, documents: list[VectorDocument], namespace: str) -> None:
        async with self._lock:
            await self._ensure_ready()
            await asyncio.to_thread(self._upsert_sync, documents, namespace)

    def _upsert_sync(self, documents: list[VectorDocument], namespace: str) -> None:
        assert self._conn is not None
        conn = self._conn
        conn.execute("BEGIN")
        try:
            for doc in documents:
                conn.execute(
                    f"INSERT INTO {self._shadow}(id, ns) VALUES(?, ?)"
                    f" ON CONFLICT(id) DO UPDATE SET ns=excluded.ns",
                    (doc.id, namespace),
                )
                row = conn.execute(
                    f"SELECT rowid FROM {self._shadow} WHERE id = ?", (doc.id,)
                ).fetchone()
                rowid = row[0]
                # vec0 does not support UPDATE — delete the old vector then re-insert.
                conn.execute(f"DELETE FROM {self._tbl} WHERE rowid = ?", (rowid,))
                conn.execute(
                    f"INSERT INTO {self._tbl}(rowid, embedding) VALUES(?, ?)",
                    (rowid, serialize_float32(doc.embedding)),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]:
        async with self._lock:
            await self._ensure_ready()
            return await asyncio.to_thread(self._search_sync, query_embedding, top_k, namespace)

    def _search_sync(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
    ) -> list[SearchResult]:
        assert self._conn is not None
        rows = self._conn.execute(
            f"""
            SELECT s.id, v.distance
            FROM (
                SELECT rowid, distance
                FROM {self._tbl}
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            ) v
            JOIN {self._shadow} s ON s.rowid = v.rowid
            WHERE s.ns = ?
            """,
            (serialize_float32(query_embedding), top_k, namespace),
        ).fetchall()
        return [
            SearchResult(
                document=VectorDocument(id=row["id"], text="", metadata={}),
                score=1.0 - row["distance"],
            )
            for row in rows
        ]

    async def _delete(self, ids: list[str], namespace: str) -> None:
        async with self._lock:
            await self._ensure_ready()
            await asyncio.to_thread(self._delete_sync, ids, namespace)

    def _delete_sync(self, ids: list[str], namespace: str) -> None:
        assert self._conn is not None
        if not ids:
            return
        conn = self._conn
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT rowid FROM {self._shadow} WHERE id IN ({ph}) AND ns = ?",
            (*ids, namespace),
        ).fetchall()
        rowids = [r[0] for r in rows]
        conn.execute("BEGIN")
        try:
            if rowids:
                rph = ",".join("?" * len(rowids))
                conn.execute(f"DELETE FROM {self._tbl} WHERE rowid IN ({rph})", rowids)
            conn.execute(
                f"DELETE FROM {self._shadow} WHERE id IN ({ph}) AND ns = ?",
                (*ids, namespace),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await asyncio.to_thread(self._conn.close)
                self._conn = None
                self._ready = False
