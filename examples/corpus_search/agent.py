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

import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from examples.corpus_search.retrieval.answerer import Answer, AnswerAgent
from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.pipeline.triggers import FolderWatcher
from fireflyframework_agentic.rag.corpus import SqliteCorpus
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.pipeline import IngestionResult, ingest_one
from fireflyframework_agentic.rag.retrieval.expander import QueryExpander
from fireflyframework_agentic.rag.retrieval.hybrid import HybridRetriever
from fireflyframework_agentic.rag.retrieval.reranker import HaikuReranker

log = logging.getLogger(__name__)


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
        # test injection — bypass the framework's real backends
        _embedder: Any | None = None,
        _vector_store: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

        self._corpus = SqliteCorpus(self.root / "corpus.sqlite")
        self._ledger: IngestLedger | None = None
        self._embedder: Any = _embedder
        self._vector_store: Any = _vector_store
        self._embed_model = embed_model
        self._embed_dimension = embed_dimension
        self._expansion_model = expansion_model
        self._answer_model = answer_model
        self._rerank_model = rerank_model
        self._rerank_pool = rerank_pool
        self._chunker = TextChunker(chunk_size=600, chunk_overlap=80)
        self._loader = MarkitdownLoader()

        # Retrieval stack — lazy-constructed on first query() so ingest doesn't
        # require the LLM-side API keys (ANTHROPIC_API_KEY).
        self._expander: QueryExpander | None = None
        self._answerer: AnswerAgent | None = None
        self._retriever: HybridRetriever | None = None
        self._reranker: HaikuReranker | None = None

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

    async def ingest_one(self, path: Path) -> IngestionResult:
        await self._ensure_corpus_ready()
        assert self._ledger is not None
        return await ingest_one(
            path=Path(path),
            corpus=self._corpus,
            vector_store=self._vector_store,
            embedder=self._embedder,
            ledger=self._ledger,
            chunker=self._chunker,
            loader=self._loader,
        )

    async def ingest_folder(self, folder: Path) -> list[IngestionResult]:
        """Recursively ingest every file under ``folder``.

        Hidden files (anything starting with ``.``) are skipped — that includes
        macOS ``.DS_Store`` metadata and editor swap files. Filtering uses
        :meth:`FolderWatcher.is_hidden` so the rules stay in sync with the
        watcher path.
        """
        await self._ensure_corpus_ready()
        root = Path(folder)
        watcher = FolderWatcher(folder=root)
        results: list[IngestionResult] = []
        candidates = sorted(p for p in root.rglob("*") if p.is_file() and not watcher.is_hidden(p))
        log.info("found %d file(s) under %s", len(candidates), root)
        for path in candidates:
            results.append(await self.ingest_one(path))
        return results

    async def watch(self, folder: Path) -> AsyncIterator[IngestionResult]:
        await self._ensure_corpus_ready()
        watcher = FolderWatcher(folder=Path(folder))
        async for path in watcher.startup_scan():
            yield await self.ingest_one(path)
        async for path in watcher.watch():
            yield await self.ingest_one(path)

    async def query(self, question: str, *, top_k: int = 5) -> Answer:
        """Run the full query pipeline: expand → retrieve → rerank → answer.

        ``top_k`` is the number of chunks fed into the answer agent
        *after* reranking. Retrieval pulls a wider pool (``rerank_pool``,
        default 20) so the reranker has enough candidates to choose
        from. Reducing ``top_k`` from 10 to 5 typically halves Sonnet's
        wall-clock time without hurting answer quality, because the
        reranker filters out low-relevance chunks first.
        """
        await self._ensure_query_ready()
        assert self._expander is not None
        assert self._retriever is not None
        assert self._reranker is not None
        assert self._answerer is not None

        queries = await self._expander.expand(question)
        # Cast a wider net for the reranker to choose from. The reranker
        # then narrows to top_k by judged relevance — better precision
        # than RRF-positional alone.
        candidates = await self._retriever.retrieve(
            queries,
            top_k_per_query=30,
            top_k_final=self._rerank_pool,
        )
        top_hits = await self._reranker.rerank(question, candidates, top_k=top_k)
        return await self._answerer.answer(question, top_hits)

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
