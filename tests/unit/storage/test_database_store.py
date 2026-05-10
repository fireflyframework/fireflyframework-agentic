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

import json
import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.storage import (
    DatabaseStore,
    RetryPolicy,
    StorageLeaseError,
    StorageTransientError,
    StorageUploadError,
)
from tests.unit.storage._fakes import InMemoryBackend


@pytest.fixture
def store_factory(tmp_path: Path):
    def _make(*, retry_policy: RetryPolicy | None = None) -> tuple[DatabaseStore, InMemoryBackend]:
        backend = InMemoryBackend()
        store = DatabaseStore(
            backend,
            store_id="t",
            cache_root=tmp_path,
            retry_policy=retry_policy,
        )
        return store, backend

    return _make


def _write_sample(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (v BLOB)")
    conn.execute("INSERT INTO t VALUES (?)", (payload,))
    conn.commit()
    conn.close()


async def test_for_write_first_run_uploads(store_factory) -> None:
    store, backend = store_factory()
    async with store.for_write() as session:
        _write_sample(session.path, b"hello")
    assert backend.uploads == 1
    assert backend.downloads == 0


async def test_for_write_skips_download_when_etag_matches(store_factory) -> None:
    store, backend = store_factory()
    async with store.for_write() as session:
        _write_sample(session.path, b"v1")
    # Second batch from same store: cached etag matches remote.
    async with store.for_write() as session:
        _write_sample(session.path, b"v2")
    assert backend.downloads == 0
    assert backend.uploads == 2


async def test_for_write_downloads_when_remote_changed(tmp_path: Path) -> None:
    backend = InMemoryBackend()
    store_a = DatabaseStore(backend, store_id="a", cache_root=tmp_path / "a")
    store_b = DatabaseStore(backend, store_id="b", cache_root=tmp_path / "b")
    async with store_a.for_write() as session:
        _write_sample(session.path, b"x")
    # store_b has never seen the blob — must download.
    async with store_b.for_write() as session:
        _write_sample(session.path, b"y")
    assert backend.downloads == 1


async def test_for_write_exception_does_not_upload(store_factory) -> None:
    store, backend = store_factory()
    raised = False
    try:
        async with store.for_write() as _session:
            raise RuntimeError("boom")
    except RuntimeError:
        raised = True
    assert raised, "for_write must propagate RuntimeError from the body"
    assert backend.uploads == 0


async def test_terminal_upload_failure_repulls_and_raises(store_factory) -> None:
    store, backend = store_factory(retry_policy=RetryPolicy(max_attempts=2, initial_backoff_s=0.0))
    # First batch succeeds — establishes a remote blob.
    async with store.for_write() as session:
        _write_sample(session.path, b"ok")
    # Next batch's uploads all fail terminally.
    backend.upload_failures = [
        StorageTransientError("503"),
        StorageTransientError("503"),
    ]
    with pytest.raises(StorageUploadError):
        async with store.for_write() as session:
            _write_sample(session.path, b"will-be-discarded")
    # Cache was re-pulled to remote state.
    assert backend.downloads == 1


async def test_ensure_fresh_returns_path_and_generation(store_factory, tmp_path: Path) -> None:
    store, backend = store_factory()
    async with store.for_write() as session:
        _write_sample(session.path, b"hello")
    path1, gen1 = await store.ensure_fresh()
    path2, gen2 = await store.ensure_fresh()
    assert path1 == path2
    assert gen1 == gen2  # within freshness window, no HEAD


async def test_ensure_fresh_bumps_generation_when_remote_moves(tmp_path: Path) -> None:
    backend = InMemoryBackend()
    writer = DatabaseStore(backend, store_id="w", cache_root=tmp_path / "w", read_freshness_seconds=0.0)
    reader = DatabaseStore(backend, store_id="r", cache_root=tmp_path / "r", read_freshness_seconds=0.0)
    async with writer.for_write() as session:
        _write_sample(session.path, b"v1")
    _, g1 = await reader.ensure_fresh()
    async with writer.for_write() as session:
        _write_sample(session.path, b"v2")
    _, g2 = await reader.ensure_fresh()
    assert g2 > g1


async def test_dirty_recovery_redownloads_on_next_for_write(store_factory, tmp_path: Path) -> None:
    store, backend = store_factory()
    async with store.for_write() as session:
        _write_sample(session.path, b"ok")
    # Simulate a crash: leave dirty=True in the sidecar.
    sidecar = tmp_path / "t" / "metadata.json"
    data = json.loads(sidecar.read_text())
    data["dirty"] = True
    sidecar.write_text(json.dumps(data))
    # Local cache also locally-mutated to ensure download overwrites it.
    cache_path = tmp_path / "t" / "db.sqlite"
    cache_path.write_bytes(b"local-only-garbage")
    async with store.for_write() as session:
        # Inside the with block, the file should be the remote contents,
        # not the garbage we wrote.
        assert session.path.read_bytes() != b"local-only-garbage"
        _write_sample(session.path, b"ok2")
    assert backend.downloads == 1


async def test_retry_policy_eventual_success(store_factory) -> None:
    store, backend = store_factory(retry_policy=RetryPolicy(max_attempts=3, initial_backoff_s=0.0))
    backend.upload_failures = [StorageTransientError("503"), StorageTransientError("503")]
    async with store.for_write() as session:
        _write_sample(session.path, b"v")
    assert backend.uploads == 1


async def test_close_is_idempotent(store_factory) -> None:
    store, _ = store_factory()
    await store.close()
    await store.close()


async def test_for_write_surfaces_lease_renew_failure(tmp_path: Path) -> None:
    """When a backend records a lease-renew failure, the next operation
    must surface it as StorageLeaseError, not silently proceed."""
    backend = InMemoryBackend()
    # Simulate the error that AzureBlobBackend._renew_loop would surface:
    # inject a StorageLeaseError into the upload-failures queue so the
    # backend raises it on the upload step of for_write().
    # StorageLeaseError is not in RetryPolicy.retry_on, so it
    # short-circuits the retry loop and surfaces as StorageUploadError.
    backend.upload_failures = [StorageLeaseError("lease renewal failed mid-operation")]
    store = DatabaseStore(
        backend,
        store_id="lf",
        cache_root=tmp_path,
        retry_policy=RetryPolicy(max_attempts=1, initial_backoff_s=0.0),
    )
    with pytest.raises(StorageUploadError) as exc_info:
        async with store.for_write() as session:
            session.path.touch()
    # The terminal upload failure wraps the original lease error
    assert isinstance(exc_info.value.__cause__, StorageLeaseError)
