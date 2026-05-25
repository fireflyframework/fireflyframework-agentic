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

"""SQLite-vec backed vector store using the vec0 virtual table."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import sqlite_vec
    from sqlite_vec import serialize_float32
except ImportError:
    sqlite_vec = None  # type: ignore[assignment]

    def serialize_float32(vector: list[float]) -> bytes:  # type: ignore[misc]
        raise ImportError("sqlite-vec is not installed")


from fireflyframework_agentic.exceptions import VectorStoreError
from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
from fireflyframework_agentic.vectorstores.base import BaseVectorStore
from fireflyframework_agentic.vectorstores.types import SearchFilter, SearchResult, VectorDocument

if TYPE_CHECKING:
    from fireflyframework_agentic.storage import WriteSession

logger = logging.getLogger(__name__)


class SqliteVecVectorStore(BaseVectorStore):
    """sqlite-vec backed vector store co-residing in an existing SQLite file.

    Constructor accepts either a path (back-compat: wrapped in a
    ``LocalBackend``-backed ``DatabaseStore`` automatically) or a
    pre-built ``DatabaseStore``. The legacy ``db_path`` keyword is
    preserved for back-compat with existing call sites.
    """

    def __init__(
        self,
        path_or_store: str | Path | DatabaseStore | None = None,
        dimension: int = 0,
        *,
        db_path: str | Path | None = None,
        table_name: str = "vec_chunks",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if path_or_store is None and db_path is None:
            raise TypeError("SqliteVecVectorStore requires path_or_store or db_path")
        target = path_or_store if path_or_store is not None else db_path
        assert target is not None  # guaranteed by the TypeError check above

        if isinstance(target, DatabaseStore):
            self._store = target
        else:
            p = Path(target)
            self._store = DatabaseStore(
                LocalBackend(p),
                store_id=f"local:{p.resolve()}",
            )
        self._dim = dimension
        self._tbl = table_name
        self._shadow = f"{table_name}_shadow"
        # Long-lived cached connection; serialised by _lock for both
        # reads and writes. Reopened when the cache file is replaced.
        self._conn: sqlite3.Connection | None = None
        self._generation: int = -1
        self._lock = asyncio.Lock()

    async def _ensure_conn(self) -> sqlite3.Connection:
        """Return the cached conn, reopening if the cache file was
        replaced. MUST be called with ``self._lock`` held."""
        path, generation = await self._store.ensure_fresh()
        if self._conn is None or generation != self._generation:
            if self._conn is not None:
                await asyncio.to_thread(self._conn.close)
            self._conn = await asyncio.to_thread(self._open_conn_with_schema, path)
            self._generation = generation
        return self._conn

    def _open_conn_with_schema(self, path: Path) -> sqlite3.Connection:
        if sqlite_vec is None:
            raise ImportError(
                "sqlite-vec is required for SqliteVecVectorStore. "
                "Install with: pip install 'fireflyframework-agentic[vectorstores-sqlite-vec]'"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        # See _open_corpus_conn for why timeout= is used instead of PRAGMA.
        conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=30.0)
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
        return conn

    # --- public overrides for session pass-through ---

    async def upsert(
        self,
        documents: list[VectorDocument],
        namespace: str = "default",
        *,
        session: WriteSession | None = None,
    ) -> None:
        """Override of BaseVectorStore.upsert to accept a shared
        DatabaseStore write session for coordinated batches."""
        needs_embedding = [d for d in documents if d.embedding is None]
        if needs_embedding:
            if self._embedder is None:
                raise VectorStoreError(
                    f"{len(needs_embedding)} document(s) have no embedding and no embedder is configured."
                )
            texts = [d.text for d in needs_embedding]
            result = await self._embedder.embed(texts)
            for doc, emb in zip(needs_embedding, result.embeddings, strict=True):
                doc.embedding = emb
        try:
            await self._upsert(documents, namespace, session=session)
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(f"Upsert failed: {exc}") from exc

    async def delete(
        self,
        ids: list[str],
        namespace: str = "default",
        *,
        session: WriteSession | None = None,
    ) -> None:
        try:
            await self._delete(ids, namespace, session=session)
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(f"Delete failed: {exc}") from exc

    # --- BaseVectorStore protocol implementations ---

    async def _upsert(
        self,
        documents: list[VectorDocument],
        namespace: str,
        *,
        session: WriteSession | None = None,
    ) -> None:
        if session is None:
            async with self._store.for_write() as session:
                await self._upsert_in_session(documents, namespace)
        else:
            await self._upsert_in_session(documents, namespace)

    async def _upsert_in_session(self, documents: list[VectorDocument], namespace: str) -> None:
        async with self._lock:
            conn = await self._ensure_conn()
            await asyncio.to_thread(self._upsert_sync_on, conn, documents, namespace)

    def _upsert_sync_on(self, conn: sqlite3.Connection, documents: list[VectorDocument], namespace: str) -> None:
        conn.execute("BEGIN")
        try:
            for doc in documents:
                conn.execute(
                    f"INSERT INTO {self._shadow}(id, ns) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET ns=excluded.ns",
                    (doc.id, namespace),
                )
                row = conn.execute(f"SELECT rowid FROM {self._shadow} WHERE id = ?", (doc.id,)).fetchone()
                rowid = row[0]
                conn.execute(f"DELETE FROM {self._tbl} WHERE rowid = ?", (rowid,))
                assert doc.embedding is not None
                conn.execute(
                    f"INSERT INTO {self._tbl}(rowid, embedding) VALUES(?, ?)",
                    (rowid, serialize_float32(doc.embedding)),
                )
            conn.execute("COMMIT")
            conn.execute("PRAGMA wal_checkpoint(FULL)")
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
            conn = await self._ensure_conn()
            return await asyncio.to_thread(self._search_sync, conn, query_embedding, top_k, namespace)

    def _search_sync(
        self,
        conn: sqlite3.Connection,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
    ) -> list[SearchResult]:
        rows = conn.execute(
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

    async def _delete(
        self,
        ids: list[str],
        namespace: str,
        *,
        session: WriteSession | None = None,
    ) -> None:
        if not ids:
            return
        if session is None:
            async with self._store.for_write() as session:
                await self._delete_in_session(ids, namespace)
        else:
            await self._delete_in_session(ids, namespace)

    async def _delete_in_session(self, ids: list[str], namespace: str) -> None:
        async with self._lock:
            conn = await self._ensure_conn()
            await asyncio.to_thread(self._delete_sync_on, conn, ids, namespace)

    def _delete_sync_on(self, conn: sqlite3.Connection, ids: list[str], namespace: str) -> None:
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
        await self._store.close()
