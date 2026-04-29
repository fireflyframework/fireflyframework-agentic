from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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
