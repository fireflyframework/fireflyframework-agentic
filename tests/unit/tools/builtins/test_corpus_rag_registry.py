# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tests for the process-wide CorpusAgent registry in corpus_rag.

The registry lets every MCP tool call against a given corpus_id share one
CorpusAgent (and thus one DatabaseStore / LocalBackend / SqliteCorpus
instance) so the asyncio.Lock inside the backend actually serialises
concurrent writers in the same process.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fireflyframework_agentic.tools.builtins import corpus_rag


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Reset module-level cache and point CORPUS_ROOT at tmp_path."""
    corpus_rag._AGENT_CACHE.clear()
    corpus_rag._WRITE_LOCKS.clear()
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "openai:text-embedding-3-small")
    monkeypatch.setenv("EXPANSION_MODEL", "anthropic:claude-haiku-3-5")
    monkeypatch.setenv("ANSWER_MODEL", "anthropic:claude-haiku-3-5")
    monkeypatch.setenv("RERANK_MODEL", "anthropic:claude-haiku-3-5")
    yield
    corpus_rag._AGENT_CACHE.clear()
    corpus_rag._WRITE_LOCKS.clear()


@pytest.mark.asyncio
async def test_agent_for_returns_cached_instance() -> None:
    a = await corpus_rag._agent_for("X")
    b = await corpus_rag._agent_for("X")
    assert a is b


@pytest.mark.asyncio
async def test_agent_for_different_corpus_ids_are_distinct() -> None:
    a = await corpus_rag._agent_for("X")
    b = await corpus_rag._agent_for("Y")
    assert a is not b


@pytest.mark.asyncio
async def test_write_lock_is_per_corpus() -> None:
    la = corpus_rag._write_lock_for("X")
    lb = corpus_rag._write_lock_for("Y")
    assert la is not lb
    assert corpus_rag._write_lock_for("X") is la


@pytest.mark.asyncio
async def test_write_lock_serialises_concurrent_writers() -> None:
    """Two coroutines holding _write_lock_for('Z') run sequentially, not concurrently."""
    timeline: list[str] = []

    async def writer(label: str) -> None:
        async with corpus_rag._write_lock_for("Z"):
            timeline.append(f"{label}-enter")
            await asyncio.sleep(0.05)
            timeline.append(f"{label}-exit")

    await asyncio.gather(writer("a"), writer("b"))
    # No interleaving: each writer's exit precedes the next writer's enter.
    assert timeline in (
        ["a-enter", "a-exit", "b-enter", "b-exit"],
        ["b-enter", "b-exit", "a-enter", "a-exit"],
    )


@pytest.mark.asyncio
async def test_shutdown_agents_closes_and_clears() -> None:
    a = await corpus_rag._agent_for("X")
    closed: list[bool] = []
    original_close = a.close

    async def tracking_close() -> None:
        closed.append(True)
        await original_close()

    a.close = tracking_close  # type: ignore[method-assign]
    await corpus_rag._shutdown_agents()
    assert closed == [True]
    assert corpus_rag._AGENT_CACHE == {}
    assert corpus_rag._WRITE_LOCKS == {}
