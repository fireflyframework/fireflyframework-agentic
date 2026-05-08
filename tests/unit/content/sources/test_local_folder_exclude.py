from pathlib import Path

import pytest

from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)


@pytest.mark.asyncio
async def test_exclude_predicate_skips_matching_files(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("keep")
    (tmp_path / "skip.csv").write_text("a,b\n1,2\n")
    (tmp_path / "also_skip.xlsx").write_bytes(b"PK\x03\x04")

    source = LocalFolderSource(
        LocalFolderSourceConfig(
            folder=tmp_path,
            exclude_predicate=lambda p: p.suffix.lower() in {".csv", ".xlsx"},
        )
    )

    names = sorted([rf.name async for rf in source.list_changed(since=None)])
    assert names == ["keep.md"]


@pytest.mark.asyncio
async def test_exclude_predicate_default_none_keeps_everything(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "b.csv").write_text("a,b\n1,2\n")

    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))
    names = sorted([rf.name async for rf in source.list_changed(since=None)])
    assert names == ["a.md", "b.csv"]


def test_exclude_predicate_rejects_async_callable(tmp_path: Path) -> None:
    async def async_pred(p: Path) -> bool:
        return False

    with pytest.raises(ValueError, match="async"):
        LocalFolderSourceConfig(folder=tmp_path, exclude_predicate=async_pred)
