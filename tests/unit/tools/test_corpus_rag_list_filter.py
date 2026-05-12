# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tests for the ``list_corpora`` per-caller filter.

``list_corpora`` consults a contextvar set by ``CorpusAuthMiddleware``. The
filter behaviour is independent of the middleware, so we test it directly
against the tool.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def populated_corpus_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create three corpora on disk under CORPUS_ROOT."""
    for cid in ("corpus-a", "corpus-b", "corpus-c"):
        (tmp_path / cid).mkdir()
        (tmp_path / cid / "corpus.sqlite").write_bytes(b"sqlite-stub")
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path))
    return tmp_path


async def _run(coro):
    """Helper: invoke the underlying coroutine of a firefly_tool-decorated function."""
    return await coro


@pytest.mark.asyncio
async def test_list_corpora_unfiltered_when_contextvar_unset(populated_corpus_root: Path) -> None:
    from fireflyframework_agentic.tools.builtins import corpus_rag as cr

    # Ensure the contextvar is unset for this run.
    assert cr.authorised_corpora_var.get() is None

    out = await cr.list_corpora.execute()
    ids = {row["corpus_id"] for row in out["corpora"]}
    assert ids == {"corpus-a", "corpus-b", "corpus-c"}


@pytest.mark.asyncio
async def test_list_corpora_filtered_when_contextvar_set(populated_corpus_root: Path) -> None:
    from fireflyframework_agentic.tools.builtins import corpus_rag as cr

    token = cr.authorised_corpora_var.set(("corpus-b",))
    try:
        out = await cr.list_corpora.execute()
    finally:
        cr.authorised_corpora_var.reset(token)

    ids = {row["corpus_id"] for row in out["corpora"]}
    assert ids == {"corpus-b"}


@pytest.mark.asyncio
async def test_list_corpora_filter_to_unknown_corpus_returns_empty(
    populated_corpus_root: Path,
) -> None:
    from fireflyframework_agentic.tools.builtins import corpus_rag as cr

    token = cr.authorised_corpora_var.set(("does-not-exist",))
    try:
        out = await cr.list_corpora.execute()
    finally:
        cr.authorised_corpora_var.reset(token)

    assert out["corpora"] == []
