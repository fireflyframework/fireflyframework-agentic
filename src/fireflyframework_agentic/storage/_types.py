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

"""Shared types for the storage layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from fireflyframework_agentic.exceptions import FireflyAgenticError


class StorageMetadata(NamedTuple):
    etag: str | None
    size_bytes: int | None
    modified: datetime | None
    exists: bool


class LockToken(NamedTuple):
    token: str
    acquired_at: datetime
    expires_at: datetime | None  # None = no auto-expiry (Local)


@dataclass(frozen=True)
class WriteSession:
    """Yielded by ``DatabaseStore.for_write``. ``path`` is the local cache
    file (lock held); ``generation`` increments each time the cache is
    replaced, so callers holding a long-lived sqlite3 connection can
    detect when to reopen."""

    path: Path
    generation: int


# --- Errors -----------------------------------------------------------


class DatabaseStoreError(FireflyAgenticError):
    """Base class for all storage-layer errors."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.context = context


class StorageTransientError(DatabaseStoreError):
    """Retryable transport / 5xx / throttling error. Internal — should
    not surface to application code (the retry helper either succeeds or
    raises a terminal subclass)."""


class StorageUploadError(DatabaseStoreError):
    """Terminal upload failure. Local cache has been re-pulled from
    remote; caller must re-run the batch (idempotency contract)."""


class StorageDownloadError(DatabaseStoreError):
    """Terminal download failure."""


class StorageLeaseError(DatabaseStoreError):
    """Lease was lost mid-operation, never acquired, or a conditional
    PUT (If-Match / If-None-Match) failed."""


class StoreUnavailableError(DatabaseStoreError):
    """Configuration / init problem: bad credentials, missing
    container, malformed URL."""


# --- Retry policy -----------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_s: float = 1.0
    max_backoff_s: float = 30.0
    jitter: bool = True
    retry_on: tuple[type[BaseException], ...] = field(default_factory=lambda: (StorageTransientError,))


__all__ = [
    "DatabaseStoreError",
    "LockToken",
    "RetryPolicy",
    "StorageDownloadError",
    "StorageLeaseError",
    "StorageMetadata",
    "StorageTransientError",
    "StorageUploadError",
    "StoreUnavailableError",
    "WriteSession",
]
