# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Integration-style unit tests for the corpus_rag MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.exceptions import ToolError
from fireflyframework_agentic.rag.exceptions import CorpusNotFoundError


@pytest.fixture
def configured_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "corpora"))
    monkeypatch.setenv("EMBEDDING_MODEL", "openai:text-embedding-3-small")
    monkeypatch.setenv("EXPANSION_MODEL", "anthropic:claude-haiku-4-5-20251001")
    monkeypatch.setenv("ANSWER_MODEL", "anthropic:claude-sonnet-4-6")
    monkeypatch.setenv("RERANK_MODEL", "anthropic:claude-haiku-4-5-20251001")
    return tmp_path


class _StubEmbedder:
    dimension = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class _StubVectorStore:
    def __init__(self) -> None:
        self._docs: list[Any] = []

    async def upsert(self, docs: list[Any]) -> None:
        self._docs.extend(docs)

    async def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def delete_by_doc_id(self, doc_id: str) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.fixture
def stub_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch CorpusAgent's backend factories so tests don't hit the network."""
    from fireflyframework_agentic.rag import agent as agent_mod

    monkeypatch.setattr(agent_mod.CorpusAgent, "_build_embedder", lambda self, m: _StubEmbedder())
    monkeypatch.setattr(agent_mod.CorpusAgent, "_build_vector_store", lambda self: _StubVectorStore())


@pytest.mark.asyncio
async def test_ingest_corpus_filesystem_smoke(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_filesystem

    docs = configured_env / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")
    (docs / "b.md").write_text("beta", encoding="utf-8")

    result = await ingest_corpus_filesystem.execute(corpus_id="t1", root_path=str(docs))
    assert result["corpus_id"] == "t1"
    assert result["ingested"] == 2
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_corpus_retrieve_raises_for_unknown_corpus(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_retrieve

    # BaseTool.execute wraps domain exceptions in ToolError; the original
    # CorpusNotFoundError is available as ToolError.__cause__.
    with pytest.raises(ToolError) as exc_info:
        await corpus_retrieve.execute(corpus_id="never-ingested", question="anything", top_k=3)
    assert isinstance(exc_info.value.__cause__, CorpusNotFoundError)


@pytest.mark.asyncio
async def test_corpus_query_raises_for_unknown_corpus(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_query

    # BaseTool.execute wraps domain exceptions in ToolError; the original
    # CorpusNotFoundError is available as ToolError.__cause__.
    with pytest.raises(ToolError) as exc_info:
        await corpus_query.execute(corpus_id="never-ingested", question="anything", top_k=3)
    assert isinstance(exc_info.value.__cause__, CorpusNotFoundError)


@pytest.mark.asyncio
async def test_list_corpora_empty_when_root_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import list_corpora

    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "does-not-exist"))
    result = await list_corpora.execute()
    assert result["corpora"] == []
    assert result["corpus_root"].endswith("does-not-exist")


@pytest.mark.asyncio
async def test_list_corpora_returns_only_dirs_with_sqlite(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import (
        ingest_corpus_filesystem,
        list_corpora,
    )

    docs = configured_env / "src"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")

    await ingest_corpus_filesystem.execute(corpus_id="bravo", root_path=str(docs))
    await ingest_corpus_filesystem.execute(corpus_id="alpha", root_path=str(docs))

    # A stray directory with no corpus.sqlite must be ignored.
    (configured_env / "corpora" / "stray").mkdir(parents=True)

    result = await list_corpora.execute()
    ids = [c["corpus_id"] for c in result["corpora"]]
    assert ids == ["alpha", "bravo"]
    for entry in result["corpora"]:
        assert entry["size_bytes"] > 0
        assert "T" in entry["modified"]  # ISO 8601 marker
