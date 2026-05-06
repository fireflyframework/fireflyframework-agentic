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

from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.agent import CorpusAgent, CorpusStats
from fireflyframework_agentic.rag.corpus import StoredChunk


class _StubEmbedder:
    async def embed(self, texts: list[str], **_: Any) -> EmbeddingResult:
        return EmbeddingResult(
            embeddings=[[0.0] * 4 for _ in texts],
            model="stub",
            usage=None,
            dimensions=4,
        )

    async def embed_one(self, _text: str, **_: Any) -> list[float]:
        return [0.0] * 4


class _StubVectorStore:
    def __init__(self) -> None:
        self._docs: dict[str, Any] = {}
        self.cleared = False

    async def upsert(self, documents: Any, _namespace: str = "default") -> None:
        pass  # chunks land in SqliteCorpus; vector search isn't exercised here

    async def delete(self, ids: Any, _namespace: str = "default") -> None:
        for i in ids:
            self._docs.pop(i, None)

    async def clear(self) -> None:
        self._docs.clear()
        self.cleared = True


def _make_agent(tmp_path: Path) -> CorpusAgent:
    return CorpusAgent(
        root=tmp_path / "corpus",
        embed_model="openai:text-embedding-3-small",
        embed_dimension=4,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-haiku-4-5-20251001",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=_StubEmbedder(),
        _vector_store=_StubVectorStore(),
    )


_DOC = """\
# Overview

This document covers several important topics in sufficient depth for the
markdown chunker to produce at least one chunk. Short stubs get dropped by
the chunker's minimum-size guard, so this fixture uses a realistic length.

## Details

The embedding pipeline embeds each chunk independently and stores vectors
alongside the text in the corpus. Stats are derived from the chunks table,
so a successful ingest must produce at least one chunk to register a doc.
"""


async def _ingest_md(agent: CorpusAgent, tmp_path: Path, name: str, content: str = _DOC) -> None:
    p = tmp_path / name
    p.write_text(content)
    await agent.ingest_one(p)


@pytest.mark.asyncio
async def test_stats_empty_corpus(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    stats = await agent.stats()
    assert isinstance(stats, CorpusStats)
    assert stats.doc_count == 0
    assert stats.chunk_count == 0
    assert stats.schema_count == 0
    await agent.close()


@pytest.mark.asyncio
async def test_stats_after_ingest(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    await _ingest_md(agent, tmp_path, "a.md")
    await _ingest_md(agent, tmp_path, "b.md")
    stats = await agent.stats()
    assert stats.doc_count == 2
    assert stats.chunk_count >= 2
    assert stats.schema_count == 0
    await agent.close()


@pytest.mark.asyncio
async def test_clear_wipes_chunks_and_ingestions(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    await _ingest_md(agent, tmp_path, "doc.md")
    before = await agent.stats()
    assert before.doc_count == 1

    await agent.clear()

    after = await agent.stats()
    assert after.doc_count == 0
    assert after.chunk_count == 0
    await agent.close()


@pytest.mark.asyncio
async def test_clear_calls_vector_store_clear(tmp_path: Path) -> None:
    vs = _StubVectorStore()
    agent = CorpusAgent(
        root=tmp_path / "corpus",
        embed_model="openai:text-embedding-3-small",
        embed_dimension=4,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-haiku-4-5-20251001",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=_StubEmbedder(),
        _vector_store=vs,
    )
    await _ingest_md(agent, tmp_path, "doc.md")
    await agent.clear()
    assert vs.cleared
    await agent.close()


@pytest.mark.asyncio
async def test_clear_allows_reingest(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    p = tmp_path / "doc.md"
    p.write_text(_DOC)
    result1 = await agent.ingest_one(p)
    assert result1.status == "success"

    await agent.clear()

    # After clear the ledger is wiped, so same file ingests again as success
    result2 = await agent.ingest_one(p)
    assert result2.status == "success"
    await agent.close()


@pytest.mark.asyncio
async def test_get_chunk_returns_none_for_missing_id(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    chunk = await agent.get_chunk("nonexistent_id")
    assert chunk is None
    await agent.close()


@pytest.mark.asyncio
async def test_get_chunk_returns_stored_chunk(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    await _ingest_md(agent, tmp_path, "doc.md")
    stats = await agent.stats()
    assert stats.chunk_count > 0

    # Pull any chunk_id from the corpus directly
    rows = await agent._corpus.query("SELECT chunk_id FROM chunks LIMIT 1")
    chunk_id = rows[0]["chunk_id"]

    chunk = await agent.get_chunk(chunk_id)
    assert chunk is not None
    assert isinstance(chunk, StoredChunk)
    assert chunk.chunk_id == chunk_id
    await agent.close()
