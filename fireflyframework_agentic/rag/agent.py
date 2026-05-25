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
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

try:
    import openpyxl
except ImportError:  # pragma: no cover - optional dep
    openpyxl = None  # type: ignore[assignment]

from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker
from fireflyframework_agentic.content.sources import ContentSource
from fireflyframework_agentic.content.sources.local_folder import LocalFolderSource, LocalFolderSourceConfig
from fireflyframework_agentic.embeddings.providers.azure import AzureEmbedder
from fireflyframework_agentic.embeddings.providers.openai import OpenAIEmbedder
from fireflyframework_agentic.pipeline.triggers import FolderWatcher
from fireflyframework_agentic.rag._telemetry import (
    query_total_duration,
    timed_span,
)
from fireflyframework_agentic.rag.corpus import ChunkHit, SqliteCorpus, StoredChunk
from fireflyframework_agentic.rag.ingest import (
    IngestionResult,
    SchemaFeedback,
    SchemaRegistry,
    TargetSchema,
    discover_schema,
    discover_schema_for_paths,
    discover_schema_interactive,
    ingest_one,
    ingest_structured,
)
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.structured_pipeline import _normalize_sheet_name
from fireflyframework_agentic.rag.ingest.structured_registry import is_tabular_file
from fireflyframework_agentic.rag.ingest.unstructured_pipeline import (
    doc_id_for,
    hash_file,
)
from fireflyframework_agentic.rag.retrieval.answerer import Answer, AnswerAgent
from fireflyframework_agentic.rag.retrieval.expander import QueryExpander
from fireflyframework_agentic.rag.retrieval.hybrid import HybridRetriever
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import ReasoningAnswerAgent
from fireflyframework_agentic.rag.retrieval.reranker import HaikuReranker
from fireflyframework_agentic.rag.retrieval.sql import StructuredRetriever
from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
from fireflyframework_agentic.vectorstores.sqlite_vec_store import SqliteVecVectorStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CorpusStats:
    """Counts returned by :meth:`CorpusAgent.stats`."""

    doc_count: int
    chunk_count: int
    schema_count: int


def _collect_structured_candidates(folder: Path) -> list[Path]:
    """Walk *folder* recursively and return only tabular files.

    Skips hidden files (via :class:`FolderWatcher.is_hidden`) and files whose
    suffix isn't recognised by the structured pipeline (CSV / Excel). This
    lets a drop folder safely contain a mix of unstructured documents (PDF,
    PPTX, DOCX, …) and tabular sources without the structured discovery /
    ingest paths trying to read binaries as CSV.

    Logs an INFO summary of skipped suffixes per call, and a WARNING when
    the folder yields zero tabular candidates but contains non-tabular
    files — that's a strong signal the operator pointed a structured tool
    at an unstructured drop folder, which would otherwise look like a
    silent no-op success.
    """
    watcher = FolderWatcher(folder=folder)
    candidates: list[Path] = []
    skipped_suffixes: set[str] = set()
    skipped_count = 0
    for p in folder.rglob("*"):
        if not p.is_file() or watcher.is_hidden(p):
            continue
        if is_tabular_file(p):
            candidates.append(p)
        else:
            skipped_suffixes.add(p.suffix.lower() or "<no-ext>")
            skipped_count += 1
    candidates.sort()
    if skipped_count:
        log.info(
            "structured walk skipped %d non-tabular file(s) under %s (e.g. %s)",
            skipped_count,
            folder,
            ", ".join(sorted(skipped_suffixes)),
        )
    if not candidates and skipped_count:
        log.warning(
            "structured walk found 0 tabular files (.csv/.xls/.xlsx) under %s "
            "but %d non-tabular file(s) were present (suffixes: %s) — pointing "
            "this tool at a folder of unstructured documents is a no-op; route "
            "those through ingest_corpus_filesystem instead.",
            folder,
            skipped_count,
            ", ".join(sorted(skipped_suffixes)),
        )
    return candidates


