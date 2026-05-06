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

"""LocalBackend: sqlite file on the local filesystem."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fireflyframework_agentic.storage._types import (
    LockToken,
    StorageDownloadError,
    StorageLeaseError,
    StorageMetadata,
)
from fireflyframework_agentic.storage.backend import StorageBackend

log = logging.getLogger(__name__)


def _stat_etag(path: Path) -> str:
    st = path.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


class LocalBackend(StorageBackend):
    def __init__(self, path: Path | str, *, stale_lock_seconds: float = 600.0) -> None:
        self._path = Path(path)
        self._stale_lock_seconds = stale_lock_seconds
        self._sentinel = self._path.with_suffix(self._path.suffix + ".lock")
        self._asyncio_lock = asyncio.Lock()

    async def metadata(self) -> StorageMetadata:
        return await asyncio.to_thread(self._metadata_sync)

    def _metadata_sync(self) -> StorageMetadata:
        if not self._path.exists():
            return StorageMetadata(etag=None, size_bytes=None, modified=None, exists=False)
        st = self._path.stat()
        return StorageMetadata(
            etag=_stat_etag(self._path),
            size_bytes=st.st_size,
            modified=datetime.fromtimestamp(st.st_mtime, tz=UTC),
            exists=True,
        )

    async def download(self, dest: Path) -> StorageMetadata:
        return await asyncio.to_thread(self._download_sync, dest)

    def _download_sync(self, dest: Path) -> StorageMetadata:
        if not self._path.exists():
            raise StorageDownloadError("source does not exist", path=str(self._path))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() == self._path.resolve():
            return self._metadata_sync()
        tmp = dest.with_suffix(dest.suffix + f".dl.{uuid.uuid4().hex}")
        shutil.copyfile(self._path, tmp)
        os.replace(tmp, dest)
        return self._metadata_sync()

    async def upload(
        self,
        src: Path,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> StorageMetadata:
        return await asyncio.to_thread(self._upload_sync, src, if_match, if_none_match)

    def _upload_sync(
        self,
        src: Path,
        if_match: str | None,
        if_none_match: str | None,
    ) -> StorageMetadata:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Conditional checks are evaluated under the on-disk sentinel
        # which the caller is expected to hold via acquire_lock.
        if if_none_match == "*" and self._path.exists():
            raise StorageLeaseError(
                "if_none_match=* but file exists",
                etag=_stat_etag(self._path),
            )
        if if_match is not None and self._path.exists():
            current = _stat_etag(self._path)
            if current != if_match:
                raise StorageLeaseError(
                    "if_match mismatch",
                    expected=if_match,
                    actual=current,
                )
        if src.resolve() != self._path.resolve():
            tmp = self._path.with_suffix(self._path.suffix + f".up.{uuid.uuid4().hex}")
            shutil.copyfile(src, tmp)
            os.replace(tmp, self._path)
        # Re-stat after replace.
        return self._metadata_sync()

    async def acquire_lock(self, *, timeout: float) -> LockToken:
        deadline = time.monotonic() + timeout
        # In-process serialisation first.
        try:
            await asyncio.wait_for(self._asyncio_lock.acquire(), timeout=timeout)
        except TimeoutError as exc:
            raise StorageLeaseError("in-process lock timeout", path=str(self._path)) from exc
        try:
            while True:
                self._reclaim_stale_sentinel_if_any()
                token_str = f"{os.getpid()}:{uuid.uuid4().hex}"
                try:
                    fd = os.open(
                        self._sentinel,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o644,
                    )
                except FileExistsError as exc:
                    if time.monotonic() >= deadline:
                        raise StorageLeaseError(
                            "sentinel held by another process",
                            sentinel=str(self._sentinel),
                        ) from exc
                    await asyncio.sleep(0.05)
                    continue
                with os.fdopen(fd, "w") as f:
                    f.write(token_str)
                return LockToken(
                    token=token_str,
                    acquired_at=datetime.now(UTC),
                    expires_at=None,
                )
        except BaseException:
            self._asyncio_lock.release()
            raise

    def _reclaim_stale_sentinel_if_any(self) -> None:
        if not self._sentinel.exists():
            return
        try:
            age = time.time() - self._sentinel.stat().st_mtime
        except FileNotFoundError:
            return
        try:
            text = self._sentinel.read_text().strip()
            pid_str, _ = text.split(":", 1)
            pid = int(pid_str)
        except (OSError, ValueError):
            pid = -1
        if pid > 0:
            try:
                os.kill(pid, 0)  # liveness check
                process_alive = True
            except OSError:
                process_alive = False
        else:
            process_alive = False
        if not process_alive or age > self._stale_lock_seconds:
            log.warning(
                "reclaiming stale sentinel %s (pid=%s alive=%s age=%.1fs)",
                self._sentinel,
                pid,
                process_alive,
                age,
            )
            with contextlib.suppress(FileNotFoundError):
                self._sentinel.unlink()

    async def release_lock(self, token: LockToken) -> None:
        try:
            await asyncio.to_thread(self._release_sync, token)
        finally:
            if self._asyncio_lock.locked():
                self._asyncio_lock.release()

    def _release_sync(self, token: LockToken) -> None:
        if not self._sentinel.exists():
            return
        # Tolerate a stale-reclaimed sentinel: only delete if the token
        # in the file matches ours.
        try:
            current = self._sentinel.read_text().strip()
        except OSError:
            return
        if current == token.token:
            with contextlib.suppress(FileNotFoundError):
                self._sentinel.unlink()
