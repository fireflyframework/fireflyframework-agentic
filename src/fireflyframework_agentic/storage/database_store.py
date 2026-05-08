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

"""DatabaseStore: orchestrates a managed SQLite file over a StorageBackend."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fireflyframework_agentic.storage._types import (
    RetryPolicy,
    StorageUploadError,
    WriteSession,
)
from fireflyframework_agentic.storage.backend import StorageBackend

log = logging.getLogger(__name__)

_DEFAULT_CACHE_ROOT_ENV = "FIREFLY_DBSTORE_CACHE_ROOT"
_DEFAULT_CACHE_ROOT = Path("~/.cache/fireflyframework_agentic/dbstore").expanduser()


def _resolve_cache_root(cache_root: Path | None) -> Path:
    if cache_root is not None:
        return Path(cache_root)
    env = os.environ.get(_DEFAULT_CACHE_ROOT_ENV)
    if env:
        return Path(env).expanduser()
    return _DEFAULT_CACHE_ROOT


class _Sidecar:
    """Persistent {etag, dirty} on disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.etag: str | None = None
        self.dirty: bool = False

    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("sidecar unreadable, resetting: %s", exc)
            return
        self.etag = data.get("etag")
        self.dirty = bool(data.get("dirty", False))

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps({"etag": self.etag, "dirty": self.dirty}))
        os.replace(tmp, self._path)


class DatabaseStore:
    def __init__(
        self,
        backend: StorageBackend,
        *,
        store_id: str,
        cache_root: Path | None = None,
        retry_policy: RetryPolicy | None = None,
        read_freshness_seconds: float = 5.0,
    ) -> None:
        self._backend = backend
        self._store_id = store_id
        self._cache_dir = _resolve_cache_root(cache_root) / store_id
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path = self._cache_dir / "db.sqlite"
        self._sidecar = _Sidecar(self._cache_dir / "metadata.json")
        self._sidecar.load()
        self._retry_policy = retry_policy or RetryPolicy()
        self._read_freshness_seconds = read_freshness_seconds
        self._inproc_lock = asyncio.Lock()
        self._generation = 0
        self._last_freshness_check: float = 0.0

    @property
    def store_id(self) -> str:
        return self._store_id

    @property
    def cache_path(self) -> Path:
        return self._cache_path

    async def ensure_fresh(self) -> tuple[Path, int]:
        async with self._inproc_lock:
            now = time.monotonic()
            if now - self._last_freshness_check <= self._read_freshness_seconds and self._cache_path.exists():
                return self._cache_path, self._generation
            meta = await self._backend.metadata()
            if meta.exists and meta.etag != self._sidecar.etag:
                await self._backend.download(self._cache_path)
                self._sidecar.etag = meta.etag
                self._sidecar.save()
                self._generation += 1
            self._last_freshness_check = now
            return self._cache_path, self._generation

    @contextlib.asynccontextmanager
    async def for_write(self, *, lock_timeout: float = 30.0) -> AsyncIterator[WriteSession]:
        token = await self._backend.acquire_lock(timeout=lock_timeout)
        try:
            # Reload sidecar from disk so crash-recovery dirty flag is
            # picked up even when the same DatabaseStore instance is reused.
            self._sidecar.load()
            meta = await self._backend.metadata()
            first_write = not meta.exists

            if not first_write and meta.etag != self._sidecar.etag:
                # Remote has changed since we last synced — download it.
                await self._backend.download(self._cache_path)
                self._sidecar.etag = meta.etag
                self._sidecar.save()
                self._generation += 1
            elif self._sidecar.dirty:
                # Crash recovery: a previous run committed locally but
                # never confirmed upload. Discard local and re-pull.
                if meta.exists:
                    await self._backend.download(self._cache_path)
                    self._sidecar.etag = meta.etag
                self._sidecar.dirty = False
                self._sidecar.save()
                self._generation += 1
            elif first_write:
                # Touch an empty file so the caller can open a sqlite3
                # connection against it.
                self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                if not self._cache_path.exists():
                    self._cache_path.touch()
                self._generation += 1

            yielded_exception: BaseException | None = None
            try:
                yield WriteSession(path=self._cache_path, generation=self._generation)
            except BaseException as exc:
                yielded_exception = exc
                raise
            finally:
                if yielded_exception is None:
                    # Force any uncommitted WAL frames into the main SQLite
                    # file BEFORE the backend uploads it. The backend copies
                    # the main file only — without this, writes left in -wal
                    # by long-lived sqlite3 connections (e.g. SqliteCorpus)
                    # would silently disappear from the uploaded artifact.
                    await asyncio.to_thread(_checkpoint_wal, self._cache_path)
                    await self._upload_with_retry(first_write=first_write)
        finally:
            with contextlib.suppress(Exception):
                await self._backend.release_lock(token)

    async def _upload_with_retry(self, *, first_write: bool) -> None:
        self._sidecar.dirty = True
        self._sidecar.save()
        policy = self._retry_policy
        last_exc: BaseException | None = None
        for attempt in range(1, policy.max_attempts + 1):
            try:
                meta = await self._backend.upload(
                    self._cache_path,
                    if_match=self._sidecar.etag if not first_write else None,
                    if_none_match="*" if first_write else None,
                )
            except policy.retry_on as exc:
                last_exc = exc
                if attempt == policy.max_attempts:
                    break
                await asyncio.sleep(_compute_backoff(policy, attempt))
                continue
            except BaseException as exc:
                last_exc = exc
                break
            self._sidecar.etag = meta.etag
            self._sidecar.dirty = False
            self._sidecar.save()
            return
        # Terminal failure: discard local and re-pull.
        await self._discard_local_after_failure()
        log.error(
            "DatabaseStore upload failed terminally store_id=%s attempts=%d: %s",
            self._store_id,
            policy.max_attempts,
            last_exc,
        )
        raise StorageUploadError(
            f"upload failed after {policy.max_attempts} attempts",
            store_id=self._store_id,
            attempts=policy.max_attempts,
            inner=repr(last_exc),
        ) from last_exc

    async def _discard_local_after_failure(self) -> None:
        try:
            meta = await self._backend.metadata()
            if meta.exists:
                await self._backend.download(self._cache_path)
                self._sidecar.etag = meta.etag
            self._sidecar.dirty = False
            self._generation += 1
            self._sidecar.save()
        except Exception as exc:
            # Don't shadow the original upload error.
            log.error("post-failure re-pull also failed: %s", exc)

    async def close(self) -> None:
        # Reserved for future symmetry. No-op today.
        return None


def _checkpoint_wal(path: Path) -> None:
    """Truncate any pending WAL frames into *path*.

    Called by ``for_write`` before handing the file to the storage backend
    for upload. ``shutil.copyfile`` (the backend's typical upload path)
    only reads the main DB file; without this, any frames still in
    ``<path>-wal`` from a long-lived writer connection would be silently
    dropped from the uploaded artifact.

    Failures are logged but not raised — checkpointing is best-effort and
    must not abort the upload.
    """
    if not path.exists():
        return
    try:
        conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logging.getLogger(__name__).warning("WAL checkpoint failed for %s before upload: %s", path, exc)


def _compute_backoff(policy: RetryPolicy, attempt: int) -> float:
    base = policy.initial_backoff_s * (2 ** (attempt - 1))
    capped = min(base, policy.max_backoff_s)
    if policy.jitter:
        capped *= 0.5 + random.random()
    return capped


__all__ = ["DatabaseStore"]
