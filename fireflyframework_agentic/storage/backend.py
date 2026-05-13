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

"""Abstract base class for storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from fireflyframework_agentic.storage._types import LockToken, StorageMetadata


class StorageBackend(ABC):
    """Owns the physical storage of a single SQLite file and exclusive
    write locking against it.

    Implementations are expected to be safe to use from a single asyncio
    event loop; they are NOT required to be thread-safe across loops.
    """

    @abstractmethod
    async def metadata(self) -> StorageMetadata:
        """Return current remote metadata (etag, size, exists)."""
        raise NotImplementedError

    @abstractmethod
    async def download(self, dest: Path) -> StorageMetadata:
        """Atomically replace ``dest`` with the current remote contents.
        Returns the metadata observed at the time of the read."""
        raise NotImplementedError

    @abstractmethod
    async def upload(
        self,
        src: Path,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> StorageMetadata:
        """Atomically publish ``src`` as the new contents.

        Conditional headers:
        - ``if_match``: only succeed when remote etag matches.
        - ``if_none_match='*'``: only succeed when remote does not exist
          (used on first write).

        Conditional failure raises ``StorageLeaseError``.
        Transport / 5xx errors raise ``StorageTransientError`` and are
        retried by the caller's RetryPolicy.
        """
        raise NotImplementedError

    @abstractmethod
    async def acquire_lock(self, *, timeout: float) -> LockToken:
        """Acquire the exclusive write lock, waiting up to ``timeout``."""
        raise NotImplementedError

    @abstractmethod
    async def release_lock(self, token: LockToken) -> None:
        """Release the lock previously acquired via ``acquire_lock``."""
        raise NotImplementedError

    async def renew_lock(self, token: LockToken) -> LockToken:
        """Optional. Default raises NotImplementedError. Used by
        backends with bounded leases (Azure) to extend before
        expiry."""
        raise NotImplementedError

    @property
    def local_path(self) -> Path | None:
        """Path to the on-disk file this backend stores its bytes in, if any.

        Returns ``None`` for remote backends (Azure Blob, S3, etc.) where
        the storage isn't a single local file. Returns the file path for
        local-filesystem backends. ``DatabaseStore`` reads this at
        construction time: when it's not ``None``, the store's local
        working copy is co-located with the backend file (same inode,
        no duplicate, no ``~/.cache/`` divergence). When it's ``None``,
        the store falls back to its independent cache directory — the
        right behaviour for backends where the working copy MUST be a
        local file separate from the remote source of truth.
        """
        return None
