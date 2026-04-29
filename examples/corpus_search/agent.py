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
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from examples.corpus_search.corpus import SqliteCorpus
from examples.corpus_search.ingest.ledger import IngestLedger
from examples.corpus_search.ingest.pipeline import IngestionResult, ingest_one
from examples.corpus_search.retrieval.answerer import Answer, AnswerAgent
from examples.corpus_search.retrieval.expander import QueryExpander
from examples.corpus_search.retrieval.hybrid import HybridRetriever
from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.pipeline.triggers import FolderWatcher

log = logging.getLogger(__name__)


class CorpusAgent:
    """High-level facade for ingest + query.

    Owns the lifecycles of ``SqliteCorpus``, the Chroma vector store, the OpenAI
    embedder, the ledger, and the three retrieval components (expander,
    retriever, answerer). Use as an async context manager or call :meth:`close`
    explicitly.

    Stubs for embedder / vector_store can be injected via the underscored
    parameters in tests.
    """

    def __init__(
        self,
        *,
        root: Path,
        embed_model: str,
        expansion_model: str,
        answer_model: str,
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
        self._chunker = TextChunker(chunk_size=600, chunk_overlap=80)
        self._loader = MarkitdownLoader()

        self._expander = QueryExpander(model=expansion_model)
        self._retriever: HybridRetriever | None = None
        self._answerer = AnswerAgent(model=answer_model)

        self._started = False

    async def _ensure_started(self) -> None:
        if self._started:
            return
        await self._corpus.initialise()
        if self._embedder is None:
            from fireflyframework_agentic.embeddings.providers.openai import OpenAIEmbedder
            model_name = self._embed_model.split(":", 1)[-1]
            self._embedder = OpenAIEmbedder(model=model_name)
        if self._vector_store is None:
            import chromadb
            from chromadb.config import Settings

            from fireflyframework_agentic.vectorstores.chroma_store import ChromaVectorStore
            client = chromadb.PersistentClient(
                path=str(self.root / "chroma"),
                settings=Settings(anonymized_telemetry=False),
            )
            self._vector_store = ChromaVectorStore(
                collection_name="corpus_chunks",
                client=client,
            )
        self._ledger = IngestLedger(self._corpus)
        self._retriever = HybridRetriever(
            corpus=self._corpus,
            vector_store=self._vector_store,
            embedder=self._embedder,
        )
        self._started = True

    async def ingest_one(self, path: Path) -> IngestionResult:
        await self._ensure_started()
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
        await self._ensure_started()
        results: list[IngestionResult] = []
        for path in sorted(Path(folder).iterdir()):
            if path.is_file():
                results.append(await self.ingest_one(path))
        return results

    async def watch(self, folder: Path) -> AsyncIterator[IngestionResult]:
        await self._ensure_started()
        watcher = FolderWatcher(folder=Path(folder))
        async for path in watcher.startup_scan():
            yield await self.ingest_one(path)
        async for path in watcher.watch():
            yield await self.ingest_one(path)

    async def query(self, question: str) -> Answer:
        await self._ensure_started()
        assert self._retriever is not None
        queries = await self._expander.expand(question)
        hits = await self._retriever.retrieve(queries, top_k_per_query=30, top_k_final=10)
        return await self._answerer.answer(question, hits)

    async def close(self) -> None:
        await self._corpus.close()
        self._started = False
