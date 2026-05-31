"""pgvector vector store backend.

A PostgreSQL-backed vector store using the ``pgvector`` extension, peer to the
Chroma / Pinecone / Qdrant adapters. Co-locating the vector projection with a
PostgreSQL instance means production deployments don't have to operate a
separate vector database.

Like the other adapters this is **namespace-based** (single ``namespace`` per
document); multi-tenant isolation is layered on top by
:class:`~fireflyframework_agentic.vectorstores.scoped.TenantScopedVectorStore`.

The store owns one table (``vector_documents`` by default), created on first use::

    CREATE TABLE <table> (
        id         TEXT PRIMARY KEY,
        namespace  TEXT NOT NULL DEFAULT 'default',
        embedding  vector(<dimension>) NOT NULL,
        text       TEXT NOT NULL,
        metadata   JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

ANN search uses an HNSW index over cosine distance. :meth:`_prepare_session` is
an overridable per-transaction hook (default no-op) for callers that need
connection-level session setup -- e.g. ``SET LOCAL`` for Postgres Row-Level
Security GUCs.

Requires the ``vectorstores-pgvector`` extra
(``pip install fireflyframework-agentic[vectorstores-pgvector]``) and the
``pgvector`` extension available on the Postgres server.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

try:
    import asyncpg  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    asyncpg = None  # type: ignore[assignment]

from fireflyframework_agentic.exceptions import VectorStoreConnectionError, VectorStoreError
from fireflyframework_agentic.vectorstores.base import BaseVectorStore
from fireflyframework_agentic.vectorstores.types import SearchFilter, SearchResult, VectorDocument

logger = logging.getLogger(__name__)

_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# SQL comparison operator for each non-membership SearchFilter operator.
_SCALAR_OPERATORS = {"eq": "=", "ne": "<>", "gt": ">", "lt": "<", "gte": ">=", "lte": "<="}


class PgVectorVectorStore(BaseVectorStore):
    """pgvector-backed vector store.

    Parameters:
        url: PostgreSQL connection string (e.g. ``postgresql://user:pass@host/db``).
        dimension: Embedding dimension; sizes the ``vector(<dimension>)`` column.
        table_name: Table that holds the vectors. Must be a valid SQL identifier.
        hnsw_m: HNSW ``m`` build parameter.
        hnsw_ef_construction: HNSW ``ef_construction`` build parameter.
        hnsw_ef_search: ``hnsw.ef_search`` set per query for recall/latency tuning.
        pool_min_size / pool_max_size: asyncpg connection-pool bounds.
        embedder: Optional embedder for auto-embedding (see :class:`BaseVectorStore`).
    """

    def __init__(
        self,
        url: str,
        *,
        dimension: int,
        table_name: str = "vector_documents",
        hnsw_m: int = 16,
        hnsw_ef_construction: int = 64,
        hnsw_ef_search: int = 200,
        pool_min_size: int = 1,
        pool_max_size: int = 10,
        embedder: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(embedder=embedder, **kwargs)
        if asyncpg is None:
            raise ImportError(
                "asyncpg is required for PgVectorVectorStore. Install it with: "
                "pip install fireflyframework-agentic[vectorstores-pgvector]"
            )
        if not _SAFE_IDENTIFIER.match(table_name):
            raise ValueError(f"Invalid table_name: {table_name!r}. Must be a valid SQL identifier.")
        self._url = url
        self._dimension = dimension
        self._table = table_name
        self._hnsw_m = hnsw_m
        self._hnsw_ef_construction = hnsw_ef_construction
        self._hnsw_ef_search = hnsw_ef_search
        self._pool_min_size = pool_min_size
        self._pool_max_size = pool_max_size
        self._pool: Any = None
        self._initialised = False

    # -- lifecycle ----------------------------------------------------------

    async def initialise(self) -> None:
        """Open the connection pool and create the schema. Idempotent."""
        await self._ensure_pool()

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self._initialised = False

    async def _ensure_pool(self) -> Any:
        assert asyncpg is not None  # guaranteed by the __init__ import guard
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    self._url,
                    min_size=self._pool_min_size,
                    max_size=self._pool_max_size,
                )
            except Exception as exc:
                raise VectorStoreConnectionError(f"Failed to connect to PostgreSQL: {exc}") from exc
        if not self._initialised:
            async with self._pool.acquire() as conn:
                await self._create_schema(conn)
            self._initialised = True
        return self._pool

    async def _create_schema(self, conn: Any) -> None:
        """Create the extension, table, and indexes if absent. Idempotent.

        Subclasses may override to add deployment concerns (e.g. RLS policies)
        on the same connection via ``await super()._create_schema(conn)``.
        """
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table} (
                id         TEXT PRIMARY KEY,
                namespace  TEXT NOT NULL DEFAULT 'default',
                embedding  vector({self._dimension}) NOT NULL,
                text       TEXT NOT NULL,
                metadata   JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {self._table}_hnsw
            ON {self._table} USING hnsw (embedding vector_cosine_ops)
            WITH (m = {self._hnsw_m}, ef_construction = {self._hnsw_ef_construction})
            """
        )
        await conn.execute(f"CREATE INDEX IF NOT EXISTS {self._table}_namespace ON {self._table} (namespace)")

    async def _prepare_session(self, conn: Any, *, namespace: str) -> None:
        """Per-transaction session-setup hook. Default: no-op.

        Override to run ``SET LOCAL`` statements on *conn* before the operation
        executes -- e.g. RLS GUCs, ``search_path``, or ``statement_timeout``.
        """
        return None

    # -- VectorStoreProtocol surface ---------------------------------------

    async def _upsert(self, documents: list[VectorDocument], namespace: str) -> None:
        rows = []
        for doc in documents:
            if doc.embedding is None:
                raise VectorStoreError(f"VectorDocument {doc.id!r} has no embedding; pgvector requires one.")
            rows.append((doc.id, namespace, _vector_literal(doc.embedding), doc.text, json.dumps(doc.metadata)))
        if not rows:
            return
        pool = await self._ensure_pool()
        async with pool.acquire() as conn, conn.transaction():
            await self._prepare_session(conn, namespace=namespace)
            await conn.executemany(
                f"""
                INSERT INTO {self._table} (id, namespace, embedding, text, metadata)
                VALUES ($1, $2, $3::vector, $4, $5::jsonb)
                ON CONFLICT (id) DO UPDATE
                SET namespace = EXCLUDED.namespace,
                    embedding = EXCLUDED.embedding,
                    text      = EXCLUDED.text,
                    metadata  = EXCLUDED.metadata
                """,
                rows,
            )

    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]:
        params: list[Any] = [_vector_literal(query_embedding), namespace, top_k]
        where = ["namespace = $2"]
        next_index = 4
        for f in filters or []:
            clause, clause_params, next_index = _filter_clause(f, next_index)
            where.append(clause)
            params.extend(clause_params)
        sql = f"""
            SELECT id, text, metadata, 1 - (embedding <=> $1::vector) AS score
            FROM {self._table}
            WHERE {" AND ".join(where)}
            ORDER BY embedding <=> $1::vector
            LIMIT $3
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn, conn.transaction():
            await self._prepare_session(conn, namespace=namespace)
            await conn.execute(f"SET LOCAL hnsw.ef_search = {self._hnsw_ef_search}")
            records = await conn.fetch(sql, *params)
        return [
            SearchResult(
                document=VectorDocument(
                    id=str(rec["id"]),
                    text=rec["text"],
                    embedding=None,
                    metadata=_load_metadata(rec["metadata"]),
                    namespace=namespace,
                ),
                score=float(rec["score"]),
            )
            for rec in records
        ]

    async def _delete(self, ids: list[str], namespace: str) -> None:
        if not ids:
            return
        pool = await self._ensure_pool()
        async with pool.acquire() as conn, conn.transaction():
            await self._prepare_session(conn, namespace=namespace)
            await conn.execute(
                f"DELETE FROM {self._table} WHERE namespace = $1 AND id = ANY($2::text[])",
                namespace,
                [str(i) for i in ids],
            )


def _vector_literal(values: list[float]) -> str:
    """Render a vector as the pgvector text input literal ``[v1,v2,...]``."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _load_metadata(raw: Any) -> dict[str, Any]:
    """Decode a JSONB column (asyncpg returns it as ``str``) to a dict."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        return dict(json.loads(raw))
    return dict(raw)


def _filter_clause(f: SearchFilter, index: int) -> tuple[str, list[Any], int]:
    """Build a parameterised metadata predicate for one :class:`SearchFilter`.

    The metadata key and value are both bound as parameters (``metadata ->> $k``),
    so neither is interpolated into the SQL text. Returns the clause, its
    parameters, and the next free positional-parameter index.
    """
    if f.operator == "in":
        values = [str(v) for v in f.value]
        return f"metadata ->> ${index} = ANY(${index + 1}::text[])", [f.field, values], index + 2
    op = _SCALAR_OPERATORS.get(f.operator)
    if op is None:  # pragma: no cover - SearchFilter.operator is a constrained Literal
        raise VectorStoreError(f"Unsupported filter operator: {f.operator!r}")
    if f.operator == "ne":
        # IS DISTINCT FROM so NULL metadata keys are treated as "not equal".
        return f"metadata ->> ${index} IS DISTINCT FROM ${index + 1}", [f.field, str(f.value)], index + 2
    return f"metadata ->> ${index} {op} ${index + 1}", [f.field, str(f.value)], index + 2
