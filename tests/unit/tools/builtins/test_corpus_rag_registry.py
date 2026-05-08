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
async def test_write_lock_concurrent_callers_share_one_lock() -> None:
    """Two concurrent first-time callers for the same corpus_id must
    receive the same Lock instance — guards against the check-then-set
    race in _write_lock_for."""
    locks: list[asyncio.Lock] = []

    async def grab() -> None:
        locks.append(corpus_rag._write_lock_for("RACE"))

    await asyncio.gather(*[grab() for _ in range(10)])
    assert len({id(lock) for lock in locks}) == 1


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


@pytest.mark.asyncio
async def test_shutdown_agents_continues_after_one_close_fails() -> None:
    """If one agent's close raises, the rest still close and registries clear."""
    a = await corpus_rag._agent_for("X")
    b = await corpus_rag._agent_for("Y")
    closed: list[str] = []

    async def x_close():
        raise RuntimeError("boom")

    async def y_close():
        closed.append("Y")

    a.close = x_close  # type: ignore[method-assign]
    b.close = y_close  # type: ignore[method-assign]

    await corpus_rag._shutdown_agents()
    assert closed == ["Y"]
    assert corpus_rag._AGENT_CACHE == {}
    assert corpus_rag._WRITE_LOCKS == {}


@pytest.mark.asyncio
async def test_create_mcp_app_accepts_lifespan() -> None:
    """create_mcp_app must accept a lifespan and pass it to FastMCP."""
    import contextlib

    from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
    from fireflyframework_agentic.tools.registry import ToolRegistry

    fired: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        fired.append("startup")
        try:
            yield
        finally:
            fired.append("shutdown")

    app = create_mcp_app(name="test", registry=ToolRegistry(), lifespan=lifespan)
    # FastMCP stores the user-supplied lifespan on `_lifespan`; `app.lifespan`
    # is a no-arg aggregate context manager that wraps it. Drive `_lifespan`
    # directly so the assertion confirms the callable was passed through.
    async with app._lifespan(app):
        assert fired == ["startup"]
    assert fired == ["startup", "shutdown"]


@pytest.mark.asyncio
async def test_ingest_corpus_filesystem_skips_tabular_files(tmp_path: Path, monkeypatch) -> None:
    """ingest_corpus_filesystem leaves CSV / XLS / XLSX to ingest_corpus_structured.

    Regression: without this, spreadsheets ended up double-represented (chunks
    via markitdown + SQL rows via the structured pipeline).
    """
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "deck.md").write_text("hello")
    (drop / "rows.csv").write_text("a,b\n1,2\n")
    (drop / "sheet.xlsx").write_bytes(b"PK\x03\x04")

    captured: dict[str, object] = {}

    class _StubSummary:
        results: list[object] = []
        ingested = skipped = failed = 0
        cursor: str | None = None

    class _StubAgent:
        async def ingest_source(self, source):
            captured["source"] = source
            return _StubSummary()

        async def close(self):
            pass

    monkeypatch.setitem(corpus_rag._AGENT_CACHE, "T", _StubAgent())

    await corpus_rag.ingest_corpus_filesystem.execute(corpus_id="T", root_path=str(drop))

    source = captured["source"]
    names = sorted([rf.name async for rf in source.list_changed(since=None)])
    # Only the markdown file should be visible to the unstructured ingest path.
    assert names == ["deck.md"]
