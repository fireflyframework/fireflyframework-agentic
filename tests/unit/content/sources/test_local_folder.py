# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for LocalFolderSource."""

from __future__ import annotations

from pathlib import Path

import pytest

from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_lists_files_recursively(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "hello")
    _write(tmp_path / "sub" / "b.md", "world")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))

    raws = [r async for r in source.list_changed(None)]
    names = sorted(r.name for r in raws)
    assert names == ["a.md", "b.md"]


@pytest.mark.asyncio
async def test_skips_hidden_files_by_default(tmp_path: Path) -> None:
    _write(tmp_path / "visible.md", "x")
    _write(tmp_path / ".hidden.md", "x")
    _write(tmp_path / ".DS_Store", "")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))

    raws = [r async for r in source.list_changed(None)]
    assert [r.name for r in raws] == ["visible.md"]


@pytest.mark.asyncio
async def test_includes_hidden_when_requested(tmp_path: Path) -> None:
    _write(tmp_path / ".hidden.md", "x")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path, include_hidden=True))

    raws = [r async for r in source.list_changed(None)]
    assert [r.name for r in raws] == [".hidden.md"]


@pytest.mark.asyncio
async def test_etag_stable_when_file_unchanged(tmp_path: Path) -> None:
    f = _write(tmp_path / "a.md", "hello")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))

    first = [r async for r in source.list_changed(None)]
    second = [r async for r in source.list_changed(None)]
    assert first[0].etag == second[0].etag
    # mtime+size combination changes when content changes
    f.write_text("hello world", encoding="utf-8")
    third = [r async for r in source.list_changed(None)]
    assert third[0].etag != first[0].etag


@pytest.mark.asyncio
async def test_fetch_returns_path_unchanged(tmp_path: Path) -> None:
    f = _write(tmp_path / "a.md", "hello")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))

    raws = [r async for r in source.list_changed(None)]
    fetched = await source.fetch(raws[0])
    assert fetched == f.resolve()


@pytest.mark.asyncio
async def test_cursor_methods_are_noops(tmp_path: Path) -> None:
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))
    assert await source.current_cursor() is None
    assert await source.pending_cursor() is None
    await source.commit_delta("anything")  # must not raise


@pytest.mark.asyncio
async def test_source_id_is_kind_prefixed(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "x")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))
    raws = [r async for r in source.list_changed(None)]
    assert raws[0].source_id.startswith("local:")


@pytest.mark.asyncio
async def test_satisfies_content_source_protocol(tmp_path: Path) -> None:
    from fireflyframework_agentic.content.sources import ContentSource

    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))
    assert isinstance(source, ContentSource)
