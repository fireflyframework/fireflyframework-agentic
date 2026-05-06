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
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker
from fireflyframework_agentic.content.sources import ContentSource
from fireflyframework_agentic.pipeline.triggers import FolderWatcher
from fireflyframework_agentic.rag._telemetry import (
    query_total_duration,
    timed_span,
)
from fireflyframework_agentic.rag.corpus import ChunkHit, SqliteCorpus, StoredChunk
from fireflyframework_agentic.rag.ingest import (
    IngestionResult,
    SchemaRegistry,
    discover_schema,
    ingest_one,
    ingest_structured,
)
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.unstructured_pipeline import (
    _doc_id_for,
    _hash_file,
)
from fireflyframework_agentic.rag.retrieval.answerer import Answer, AnswerAgent
from fireflyframework_agentic.rag.retrieval.expander import QueryExpander
from fireflyframework_agentic.rag.retrieval.hybrid import HybridRetriever
from fireflyframework_agentic.rag.retrieval.reranker import HaikuReranker
from fireflyframework_agentic.rag.retrieval.sql import StructuredRetriever, _DEFAULT_SQL_MODEL
from fireflyframework_agentic.rag.ingest.structured_registry import _DEFAULT_SCHEMA_MODEL

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CorpusStats:
    """Counts returned by :meth:`CorpusAgent.stats`."""

    doc_count: int
    chunk_count: int
    schema_count: int


@dataclass(slots=True)
class IngestSummary:
    """Aggregate result of an ``ingest_source`` / ``ingest_folder`` run."""

    results: list[IngestionResult] = field(default_factory=list)
    cursor: str | None = None

    @property
    def ingested(self) -> int:
        return sum(1 for r in self.results if r.status == "success")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status not in {"success", "skipped"})