def _filter_schema_for_path(schema: TargetSchema, path: Path) -> TargetSchema | None:
    """Pick the ``TableSpec``s in *schema* that belong to *path*.

    For a CSV: match the single TableSpec whose snake_case name equals the
    file stem. For an Excel workbook: match every TableSpec whose name is one
    of the workbook's sheet names. Returns ``None`` if no table matches —
    caller falls back to per-file discovery.
    """
    suffix = path.suffix.lower()
    if suffix in (".xls", ".xlsx"):
        try:
            if openpyxl is None:
                raise ImportError(
                    "openpyxl is required for Excel ingestion. "
                    "Install with: pip install fireflyframework-agentic[rag]"
                )

            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            wanted = {_normalize_sheet_name(s) for s in wb.sheetnames}
            wb.close()
        except Exception:
            return None
        tables = [t for t in schema.tables if t.name in wanted]
    else:
        target = _normalize_sheet_name(path.stem)
        tables = [t for t in schema.tables if t.name == target]
    if not tables:
        return None
    return TargetSchema(tables=tables)


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
        schema_model: str = "anthropic:claude-sonnet-4-6",
        sql_model: str = "anthropic:claude-haiku-4-5-20251001",
        answer_strategy: Literal["fast", "reasoning"] = "fast",
        max_reasoning_tool_calls: int = 20,
        max_reasoning_llm_calls: int = 10,
        reasoning_wall_clock_seconds: float = 120.0,
        # test injection — bypass the framework's real backends
        _embedder: Any | None = None,
        _vector_store: Any | None = None,
        db_store: DatabaseStore | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

        if db_store is None:
            db_store = DatabaseStore(
                LocalBackend(self.root / "corpus.sqlite"),
                store_id=f"corpus_search:{self.root.resolve()}",
            )
        self._db_store = db_store
        self._corpus = SqliteCorpus(self._db_store)
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
        self._answer_strategy = answer_strategy
        self._max_reasoning_tool_calls = max_reasoning_tool_calls
        self._max_reasoning_llm_calls = max_reasoning_llm_calls
        self._reasoning_wall_clock = reasoning_wall_clock_seconds
        self._chunker = MarkdownChunker(max_chunk_tokens=600, chunk_overlap=80)
        self._loader = MarkitdownLoader()

        # Retrieval stack — lazy-constructed on first query() so ingest doesn't
        # require the LLM-side API keys (ANTHROPIC_API_KEY).
        self._expander: QueryExpander | None = None
        # AnswerAgent (fast) or ReasoningAnswerAgent (reasoning); resolved
        # lazily in _ensure_query_ready based on self._answer_strategy.
        self._answerer: Any = None
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
        if self._reranker is None:
            self._reranker = HaikuReranker(model=self._rerank_model)
        if self._retriever is None:
            self._retriever = HybridRetriever(
                corpus=self._corpus,
                vector_store=self._vector_store,
                embedder=self._embedder,
            )
        if self._structured_retriever is None:
            # Route through _db_store.ensure_fresh() so cloud backends
            # (e.g. AzureBlobBackend) materialize a local copy of the
            # sqlite file before StructuredRetriever opens it. On
            # LocalBackend this is a near no-op and returns the same
            # path as self.root / "corpus.sqlite".
            sqlite_path, _generation = await self._db_store.ensure_fresh()
            self._structured_retriever = StructuredRetriever(sqlite_path, sql_model=self._sql_model)
        # Answerer must be constructed AFTER structured_retriever so the
        # reasoning branch can pass it in.
        if self._answerer is None:
            if self._answer_strategy == "reasoning":
                assert self._schema_registry is not None
                self._answerer = ReasoningAnswerAgent(
                    model=self._answer_model,
                    corpus_agent=self,
                    structured_retriever=self._structured_retriever,
                    schema_registry=self._schema_registry,
                    db_path=self.root / "corpus.sqlite",
                    max_tool_calls=self._max_reasoning_tool_calls,
                    max_llm_calls=self._max_reasoning_llm_calls,
                    wall_clock_seconds=self._reasoning_wall_clock,
                )
            else:
                self._answerer = AnswerAgent(model=self._answer_model)
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
            return OpenAIEmbedder(model=deployment)

        raise ValueError(f"Unknown embedding provider {provider!r} (use 'azure:<deployment>' or 'openai:<model>').")

    def _build_vector_store(self) -> Any:
        return SqliteVecVectorStore(
            self._db_store,
            dimension=self._embed_dimension,
        )

    # ----- public API ----------------------------------------------------

    async def _ingest_structured_file(
        self,
        path: Path,
        *,
        on_review: Callable[[TargetSchema], Awaitable[SchemaFeedback]] | None = None,
        force: bool = False,
        schema: TargetSchema | None = None,
    ) -> IngestionResult:
        """Ingest a single tabular file.

        When *schema* is provided, schema discovery is skipped — caller
        already supplied the target shape (e.g. operator-reviewed output of
        :meth:`discover_schema`, or a canonical schema reused across files).
        """
        assert self._ledger is not None
        assert self._schema_registry is not None
        doc_id = doc_id_for(path)
        source_path = str(path.resolve())
        file_hash = hash_file(path)
        if not force and await self._ledger.should_skip(doc_id, file_hash):
            return IngestionResult(doc_id=doc_id, source_path=source_path, status="skipped", n_chunks=0)
        try:
            if schema is None:
                if on_review is not None:
                    schema = await discover_schema_interactive(path, on_review=on_review, model=self._schema_model)
                else:
                    schema = await discover_schema(path, model=self._schema_model)
            ingest_result = await ingest_structured(path, self._db_store, schema)
            # ``partial`` is a load-some-rows outcome (e.g. composite-PK
            # placeholder rows like ``('-', '-')`` violated UNIQUE, but
            # 680 valid rows committed). Treat it as success for ledger
            # purposes — the data IS in the corpus — but surface every
            # per-row error as a warning so the user can decide whether
            # to clean up the source. Only ``failed`` (zero rows
            # inserted) blocks the ledger.
            for name, meta in ingest_result.items():
                if meta.get("status") in ("partial", "failed"):
                    log.warning(
                        "structured ingest table %s %s for %s: %s",
                        name,
                        meta.get("status"),
                        path,
                        "; ".join(meta.get("errors", [])) or meta.get("status"),
                    )
            hard_failures = {name: meta for name, meta in ingest_result.items() if meta.get("status") == "failed"}
            if hard_failures:
                await self._ledger.upsert(doc_id, source_path, file_hash, status="load_failed")
                return IngestionResult(doc_id=doc_id, source_path=source_path, status="load_failed", n_chunks=0)
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
        on_review: Callable[[TargetSchema], Awaitable[SchemaFeedback]] | None = None,
        force: bool = False,
        schema: TargetSchema | None = None,
    ) -> IngestionResult:
        await self._ensure_corpus_ready()
        assert self._ledger is not None
        if mode == "structured":
            return await self._ingest_structured_file(path, on_review=on_review, force=force, schema=schema)
        return await ingest_one(
            path=Path(path),
            corpus=self._corpus,
            vector_store=self._vector_store,
            embedder=self._embedder,
            ledger=self._ledger,
            chunker=self._chunker,
            loader=self._loader,
            force=force,
        )

    async def discover_schema(
        self,
        path: Path,
        *,
        corrections: str = "",
        previous_schema: TargetSchema | None = None,
    ) -> TargetSchema:
        """Infer a ``TargetSchema`` for *path* without ingesting anything.

        Accepts a single CSV/Excel file or a folder. For a folder, discovery
        is run across every (non-hidden) file in one LLM call so cross-file
        foreign keys can be proposed. The returned schema is **not** persisted
        to the schema registry — callers that want to ingest under it should
        pass it back via :meth:`ingest_one` / :meth:`ingest_folder` ``schema=``.

        Pass *corrections* + *previous_schema* to iteratively refine an
        earlier discovery output ("rename column X to Y", "amount should be
        nullable", "add foreign_key from billing.customer_id to
        customers.id"); both must be supplied together.
        """
        await self._ensure_corpus_ready()
        target = Path(path)
        if target.is_file():
            return await discover_schema(
                target,
                model=self._schema_model,
                corrections=corrections,
                previous_schema=previous_schema,
            )
        candidates = _collect_structured_candidates(target)
        return await discover_schema_for_paths(
            candidates,
            model=self._schema_model,
            corrections=corrections,
            previous_schema=previous_schema,
        )

    async def ingest_folder(
        self,
        folder: Path,
        *,
        mode: Literal["unstructured", "structured"] = "unstructured",
        on_review: Callable[[TargetSchema], Awaitable[SchemaFeedback]] | None = None,
        force: bool = False,
        schema: TargetSchema | None = None,
    ) -> IngestSummary:
        """Recursively ingest every (non-hidden) file under ``folder``.

        For ``mode='unstructured'`` (default), delegates to :meth:`ingest_source`
        via :class:`LocalFolderSource`. For ``mode='structured'``, runs schema
        discovery once across the whole folder (so cross-file foreign keys are
        visible) and then ingests each file under the matching ``TableSpec``.
        ``on_review`` and ``force`` are only honoured by the structured branch
        (the unstructured ContentSource path has its own change-detection
        model). When *schema* is supplied, discovery is skipped entirely.
        """
        if mode == "structured":
            await self._ensure_corpus_ready()
            candidates = _collect_structured_candidates(Path(folder))
            folder_schema = schema
            if folder_schema is None and len(candidates) > 1:
                folder_schema = await discover_schema_for_paths(candidates, model=self._schema_model)
                if on_review is not None:
                    feedback = await on_review(folder_schema)
                    if not feedback.approved:
                        # Rerun discovery once with corrections — keep the
                        # interactive loop shallow at folder level so
                        # per-folder UX matches per-file UX (one approval).
                        folder_schema = await discover_schema_for_paths(candidates, model=self._schema_model)
            results: list[IngestionResult] = []
            for path in candidates:
                per_file_schema = _filter_schema_for_path(folder_schema, path) if folder_schema else None
                results.append(
                    await self.ingest_one(
                        path,
                        mode="structured",
                        on_review=on_review if per_file_schema is None else None,
                        force=force,
                        schema=per_file_schema,
                    )
                )
            return IngestSummary(results=results)

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
                    # The cursor advances past this file because the iterator
                    # drained, so we persist the failure to the ledger to keep
                    # it observable for retries / audits. content_hash is empty
                    # because the fetch never produced bytes; should_skip() will
                    # not match this row against any real hash, so a future run
                    # that successfully fetches the same source will re-ingest.
                    log.warning("fetch failed for %s: %s", raw.source_id, exc)
                    await self._ledger.upsert(
                        doc_id=raw.source_id,
                        source_path=raw.source_id,
                        content_hash="",
                        status="failed",
                    )
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

    async def query(self, question: str, *, top_k: int = 5, include_trace: bool = False) -> Answer:
        """Run the full pipeline: retrieve (with rerank) + answer.

        Under ``answer_strategy="fast"`` (default): runs RAG retrieval and SQL
        retrieval in parallel via ``asyncio.gather``, then feeds both into a
        one-shot AnswerAgent. ``top_k`` is the number of chunks fed into the
        answerer *after* reranking. ``include_trace`` is a no-op on this path.

        Under ``answer_strategy="reasoning"``: delegates the whole answer
        phase to a ReasoningAnswerAgent that calls knowledge_search /
        sql_query / inspect_table / python_compute tools as it sees fit.
        ``top_k`` and the up-front retrieval are no longer authoritative —
        the tool decides. Pass ``include_trace=True`` to attach the typed
        ReasoningTrace to the returned Answer for reproducibility.
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
                "firefly.rag.answer_strategy": self._answer_strategy,
            },
        ) as span:
            # ``self._answerer`` is concretely a ``ReasoningAnswerAgent`` on the
            # reasoning branch and an ``AnswerAgent`` on the fast branch —
            # they have different ``answer(...)`` signatures, dispatched here
            # by ``self._answer_strategy``. The field is typed ``Any`` because
            # importing ``ReasoningAnswerAgent`` at class-definition time would
            # introduce a circular import (it lives under ``rag.retrieval``,
            # which imports ``rag.agent``).
            if self._answer_strategy == "reasoning":
                answer = await self._answerer.answer(question, include_trace=include_trace)
            else:
                schemas = await self._schema_registry.list_schemas()
                top_hits, sql_outcome = await asyncio.gather(
                    self.retrieve(question, top_k=top_k, rerank=True),
                    self._structured_retriever.retrieve(question, schemas),
                )
                answer = await self._answerer.answer(question, top_hits, sql_outcome=sql_outcome)
            outcome = "no_info" if not answer.cited_sources else "answered"
            elapsed_ms = (time.perf_counter() - query_start) * 1000.0
            query_total_duration.record(elapsed_ms, {"outcome": outcome})
            span.set_attribute("firefly.rag.citation_count", len(answer.cited_sources))
            span.set_attribute("firefly.rag.outcome", outcome)
            return answer

    async def list_schemas(self) -> list[TargetSchema]:
        """Return every ``TargetSchema`` saved by structured ingestion.

        Returns an empty list when the corpus has only ever ingested
        unstructured documents. Used by read-only tools (``list_corpus_schemas``,
        ``corpus_sql``) that need to surface or whitelist the structured
        tables without invoking the SQL retriever's LLM loop.
        """
        await self._ensure_corpus_ready()
        assert self._schema_registry is not None
        return await self._schema_registry.list_schemas()

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
