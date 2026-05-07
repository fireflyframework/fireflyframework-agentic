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

"""In-memory StorageBackend fake for unit tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fireflyframework_agentic.storage._types import (
    LockToken,
    StorageLeaseError,
    StorageMetadata,
)
from fireflyframework_agentic.storage.backend import StorageBackend


class InMemoryBackend(StorageBackend):
    """Holds bytes in memory; supports etag, conditional ops, and a
    programmable failure queue for retry tests."""

    def __init__(self) -> None:
        self._data: bytes | None = None
        self._etag: str | None = None
        self._modified: datetime | None = None
        self._lock = asyncio.Lock()
        self._token: str | None = None
        # Programmable failures: each entry is consumed by the next
        # upload() call. Use ``StorageTransientError`` for retryable.
        self.upload_failures: list[Exception] = []
        # Counters for assertions
        self.uploads = 0
        self.downloads = 0
        self.metadata_calls = 0

    async def metadata(self) -> StorageMetadata:
        self.metadata_calls += 1
        return StorageMetadata(
            etag=self._etag,
            size_bytes=len(self._data) if self._data is not None else None,
            modified=self._modified,
            exists=self._data is not None,
        )

    async def download(self, dest: Path) -> StorageMetadata:
        if self._data is None:
            raise FileNotFoundError("blob does not exist")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._data)
        self.downloads += 1
        return await self.metadata()

    async def upload(
        self,
        src: Path,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> StorageMetadata:
        if self.upload_failures:
            raise self.upload_failures.pop(0)
        if if_none_match == "*" and self._data is not None:
            raise StorageLeaseError("if_none_match=*: blob exists")
        if if_match is not None and if_match != self._etag:
            raise StorageLeaseError("if_match mismatch", expected=if_match, actual=self._etag)
        self._data = src.read_bytes()
        self._etag = uuid.uuid4().hex
        self._modified = datetime.now(UTC)
        self.uploads += 1
        return await self.metadata()

    async def acquire_lock(self, *, timeout: float) -> LockToken:
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=timeout)
        except TimeoutError as exc:
            raise StorageLeaseError("lock timeout") from exc
        self._token = uuid.uuid4().hex
        return LockToken(
            token=self._token,
            acquired_at=datetime.now(UTC),
            expires_at=None,
        )

    async def release_lock(self, token: LockToken) -> None:
        if self._token == token.token:
            self._token = None
        if self._lock.locked():
            self._lock.release()
