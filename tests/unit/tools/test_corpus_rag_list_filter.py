# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tests for the ``list_corpora`` per-caller filter and backend registry.

``list_corpora`` consults a contextvar set by ``CorpusAuthMiddleware`` and
delegates enumeration to the configured :class:`CorpusBackendRegistry`.
Both behaviours are independent of the middleware and of any specific
backend, so we test them directly against the tool with a stub registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Ensure each test starts with a fresh registry resolution.

    ``corpus_rag`` caches the resolved registry for the lifetime of the
    process; without this, the first test in the module would pin the
    registry instance every later test inherits, defeating the
    monkeypatched ``CORPUS_ROOT`` and ``CORPUS_BACKEND_REGISTRY_FACTORY``
    overrides.
    """
    from fireflyframework_agentic.tools.builtins import corpus_rag as cr

    cr._REGISTRY = None
    yield
    cr._REGISTRY = None


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


# ---------- registry pivot --------------------------------------------------


class _StubRegistry:
    """Fake :class:`CorpusBackendRegistry` for the pivot tests.

    Returns a fixed list and a label that ``list_corpora`` will surface
    via ``corpus_root``, so we can assert both the enumeration delegate
    and the source label propagate through unchanged.
    """

    def __init__(self, entries: list[dict[str, Any]], source: str = "stub://corpora") -> None:
        self._entries = entries
        self.source = source

    def backend_for(self, corpus_id: str):  # pragma: no cover - unused in these tests
        raise NotImplementedError

    async def list_corpora(self) -> list[dict[str, Any]]:
        return list(self._entries)


@pytest.mark.asyncio
async def test_list_corpora_delegates_to_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from fireflyframework_agentic.tools.builtins import corpus_rag as cr

    entries = [
        {"corpus_id": "alpha", "size_bytes": 100, "modified": "2026-05-19T00:00:00+00:00"},
        {"corpus_id": "beta", "size_bytes": 200, "modified": "2026-05-19T01:00:00+00:00"},
    ]
    monkeypatch.setattr(cr, "_REGISTRY", _StubRegistry(entries, source="https://blob/corpora"))

    out = await cr.list_corpora.execute()

    assert out == {
        "corpus_root": "https://blob/corpora",
        "corpora": entries,
    }


@pytest.mark.asyncio
async def test_list_corpora_authorised_filter_applies_after_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contextvar filter is applied by ``list_corpora`` itself, not by
    the registry. Registries that ship full lists still see per-caller
    enforcement at the tool boundary.
    """
    from fireflyframework_agentic.tools.builtins import corpus_rag as cr

    entries = [
        {"corpus_id": "alpha", "size_bytes": 100, "modified": None},
        {"corpus_id": "beta", "size_bytes": 200, "modified": None},
        {"corpus_id": "gamma", "size_bytes": 300, "modified": None},
    ]
    monkeypatch.setattr(cr, "_REGISTRY", _StubRegistry(entries))

    token = cr.authorised_corpora_var.set(("beta",))
    try:
        out = await cr.list_corpora.execute()
    finally:
        cr.authorised_corpora_var.reset(token)

    assert {row["corpus_id"] for row in out["corpora"]} == {"beta"}


def test_resolve_registry_factory_bad_spec() -> None:
    from fireflyframework_agentic.rag.corpus_backend import resolve_registry_factory

    with pytest.raises(RuntimeError, match="pkg.mod:callable"):
        resolve_registry_factory("not-a-spec")


def test_resolve_registry_factory_missing_module() -> None:
    from fireflyframework_agentic.rag.corpus_backend import resolve_registry_factory

    with pytest.raises(RuntimeError, match="Cannot import"):
        resolve_registry_factory("definitely.not.a.real.module:build_registry")


def test_resolve_registry_factory_missing_attribute() -> None:
    from fireflyframework_agentic.rag.corpus_backend import resolve_registry_factory

    with pytest.raises(RuntimeError, match="without attribute"):
        # `os` is real; `not_a_factory` isn't an attribute of it.
        resolve_registry_factory("os:not_a_factory")


def test_resolve_registry_factory_returns_callable() -> None:
    from fireflyframework_agentic.rag.corpus_backend import resolve_registry_factory

    # `os.getcwd` is conveniently callable and importable; we don't
    # actually call it, just resolve.
    fn = resolve_registry_factory("os:getcwd")
    assert callable(fn)


def test_local_registry_source_uses_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fireflyframework_agentic.rag.corpus_backend import LocalCorpusBackendRegistry

    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path))
    reg = LocalCorpusBackendRegistry()
    assert reg.source == str(tmp_path)
    assert reg.root == tmp_path


@pytest.mark.asyncio
async def test_local_registry_list_corpora_matches_old_behaviour(tmp_path: Path) -> None:
    """Regression check: the framework-default registry produces the same
    shape ``list_corpora`` used to produce before the registry pivot.
    """
    from fireflyframework_agentic.rag.corpus_backend import LocalCorpusBackendRegistry

    for cid in ("corpus-a", "corpus-b"):
        (tmp_path / cid).mkdir()
        (tmp_path / cid / "corpus.sqlite").write_bytes(b"sqlite-stub")
    # Non-corpus entries are ignored.
    (tmp_path / "loose-file.txt").write_text("not a corpus")
    (tmp_path / "corpus-d").mkdir()  # no sqlite inside

    reg = LocalCorpusBackendRegistry(root=tmp_path)
    out = await reg.list_corpora()
    assert {row["corpus_id"] for row in out} == {"corpus-a", "corpus-b"}
    for row in out:
        assert set(row.keys()) == {"corpus_id", "size_bytes", "modified"}
        assert row["size_bytes"] == len(b"sqlite-stub")
        assert row["modified"].endswith("+00:00")
