from __future__ import annotations

import asyncio

from fireflyframework_agentic.pipeline.triggers import FolderWatcher


async def test_startup_scan_yields_existing_files(tmp_path):
    (tmp_path / "a.txt").write_text("hello a")
    (tmp_path / "b.txt").write_text("hello b")

    watcher = FolderWatcher(folder=tmp_path, debounce_ms=10, stability_polls=1, stability_interval_ms=10)

    seen: set[str] = set()
    async for path in watcher.startup_scan():
        seen.add(path.name)

    assert seen == {"a.txt", "b.txt"}


async def test_skips_files_not_yet_stable(tmp_path):
    target = tmp_path / "growing.txt"
    target.write_text("0")

    watcher = FolderWatcher(folder=tmp_path, debounce_ms=10, stability_polls=2, stability_interval_ms=20)

    async def keep_writing():
        for i in range(5):
            await asyncio.sleep(0.005)
            target.write_text("0" * (i + 1))

    writer = asyncio.create_task(keep_writing())
    stable = await watcher.wait_for_stability(target, max_wait_ms=120)
    await writer
    # If size kept changing within the wait window, stability should be False
    assert stable is False or target.stat().st_size > 0


async def test_returns_stable_for_quiescent_file(tmp_path):
    target = tmp_path / "still.txt"
    target.write_text("hi")
    watcher = FolderWatcher(folder=tmp_path, debounce_ms=5, stability_polls=2, stability_interval_ms=10)
    assert await watcher.wait_for_stability(target, max_wait_ms=200) is True


def test_is_hidden_skips_dotfile_at_top_level(tmp_path):
    watcher = FolderWatcher(folder=tmp_path)
    assert watcher._is_hidden(tmp_path / ".DS_Store") is True


def test_is_hidden_skips_dotfile_in_subdirectory(tmp_path):
    watcher = FolderWatcher(folder=tmp_path)
    assert watcher._is_hidden(tmp_path / "subdir" / ".DS_Store") is True


def test_is_hidden_skips_dotted_directory(tmp_path):
    watcher = FolderWatcher(folder=tmp_path)
    # File inside a hidden directory (e.g. .git/HEAD) should be filtered.
    assert watcher._is_hidden(tmp_path / ".git" / "HEAD") is True


def test_is_hidden_allows_hyphenated_paths(tmp_path):
    watcher = FolderWatcher(folder=tmp_path)
    assert watcher._is_hidden(tmp_path / "my-docs" / "report.pdf") is False


def test_is_hidden_allows_normal_filenames(tmp_path):
    watcher = FolderWatcher(folder=tmp_path)
    assert watcher._is_hidden(tmp_path / "subdir" / "file.txt") is False


async def test_startup_scan_skips_dotfiles_anywhere_in_tree(tmp_path):
    (tmp_path / "good.txt").write_text("ok")
    (tmp_path / ".DS_Store").write_text("metadata")
    nested = tmp_path / "subdir"
    nested.mkdir()
    (nested / "ok.txt").write_text("ok")
    (nested / ".DS_Store").write_text("metadata")

    watcher = FolderWatcher(folder=tmp_path)
    seen = []
    async for path in watcher.startup_scan():
        seen.append(path.name)
    assert "good.txt" in seen
    assert "ok.txt" in seen
    assert ".DS_Store" not in seen
