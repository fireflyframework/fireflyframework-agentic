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

"""Verify the rag instrumentation emits the expected spans.

We attach an ``InMemorySpanExporter`` to the existing global tracer
provider (whatever ``configure_exporters`` left in place) and run a
minimal ingest + query path with stubs, then assert the expected span
names show up.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.corpus import SqliteCorpus
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.pipeline import ingest_one


class _StubEmbedder:
    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        # Trivial deterministic embeddings; dimensions don't matter for
        # the span emission test.
        vectors = [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]
        return EmbeddingResult(embeddings=vectors, model="stub", dimensions=4, usage=None)

    async def embed_one(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


class _StubVectorStore:
    def __init__(self) -> None:
        self.docs: dict[str, Any] = {}

    async def upsert(self, docs: Sequence[Any], namespace: str | None = None) -> None:
        for d in docs:
            self.docs[d.id] = d

    async def delete(self, ids: Sequence[str], namespace: str | None = None) -> None:
        for cid in ids:
            self.docs.pop(cid, None)

    async def search(self, vector: list[float], top_k: int = 30, namespace: str | None = None):
        return []


@pytest.fixture
def in_memory_exporter():
    """Attach an in-memory span exporter to the active global TracerProvider.

    Two complications make this fixture unusual:

    1. OTel's :func:`trace.set_tracer_provider` is gated by a one-shot
       :class:`_OnceLock`; subsequent calls log a warning and are
       ignored, leaving our exporter on a detached provider.
    2. ``tests/unit/observability/test_trace_propagation.py`` deliberately
       resets ``trace._TRACER_PROVIDER = None`` on teardown, so by the
       time this test runs, ``get_tracer_provider()`` returns a
       :class:`ProxyTracerProvider` (which has no ``add_span_processor``).

    The fix poke directly at ``trace._TRACER_PROVIDER`` — the same
    private slot the propagation test resets — to install a real
    :class:`TracerProvider` we control. This bypasses the one-shot
    latch and avoids the warning.
    """
    saved = trace._TRACER_PROVIDER  # type: ignore[attr-defined]
    provider = TracerProvider()
    trace._TRACER_PROVIDER = provider  # type: ignore[attr-defined]
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        yield exporter
    finally:
        exporter.clear()
        trace._TRACER_PROVIDER = saved  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_ingest_one_emits_expected_spans(in_memory_exporter, tmp_path: Path) -> None:
    # Build a tiny markdown file to ingest.
    src = tmp_path / "doc.md"
    src.write_text("# Title\n\nFirefly is a metaframework. " * 10)

    corpus = SqliteCorpus(tmp_path / "corpus.sqlite")
    await corpus.initialise()
    ledger = IngestLedger(corpus)
    embedder = _StubEmbedder()
    vector_store = _StubVectorStore()
    chunker = TextChunker(chunk_size=200, chunk_overlap=20)
    loader = MarkitdownLoader()

    in_memory_exporter.clear()

    await ingest_one(
        path=src,
        corpus=corpus,
        vector_store=vector_store,
        embedder=embedder,
        ledger=ledger,
        chunker=chunker,
        loader=loader,
    )
    await corpus.close()

    span_names = {span.name for span in in_memory_exporter.get_finished_spans()}
    # Outer + every inner stage must emit a span
    expected = {
        "rag.ingest.document",
        "rag.ingest.load",
        "rag.ingest.hash",
        "rag.ingest.chunk",
        "rag.ingest.reset",
        "rag.ingest.embed",
        "rag.ingest.store",
        "rag.ingest.ledger",
    }
    missing = expected - span_names
    assert not missing, f"missing spans: {missing}; got {span_names}"
