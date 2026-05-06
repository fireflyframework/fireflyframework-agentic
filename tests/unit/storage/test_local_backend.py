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

import asyncio
import os
from pathlib import Path

import pytest

from fireflyframework_agentic.storage import (
    LocalBackend,
    StorageLeaseError,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "db.sqlite"


async def test_metadata_reports_missing(db_path: Path) -> None:
    backend = LocalBackend(db_path)
    meta = await backend.metadata()
    assert meta.exists is False
    assert meta.etag is None


async def test_upload_creates_file_and_returns_etag(db_path: Path, tmp_path: Path) -> None:
    src = tmp_path / "src.sqlite"
    src.write_bytes(b"hello")
    backend = LocalBackend(db_path)
    meta = await backend.upload(src)
    assert meta.exists is True
    assert meta.etag is not None
    assert db_path.read_bytes() == b"hello"


async def test_upload_etag_changes_when_content_changes(db_path: Path, tmp_path: Path) -> None:
    src = tmp_path / "src.sqlite"
    src.write_bytes(b"v1")
    backend = LocalBackend(db_path)
    m1 = await backend.upload(src)
    src.write_bytes(b"v2-longer")
    m2 = await backend.upload(src)
    assert m1.etag != m2.etag


async def test_download_copies_remote_to_dest(db_path: Path, tmp_path: Path) -> None:
    src = tmp_path / "src.sqlite"
    src.write_bytes(b"payload")
    backend = LocalBackend(db_path)
    await backend.upload(src)

    dest = tmp_path / "downloaded.sqlite"
    meta = await backend.download(dest)
    assert dest.read_bytes() == b"payload"
    assert meta.etag is not None


async def test_acquire_release_lock_roundtrip(db_path: Path) -> None:
    backend = LocalBackend(db_path)
    token = await backend.acquire_lock(timeout=1.0)
    sentinel = db_path.with_suffix(db_path.suffix + ".lock")
    assert sentinel.exists()
    await backend.release_lock(token)
    assert not sentinel.exists()


async def test_concurrent_acquire_serialises(db_path: Path) -> None:
    backend = LocalBackend(db_path)
    order: list[str] = []

    async def hold(label: str, hold_for: float) -> None:
        token = await backend.acquire_lock(timeout=5.0)
        order.append(f"+{label}")
        await asyncio.sleep(hold_for)
        order.append(f"-{label}")
        await backend.release_lock(token)

    await asyncio.gather(hold("A", 0.05), hold("B", 0.0))
    # Both critical sections must be non-overlapping.
    assert order in (["+A", "-A", "+B", "-B"], ["+B", "-B", "+A", "-A"])


async def test_acquire_timeout_raises(db_path: Path) -> None:
    backend = LocalBackend(db_path)
    held = await backend.acquire_lock(timeout=0.5)
    try:
        # Same backend instance: the second acquire would block on the
        # in-process asyncio.Lock. Use a *separate* instance to simulate
        # cross-process — that path checks the on-disk sentinel.
        other = LocalBackend(db_path)
        with pytest.raises(StorageLeaseError):
            await other.acquire_lock(timeout=0.2)
    finally:
        await backend.release_lock(held)


async def test_upload_if_match_mismatch_raises(db_path: Path, tmp_path: Path) -> None:
    src = tmp_path / "src.sqlite"
    src.write_bytes(b"v1")
    backend = LocalBackend(db_path)
    await backend.upload(src)
    src.write_bytes(b"v2")
    with pytest.raises(StorageLeaseError):
        await backend.upload(src, if_match="not-the-real-etag")


async def test_upload_if_none_match_star_blocks_overwrite(db_path: Path, tmp_path: Path) -> None:
    src = tmp_path / "src.sqlite"
    src.write_bytes(b"v1")
    backend = LocalBackend(db_path)
    await backend.upload(src)  # creates file
    with pytest.raises(StorageLeaseError):
        await backend.upload(src, if_none_match="*")


async def test_stale_sentinel_reclaim(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel = db_path.with_suffix(db_path.suffix + ".lock")
    # Write a sentinel from a non-existent pid + ancient mtime
    sentinel.write_text("999999999:fake-nonce")
    very_old = 0.0
    os.utime(sentinel, (very_old, very_old))
    backend = LocalBackend(db_path, stale_lock_seconds=1)
    token = await backend.acquire_lock(timeout=2.0)
    await backend.release_lock(token)