class CorpusAgent:
    """High-level facade for ingest + query.

    Owns the lifecycles of ``SqliteCorpus``, the vector store, the
    embedder (Azure OpenAI or OpenAI), the ledger, and the three retrieval
    components (expander, retriever, answerer). The retrieval components are
    constructed lazily on the first ``query()`` call so that pure-ingest usage
    does not require ``ANTHROPIC_API_KEY``.

    Use as an async context manager or call :meth:`close` explicitly.

    Stubs for embedder / vector_store can be injected via the underscored
    parameters in tests.
    """

    def __init__(
        self,
        *,
        root: Path,
        embed_model: str,
        embed_dimension: int = 1536,
        expansion_model: str,
        answer_model: str,
        rerank_model: str,
        rerank_pool: int = 20,
        schema_model: str = _DEFAULT_SCHEMA_MODEL,
        sql_model: str = _DEFAULT_SQL_MODEL,
        # test injection — bypass the framework's real backends
        _embedder: Any | None = None,
        _vector_store: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

        self._corpus = SqliteCorpus(self.root / "corpus.sqlite")
        self._ledger: IngestLedger | None = None
        self._schema_registry: SchemaRegistry | None = None
        self._embedder: Any = _embedder
        self._vector_store: Any = _vector_store
        self._embed_model = embed_model
        self._embed_dimension = embed_dimension
        self._expansion_model = expansion_model
        self._answer_model = answer_model
        self._rerank_model = rerank_model
        self._rerank_pool = rerank_pool
        self._schema_model = schema_model
        self._sql_model = sql_model
        self._chunker = MarkdownChunker(max_chunk_tokens=600, chunk_overlap=80)
        self._loader = MarkitdownLoader()

        # Retrieval stack — lazy-constructed on first query() so ingest doesn't
        # require the LLM-side API keys (ANTHROPIC_API_KEY).
        self._expander: QueryExpander | None = None
        self._answerer: AnswerAgent | None = None
        self._retriever: HybridRetriever | None = None
        self._reranker: HaikuReranker | None = None
        self._structured_retriever: StructuredRetriever | None = None

        self._corpus_ready = False
        self._query_ready = False

    # ----- lifecycle -----------------------------------------------------

    async def _ensure_corpus_ready(self) -> None:
        if self._corpus_ready:
            return
        await self._corpus.initialise()
        if self._embedder is None:
            self._embedder = self._build_embedder(self._embed_model)
        if self._vector_store is None:
            self._vector_store = self._build_vector_store()
        self._ledger = IngestLedger(self._corpus)
        self._schema_registry = SchemaRegistry(self._corpus)
        await self._schema_registry.initialise()
        self._corpus_ready = True

    async def _ensure_query_ready(self) -> None:
        await self._ensure_corpus_ready()
        if self._query_ready:
            return
        if self._expander is None:
            self._expander = QueryExpander(model=self._expansion_model)
        if self._answerer is None:
            self._answerer = AnswerAgent(model=self._answer_model)
        if self._reranker is None:
            self._reranker = HaikuReranker(model=self._rerank_model)
        if self._retriever is None:
            self._retriever = HybridRetriever(
                corpus=self._corpus,
                vector_store=self._vector_store,
                embedder=self._embedder,
            )
        if self._structured_retriever is None:
            self._structured_retriever = StructuredRetriever(self.root / "corpus.sqlite", sql_model=self._sql_model)
        self._query_ready = True

    async def _ensure_started(self) -> None:
        """Test/explicit-init helper — fully readies the agent (corpus + query)."""
        await self._ensure_query_ready()

    # ----- backend factories ---------------------------------------------

    def _build_embedder(self, embed_model: str) -> Any:
        """Construct the embedder based on the ``provider:deployment`` model
        spec. Supports ``azure:<deployment>`` (preferred — reads
        ``EMBEDDING_BINDING_HOST`` / ``EMBEDDING_BINDING_API_KEY``) and
        ``openai:<model>`` (reads ``OPENAI_API_KEY``).
        """
        if ":" in embed_model:
            provider, deployment = embed_model.split(":", 1)
        else:
            provider, deployment = "openai", embed_model

        if provider == "azure":
            from fireflyframework_agentic.embeddings.providers.azure import AzureEmbedder

            azure_endpoint = os.environ.get("EMBEDDING_BINDING_HOST")
            api_key = os.environ.get("EMBEDDING_BINDING_API_KEY")
            if not azure_endpoint:
                raise RuntimeError("Azure embedder requires EMBEDDING_BINDING_HOST in the environment.")
            if not api_key:
                raise RuntimeError("Azure embedder requires EMBEDDING_BINDING_API_KEY in the environment.")
            return AzureEmbedder(
                model=deployment,
                azure_endpoint=azure_endpoint,
                api_key=api_key,
            )

        if provider == "openai":
            from fireflyframework_agentic.embeddings.providers.openai import OpenAIEmbedder

            return OpenAIEmbedder(model=deployment)

        raise ValueError(f"Unknown embedding provider {provider!r} (use 'azure:<deployment>' or 'openai:<model>').")

    def _build_vector_store(self) -> Any:
        from fireflyframework_agentic.vectorstores.sqlite_vec_store import SqliteVecVectorStore

        return SqliteVecVectorStore(
            db_path=self.root / "corpus.sqlite",
            dimension=self._embed_dimension,
        )

    # ----- public API ----------------------------------------------------

    async def _ingest_structured_file(self, path: Path) -> IngestionResult:
        assert self._ledger is not None
        assert self._schema_registry is not None
        doc_id = _doc_id_for(path)
        source_path = str(path.resolve())
        file_hash = _hash_file(path)
        if await self._ledger.should_skip(doc_id, file_hash):
            return IngestionResult(doc_id=doc_id, source_path=source_path, status="skipped", n_chunks=0)
        try:
            schema = await discover_schema(path, model=self._schema_model)
            await ingest_structured(path, self.root / "corpus.sqlite", schema)
            await self._schema_registry.save(schema)
            await self._ledger.upsert(doc_id, source_path, file_hash, status="success")
            return IngestionResult(doc_id=doc_id, source_path=source_path, status="success", n_chunks=0)
        except Exception as exc:
            log.warning("structured ingest failed for %s: %s", path, exc)
            await self._ledger.upsert(doc_id, source_path, file_hash, status="load_failed")
            return IngestionResult(doc_id=doc_id, source_path=source_path, status="load_failed", n_chunks=0)

    async def ingest_one(
        self,
        path: Path,
        *,
        mode: Literal["unstructured", "structured"] = "unstructured",
    ) -> IngestionResult:
        await self._ensure_corpus_ready()
        assert self._ledger is not None
        if mode == "structured":
            return await self._ingest_structured_file(path)
        return await ingest_one(
            path=Path(path),
            corpus=self._corpus,
            vector_store=self._vector_store,
            embedder=self._embedder,
            ledger=self._ledger,
            chunker=self._chunker,
            loader=self._loader,
        )

    async def ingest_folder(
        self,
        folder: Path,
        *,
        mode: Literal["unstructured", "structured"] = "unstructured",
    ) -> IngestSummary:
        """Recursively ingest every (non-hidden) file under ``folder``.

        For ``mode='unstructured'`` (default), delegates to :meth:`ingest_source`
        via :class:`LocalFolderSource`. For ``mode='structured'``, runs a direct
        loop calling :meth:`ingest_one` so each file goes through schema discovery
        and SQLite insertion rather than the embedding pipeline.
        """
        if mode == "structured":
            await self._ensure_corpus_ready()
            watcher = FolderWatcher(folder=Path(folder))
            candidates = sorted(p for p in Path(folder).rglob("*") if p.is_file() and not watcher.is_hidden(p))
            results: list[IngestionResult] = []
            for path in candidates:
                results.append(await self.ingest_one(path, mode="structured"))
            return IngestSummary(results=results)

        from fireflyframework_agentic.content.sources.local_folder import (
            LocalFolderSource,
            LocalFolderSourceConfig,
        )

        source = LocalFolderSource(LocalFolderSourceConfig(folder=Path(folder)))
        return await self.ingest_source(source)

    async def ingest_source(self, source: ContentSource) -> IngestSummary:
        """Pull every changed file from ``source`` and ingest it.

        Drives the unified ContentSource loop:
        ``list_changed`` → per item ``fetch`` → ``ingest_one`` → after the
        iterator drains, ``commit_delta`` with the source's pending cursor.

        Per-file fetch / ingest errors are logged and counted in the
        returned :class:`IngestSummary`; they do not interrupt iteration.
        Source-level errors (auth, network, malformed cursor) propagate.
        """
        await self._ensure_corpus_ready()
        assert self._ledger is not None

        async with timed_span(
            "firefly.rag.ingest_source",
            attributes={"source": source.__class__.__name__},
        ) as span:
            results: list[IngestionResult] = []
            cursor = await source.current_cursor()

            async for raw in source.list_changed(cursor):
                try:
                    local_path = await source.fetch(raw)
                except Exception as exc:  # noqa: BLE001 — per-file isolation
                    # TODO: also record this failure in the IngestLedger so the file
                    # is replayable next run. Today the in-memory IngestionResult is
                    # only surfaced through the returned IngestSummary; the cursor
                    # advances past the file because the iterator drained, so a
                    # failed fetch is effectively dropped from operational replay.
                    # Tracked as part of Task 5 / follow-up.
                    log.warning("fetch failed for %s: %s", raw.source_id, exc)
                    results.append(
                        IngestionResult(
                            doc_id=raw.source_id,
                            source_path=raw.source_id,
                            status="failed",
                            n_chunks=0,
                        )
                    )
                    continue

                results.append(await self.ingest_one(local_path))

            new_cursor = await source.pending_cursor()
            if new_cursor:
                await source.commit_delta(new_cursor)

            summary = IngestSummary(results=results, cursor=new_cursor)
            span.set_attribute("firefly.rag.terminal.success", summary.ingested)
            span.set_attribute("firefly.rag.terminal.skipped", summary.skipped)
            span.set_attribute("firefly.rag.terminal.failed", summary.failed)
            return summary

    async def watch(self, folder: Path) -> AsyncIterator[IngestionResult]:
        await self._ensure_corpus_ready()
        watcher = FolderWatcher(folder=Path(folder))
        async for path in watcher.startup_scan():
            yield await self.ingest_one(path)
        async for path in watcher.watch():
            yield await self.ingest_one(path)

    async def watch_source(
        self,
        source: ContentSource,
        *,
        interval: float = 60.0,
    ) -> AsyncIterator[IngestionResult]:
        """Poll ``source.list_changed`` on a timer; yield per-file results.

        After each successful drain of the iterator, the source's
        ``pending_cursor`` is committed, so the next tick only sees newly
        changed files. Caller cancels by exiting the iteration (``break``,
        task cancellation, etc.).
        """
        await self._ensure_corpus_ready()
        while True:
            cursor = await source.current_cursor()
            async for raw in source.list_changed(cursor):
                try:
                    local_path = await source.fetch(raw)
                except Exception as exc:  # noqa: BLE001
                    log.warning("fetch failed for %s: %s", raw.source_id, exc)
                    yield IngestionResult(
                        doc_id=raw.source_id,
                        source_path=raw.source_id,
                        status="failed",
                        n_chunks=0,
                    )
                    continue
                yield await self.ingest_one(local_path)

            new_cursor = await source.pending_cursor()
            if new_cursor:
                await source.commit_delta(new_cursor)

            await asyncio.sleep(interval)

    async def retrieve(
        self,
        question: str,
        *,
        top_k: int = 5,
        rerank: bool = True,
    ) -> list[ChunkHit]:
        """Run expand → hybrid retrieve → (optional) rerank.

        Returns the ranked chunk hits without invoking the answer LLM. Use
        this when the caller wants to compose its own answer or display raw
        evidence to the user. ``query`` calls into this method.
        """
        await self._ensure_query_ready()
        assert self._expander is not None
        assert self._retriever is not None
        assert self._reranker is not None

        async with timed_span(
            "firefly.rag.retrieve",
            attributes={"question": question, "top_k": top_k, "rerank": rerank},
        ):
            queries = await self._expander.expand(question)
            candidates = await self._retriever.retrieve(
                queries,
                top_k_per_query=30,
                top_k_final=self._rerank_pool if rerank else top_k,
            )
            if rerank:
                return await self._reranker.rerank(question, candidates, top_k=top_k)
            return candidates[:top_k]

    async def query(self, question: str, *, top_k: int = 5) -> Answer:
        """Run the full pipeline: retrieve (with rerank) + answer.

        RAG retrieval and SQL retrieval run in parallel via ``asyncio.gather``.
        ``top_k`` is the number of chunks fed into the answer agent *after* reranking.
        """
        await self._ensure_query_ready()
        assert self._answerer is not None
        assert self._structured_retriever is not None
        assert self._schema_registry is not None

        query_start = time.perf_counter()
        async with timed_span(
            "firefly.rag.query",
            attributes={
                "question": question,
                "top_k": top_k,
                "rerank_pool": self._rerank_pool,
            },
        ) as span:
            schemas = await self._schema_registry.list_schemas()
            top_hits, sql_context = await asyncio.gather(
                self.retrieve(question, top_k=top_k, rerank=True),
                self._structured_retriever.retrieve(question, schemas),
            )
            answer = await self._answerer.answer(question, top_hits, sql_context=sql_context)
            outcome = "no_info" if not answer.cited_sources else "answered"
            elapsed_ms = (time.perf_counter() - query_start) * 1000.0
            query_total_duration.record(elapsed_ms, {"outcome": outcome})
            span.set_attribute("firefly.rag.citation_count", len(answer.cited_sources))
            span.set_attribute("firefly.rag.outcome", outcome)
            return answer

    async def stats(self) -> CorpusStats:
        """Return document, chunk, and schema counts for the corpus."""
        await self._ensure_corpus_ready()
        rows = await self._corpus.query("SELECT COUNT(DISTINCT doc_id) AS n FROM chunks")
        doc_count = rows[0]["n"] if rows else 0
        rows = await self._corpus.query("SELECT COUNT(*) AS n FROM chunks")
        chunk_count = rows[0]["n"] if rows else 0
        rows = await self._corpus.query("SELECT COUNT(*) AS n FROM _schemas")
        schema_count = rows[0]["n"] if rows else 0
        return CorpusStats(doc_count=doc_count, chunk_count=chunk_count, schema_count=schema_count)

    async def clear(self) -> None:
        """Wipe all ingested data: chunks, ledger, structured tables, and schemas.

        The corpus file stays open and ready for new ingestion. If the vector
        store exposes a ``clear()`` method it is called too; otherwise orphaned
        vectors remain in the store but will never be returned (chunk IDs are
        resolved through the corpus, which is now empty).
        """
        await self._ensure_corpus_ready()
        await self._corpus.clear_all()
        if self._vector_store is not None and hasattr(self._vector_store, "clear"):
            await self._vector_store.clear()

    async def get_chunk(self, chunk_id: str) -> StoredChunk | None:
        """Retrieve a single chunk by its ID, or ``None`` if not found."""
        await self._ensure_corpus_ready()
        chunks = await self._corpus.get_chunks([chunk_id])
        return chunks[0] if chunks else None

    async def close(self) -> None:
        await self._corpus.close()
        if self._vector_store is not None and hasattr(self._vector_store, "close"):
            await self._vector_store.close()
        self._corpus_ready = False
        self._query_ready = False

    async def __aenter__(self) -> CorpusAgent:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()
