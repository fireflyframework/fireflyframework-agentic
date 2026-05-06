# DB Storage Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `DatabaseStore` abstraction owning the read/write lifecycle of a single SQLite file with pluggable `LocalBackend` and `AzureBlobBackend`, then wire `SqliteCorpus` + `SqliteVecVectorStore` and the corpus_search example to use it end-to-end.

**Architecture:** Thin orchestrator (`DatabaseStore`) holds a persistent local cache (`<root>/<store_id>/db.sqlite` + `metadata.json` sidecar) and delegates physical storage to a `StorageBackend` ABC. Writes use a backend-level exclusive lock + etag-conditional upload; reads track a generation counter so caller-managed sqlite3 connections refresh when the cache file is replaced. Domain classes accept either a path (back-compat: wrapped in a `LocalBackend` internally) or a pre-built `DatabaseStore`.

**Tech Stack:** Python 3.13, `sqlite3` stdlib + `sqlite-vec` ext, `azure-storage-blob` + `azure-identity` (new optional `[storage-azure]` extra), `pytest` with `asyncio_mode=auto`, [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite) for Azure integration tests.

**Spec:** See `docs/superpowers/specs/2026-05-06-db-storage-backend-design.md` for the full design, error semantics, lifecycle diagrams, and idempotency contract.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/fireflyframework_agentic/storage/__init__.py` | Public exports: `DatabaseStore`, `StorageBackend`, `LocalBackend`, `AzureBlobBackend`, `WriteSession`, `RetryPolicy`, error types |
| `src/fireflyframework_agentic/storage/_types.py` | `StorageMetadata`, `LockToken`, `WriteSession`, `RetryPolicy`, error hierarchy |
| `src/fireflyframework_agentic/storage/backend.py` | `StorageBackend` ABC |
| `src/fireflyframework_agentic/storage/local_backend.py` | `LocalBackend` |
| `src/fireflyframework_agentic/storage/azure_backend.py` | `AzureBlobBackend` (only loaded when `[storage-azure]` is installed) |
| `src/fireflyframework_agentic/storage/database_store.py` | `DatabaseStore` orchestrator + retry helper |
| `tests/unit/storage/__init__.py` | (empty marker) |
| `tests/unit/storage/_fakes.py` | `InMemoryBackend` for unit-testing `DatabaseStore` |
| `tests/unit/storage/test_local_backend.py` | LocalBackend behaviour |
| `tests/unit/storage/test_database_store.py` | DatabaseStore lifecycle, retries, crash recovery |
| `tests/integration/storage/__init__.py` | (empty marker) |
| `tests/integration/storage/test_azure_backend_azurite.py` | Azurite-based AzureBlobBackend tests (`@pytest.mark.nightly`) |

**Modified files:**

| Path | Change |
|---|---|
| `src/fireflyframework_agentic/rag/corpus.py` | `SqliteCorpus.__init__` accepts `Path \| str \| DatabaseStore`; add `from_store` classmethod; route file lifecycle through store; add optional `session` kwarg to `upsert_chunks` / `delete_by_doc_id`; refresh connection on generation change |
| `src/fireflyframework_agentic/vectorstores/sqlite_vec_store.py` | Same pattern: dual-typed constructor, `from_store`, generation-aware connection, `session` kwarg on `_upsert` / `_delete` |
| `src/fireflyframework_agentic/rag/ingest/pipeline.py` | If corpus + vector_store share a `DatabaseStore`, wrap chunk + vector writes in one `async with store.for_write()` |
| `src/fireflyframework_agentic/rag/agent.py` | Construct one `DatabaseStore` and pass it to both `SqliteCorpus` and `SqliteVecVectorStore`; thread it through to the ingest pipeline call site |
| `examples/corpus_search/cli.py` | Honour `CORPUS_SEARCH_BACKEND=local|azure` env var when building the agent |
| `pyproject.toml` | New `[storage-azure]` extra; add `azure-storage-blob` |
| `tests/examples/corpus_search/test_query_path.py` | Parameterise over backend kind (`local` always, `azure_blob_azurite` when Azurite reachable) |
| `tests/integration/test_ingest_with_real_vectorstore.py` | Same parameterisation |

---

## Task 1: Types module — errors, RetryPolicy, dataclasses

**Files:**
- Create: `src/fireflyframework_agentic/storage/__init__.py`
- Create: `src/fireflyframework_agentic/storage/_types.py`
- Create: `tests/unit/storage/__init__.py`

- [ ] **Step 1: Create the empty package init files**

```bash
mkdir -p src/fireflyframework_agentic/storage tests/unit/storage tests/integration/storage
touch src/fireflyframework_agentic/storage/__init__.py
touch tests/unit/storage/__init__.py
touch tests/integration/storage/__init__.py
```

- [ ] **Step 2: Write `_types.py` with error hierarchy + dataclasses**

Create `src/fireflyframework_agentic/storage/_types.py`:

```python
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


class DatabaseStoreError(Exception):
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
    retry_on: tuple[type[BaseException], ...] = field(
        default_factory=lambda: (StorageTransientError,)
    )


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
    "StoreUnavailableError",
    "WriteSession",
]
```

- [ ] **Step 3: Add public re-exports in `__init__.py`**

Edit `src/fireflyframework_agentic/storage/__init__.py`:

```python
# Copyright 2026 Firefly Software Foundation ... (Apache-2.0 header)
"""Storage layer: managed-SQLite-file abstractions.

See docs/superpowers/specs/2026-05-06-db-storage-backend-design.md.
"""

from fireflyframework_agentic.storage._types import (
    DatabaseStoreError,
    LockToken,
    RetryPolicy,
    StorageDownloadError,
    StorageLeaseError,
    StorageMetadata,
    StorageTransientError,
    StorageUploadError,
    StoreUnavailableError,
    WriteSession,
)

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
```

(`DatabaseStore`, `LocalBackend`, etc. are added to `__all__` and imported in later tasks.)

- [ ] **Step 4: Verify imports work**

Run: `uv run python -c "from fireflyframework_agentic.storage import RetryPolicy, WriteSession, StorageUploadError; print('ok')"`
Expected output: `ok`

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/storage/ tests/unit/storage/__init__.py tests/integration/storage/__init__.py
git commit -m "feat(storage): types and error hierarchy"
```

---

## Task 2: `StorageBackend` ABC

**Files:**
- Create: `src/fireflyframework_agentic/storage/backend.py`
- Modify: `src/fireflyframework_agentic/storage/__init__.py`

- [ ] **Step 1: Write the ABC**

Create `src/fireflyframework_agentic/storage/backend.py`:

```python
# (Apache-2.0 header)
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
    async def metadata(self) -> StorageMetadata: ...

    @abstractmethod
    async def download(self, dest: Path) -> StorageMetadata:
        """Atomically replace ``dest`` with the current remote contents.
        Returns the metadata observed at the time of the read."""

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

    @abstractmethod
    async def acquire_lock(self, *, timeout: float) -> LockToken: ...

    @abstractmethod
    async def release_lock(self, token: LockToken) -> None: ...

    async def renew_lock(self, token: LockToken) -> LockToken:
        """Optional. Default raises NotImplementedError. Used by
        backends with bounded leases (Azure) to extend before
        expiry."""
        raise NotImplementedError
```

- [ ] **Step 2: Re-export `StorageBackend` from the package**

Edit `src/fireflyframework_agentic/storage/__init__.py` — add to imports:

```python
from fireflyframework_agentic.storage.backend import StorageBackend
```

And include `"StorageBackend"` in `__all__`.

- [ ] **Step 3: Smoke test**

Run: `uv run python -c "from fireflyframework_agentic.storage import StorageBackend; assert StorageBackend.__abstractmethods__; print('ok')"`
Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/fireflyframework_agentic/storage/
git commit -m "feat(storage): StorageBackend ABC"
```

---

## Task 3: `LocalBackend`

**Files:**
- Create: `src/fireflyframework_agentic/storage/local_backend.py`
- Create: `tests/unit/storage/test_local_backend.py`
- Modify: `src/fireflyframework_agentic/storage/__init__.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/storage/test_local_backend.py`:

```python
# (Apache-2.0 header)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/storage/test_local_backend.py -x -q`
Expected: ImportError / ModuleNotFoundError for `LocalBackend`.

- [ ] **Step 3: Implement `LocalBackend`**

Create `src/fireflyframework_agentic/storage/local_backend.py`:

```python
# (Apache-2.0 header)
"""LocalBackend: sqlite file on the local filesystem."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
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
            modified=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
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
        except asyncio.TimeoutError as exc:
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
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise StorageLeaseError(
                            "sentinel held by another process",
                            sentinel=str(self._sentinel),
                        )
                    await asyncio.sleep(0.05)
                    continue
                with os.fdopen(fd, "w") as f:
                    f.write(token_str)
                return LockToken(
                    token=token_str,
                    acquired_at=datetime.now(timezone.utc),
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
                self._sentinel, pid, process_alive, age,
            )
            try:
                self._sentinel.unlink()
            except FileNotFoundError:
                pass

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
            try:
                self._sentinel.unlink()
            except FileNotFoundError:
                pass
```

- [ ] **Step 4: Re-export `LocalBackend` from package**

Edit `src/fireflyframework_agentic/storage/__init__.py`:

```python
from fireflyframework_agentic.storage.local_backend import LocalBackend
```

And add `"LocalBackend"` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/storage/test_local_backend.py -x -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/fireflyframework_agentic/storage/local_backend.py src/fireflyframework_agentic/storage/__init__.py tests/unit/storage/test_local_backend.py
git commit -m "feat(storage): LocalBackend (filesystem + sentinel lock)"
```

---

## Task 4: `DatabaseStore` orchestrator

**Files:**
- Create: `src/fireflyframework_agentic/storage/database_store.py`
- Create: `tests/unit/storage/_fakes.py`
- Create: `tests/unit/storage/test_database_store.py`
- Modify: `src/fireflyframework_agentic/storage/__init__.py`

- [ ] **Step 1: Write the in-memory backend fake (test infrastructure)**

Create `tests/unit/storage/_fakes.py`:

```python
# (Apache-2.0 header)
"""In-memory StorageBackend fake for unit tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fireflyframework_agentic.storage._types import (
    LockToken,
    StorageLeaseError,
    StorageMetadata,
    StorageTransientError,
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
        self._modified = datetime.now(timezone.utc)
        self.uploads += 1
        return await self.metadata()

    async def acquire_lock(self, *, timeout: float) -> LockToken:
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise StorageLeaseError("lock timeout") from exc
        self._token = uuid.uuid4().hex
        return LockToken(
            token=self._token,
            acquired_at=datetime.now(timezone.utc),
            expires_at=None,
        )

    async def release_lock(self, token: LockToken) -> None:
        if self._token == token.token:
            self._token = None
        if self._lock.locked():
            self._lock.release()
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/storage/test_database_store.py`:

```python
# (Apache-2.0 header)
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.storage import (
    DatabaseStore,
    RetryPolicy,
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
    with pytest.raises(RuntimeError):
        async with store.for_write() as _session:
            raise RuntimeError("boom")
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
    writer = DatabaseStore(backend, store_id="w", cache_root=tmp_path / "w",
                           read_freshness_seconds=0.0)
    reader = DatabaseStore(backend, store_id="r", cache_root=tmp_path / "r",
                           read_freshness_seconds=0.0)
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/storage/test_database_store.py -x -q`
Expected: ImportError for `DatabaseStore`.

- [ ] **Step 4: Implement `DatabaseStore`**

Create `src/fireflyframework_agentic/storage/database_store.py`:

```python
# (Apache-2.0 header)
"""DatabaseStore: orchestrates a managed SQLite file over a StorageBackend."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fireflyframework_agentic.storage._types import (
    DatabaseStoreError,
    RetryPolicy,
    StorageDownloadError,
    StorageLeaseError,
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
    """Persistent {etag, dirty, last_modified} on disk."""

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
            meta = await self._backend.metadata()
            first_write = not meta.exists
            if not first_write and meta.etag != self._sidecar.etag:
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
            self._store_id, policy.max_attempts, last_exc,
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
        # Reserved for future symmetry. No-op today: nothing long-lived
        # to release at the DatabaseStore layer (the backend owns its
        # own clients/leases).
        return None


def _compute_backoff(policy: RetryPolicy, attempt: int) -> float:
    base = policy.initial_backoff_s * (2 ** (attempt - 1))
    capped = min(base, policy.max_backoff_s)
    if policy.jitter:
        capped *= 0.5 + random.random()
    return capped


__all__ = ["DatabaseStore"]
```

- [ ] **Step 5: Re-export `DatabaseStore` from package**

Edit `src/fireflyframework_agentic/storage/__init__.py`:

```python
from fireflyframework_agentic.storage.database_store import DatabaseStore
```

Add `"DatabaseStore"` to `__all__`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/storage/test_database_store.py -x -q`
Expected: all tests PASS.

- [ ] **Step 7: Re-run prior backend tests as a regression check**

Run: `uv run pytest tests/unit/storage/ -x -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/fireflyframework_agentic/storage/database_store.py src/fireflyframework_agentic/storage/__init__.py tests/unit/storage/_fakes.py tests/unit/storage/test_database_store.py
git commit -m "feat(storage): DatabaseStore orchestrator with retry + crash recovery"
```

---

## Task 5: `AzureBlobBackend` + `[storage-azure]` extra

**Files:**
- Modify: `pyproject.toml`
- Create: `src/fireflyframework_agentic/storage/azure_backend.py`
- Create: `tests/integration/storage/test_azure_backend_azurite.py`
- Modify: `src/fireflyframework_agentic/storage/__init__.py`

- [ ] **Step 1: Add the `storage-azure` extra**

Edit `pyproject.toml` `[project.optional-dependencies]` block — add a new key (alphabetically before `vectorstores-*`):

```toml
storage-azure = [
    "azure-storage-blob>=12.20.0",
    "azure-identity>=1.19",
]
```

- [ ] **Step 2: Lock and install**

Run: `uv sync --extra storage-azure`
Expected: lockfile updated, packages installed.

- [ ] **Step 3: Implement `AzureBlobBackend`**

Create `src/fireflyframework_agentic/storage/azure_backend.py`:

```python
# (Apache-2.0 header)
"""AzureBlobBackend: sqlite file in Azure Blob Storage."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fireflyframework_agentic.storage._types import (
    LockToken,
    StorageDownloadError,
    StorageLeaseError,
    StorageMetadata,
    StorageTransientError,
    StoreUnavailableError,
)
from fireflyframework_agentic.storage.backend import StorageBackend

log = logging.getLogger(__name__)


_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status in _RETRYABLE_STATUS:
        return True
    # Network / DNS / timeout errors look like generic OSError or
    # ServiceRequestError from azure-core.
    name = type(exc).__name__
    return name in {"ServiceRequestError", "ConnectionError", "TimeoutError"}


class AzureBlobBackend(StorageBackend):
    def __init__(
        self,
        container_url: str,
        blob_name: str,
        *,
        credential: Any,
        lease_duration_s: int = 60,
    ) -> None:
        try:
            from azure.storage.blob import BlobClient
        except ImportError as exc:
            raise StoreUnavailableError(
                "azure-storage-blob is not installed; install with "
                "`pip install fireflyframework-agentic[storage-azure]`"
            ) from exc
        self._BlobClient = BlobClient  # noqa: N803 — mirror class name
        self._container_url = container_url.rstrip("/")
        self._blob_name = blob_name
        self._credential = credential
        self._lease_duration_s = lease_duration_s
        self._client = self._BlobClient.from_blob_url(
            f"{self._container_url}/{blob_name}",
            credential=credential,
        )
        self._renew_task: asyncio.Task[None] | None = None
        self._renew_failure: BaseException | None = None

    @property
    def kind(self) -> str:
        return "azure_blob"

    async def metadata(self) -> StorageMetadata:
        return await asyncio.to_thread(self._metadata_sync)

    def _metadata_sync(self) -> StorageMetadata:
        try:
            props = self._client.get_blob_properties()
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 404:
                return StorageMetadata(etag=None, size_bytes=None, modified=None, exists=False)
            if _is_retryable(exc):
                raise StorageTransientError(f"metadata transient error: {exc}") from exc
            raise StoreUnavailableError(f"metadata: {exc}") from exc
        return StorageMetadata(
            etag=props.etag,
            size_bytes=props.size,
            modified=props.last_modified,
            exists=True,
        )

    async def download(self, dest: Path) -> StorageMetadata:
        return await asyncio.to_thread(self._download_sync, dest)

    def _download_sync(self, dest: Path) -> StorageMetadata:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + f".dl.{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as f:
                stream = self._client.download_blob()
                stream.readinto(f)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            if _is_retryable(exc):
                raise StorageTransientError(f"download transient: {exc}") from exc
            raise StorageDownloadError(f"download: {exc}") from exc
        import os
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
        kwargs: dict[str, Any] = {"overwrite": True}
        if if_match:
            kwargs["etag"] = if_match
            kwargs["match_condition"] = self._match_condition("IfMatch")
        if if_none_match:
            kwargs["etag"] = if_none_match
            kwargs["match_condition"] = self._match_condition("IfNoneMatch")
        try:
            with open(src, "rb") as f:
                resp = self._client.upload_blob(data=f, **kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 412:
                raise StorageLeaseError("conditional check failed") from exc
            if _is_retryable(exc):
                raise StorageTransientError(f"upload transient: {exc}") from exc
            raise
        # azure-storage-blob returns dict with etag
        new_etag = resp.get("etag") if isinstance(resp, dict) else getattr(resp, "etag", None)
        return self._metadata_sync() if new_etag is None else StorageMetadata(
            etag=new_etag,
            size_bytes=src.stat().st_size,
            modified=datetime.now(timezone.utc),
            exists=True,
        )

    @staticmethod
    def _match_condition(name: str) -> Any:
        from azure.core import MatchConditions  # type: ignore[import-not-found]
        return getattr(MatchConditions, name)

    async def acquire_lock(self, *, timeout: float) -> LockToken:
        deadline = asyncio.get_running_loop().time() + timeout
        last_exc: BaseException | None = None
        while True:
            try:
                lease = await asyncio.to_thread(
                    self._client.acquire_lease,
                    self._lease_duration_s,
                )
                break
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status == 409:  # lease already held
                    last_exc = exc
                    if asyncio.get_running_loop().time() >= deadline:
                        raise StorageLeaseError("lease busy") from exc
                    await asyncio.sleep(0.5)
                    continue
                if status == 404:
                    # Blob doesn't exist yet — first-write path. Use a
                    # synthetic non-blob lock: we'll race on the
                    # conditional upload (if_none_match='*').
                    return LockToken(
                        token="<no-blob-yet>",
                        acquired_at=datetime.now(timezone.utc),
                        expires_at=None,
                    )
                if _is_retryable(exc):
                    last_exc = exc
                    if asyncio.get_running_loop().time() >= deadline:
                        raise StorageLeaseError("lease transient") from exc
                    await asyncio.sleep(0.5)
                    continue
                raise StoreUnavailableError(f"acquire_lease: {exc}") from exc
        token = LockToken(
            token=lease.id,
            acquired_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),  # informational
        )
        self._renew_failure = None
        self._renew_task = asyncio.create_task(self._renew_loop(lease))
        return token

    async def _renew_loop(self, lease: Any) -> None:
        try:
            while True:
                await asyncio.sleep(max(self._lease_duration_s / 2, 1))
                try:
                    await asyncio.to_thread(lease.renew)
                except Exception as exc:
                    self._renew_failure = exc
                    log.error("lease renewal failed: %s", exc)
                    return
        except asyncio.CancelledError:
            return

    async def release_lock(self, token: LockToken) -> None:
        if self._renew_task is not None:
            self._renew_task.cancel()
            with contextlib_suppress():
                await self._renew_task
            self._renew_task = None
        if token.token == "<no-blob-yet>":
            return
        try:
            await asyncio.to_thread(self._client.get_blob_client_lease(token.token).release)
        except Exception as exc:  # noqa: BLE001 — release is best-effort
            log.warning("release_lock: %s", exc)


def contextlib_suppress():
    import contextlib
    return contextlib.suppress(asyncio.CancelledError, Exception)
```

- [ ] **Step 4: Re-export from package init (lazy import to avoid hard dep)**

Edit `src/fireflyframework_agentic/storage/__init__.py`:

```python
def __getattr__(name: str):
    if name == "AzureBlobBackend":
        from fireflyframework_agentic.storage.azure_backend import AzureBlobBackend
        return AzureBlobBackend
    raise AttributeError(name)
```

Add `"AzureBlobBackend"` to `__all__`.

- [ ] **Step 5: Write the Azurite integration test (nightly-marked)**

Create `tests/integration/storage/test_azure_backend_azurite.py`:

```python
# (Apache-2.0 header)
"""AzureBlobBackend tests against Azurite.

Skipped unless ``AZURITE_CONNECTION_STRING`` is set in the environment.
The standard Azurite default (``DefaultEndpointsProtocol=http;AccountName=...``)
is supplied by docker-compose in CI.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.nightly]

azurite_conn = os.environ.get("AZURITE_CONNECTION_STRING")

if not azurite_conn:
    pytest.skip("AZURITE_CONNECTION_STRING not set", allow_module_level=True)


@pytest.fixture
def container_url(tmp_path: Path) -> str:
    from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]
    svc = BlobServiceClient.from_connection_string(azurite_conn)
    name = f"dbstore-{uuid.uuid4().hex}"
    svc.create_container(name)
    yield f"{svc.url}{name}"
    try:
        svc.delete_container(name)
    except Exception:
        pass


@pytest.fixture
def credential() -> object:
    from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]
    svc = BlobServiceClient.from_connection_string(azurite_conn)
    return svc.credential


async def test_round_trip_upload_download(container_url, credential, tmp_path: Path) -> None:
    from fireflyframework_agentic.storage import AzureBlobBackend
    backend = AzureBlobBackend(container_url, "x.sqlite", credential=credential)
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello-azurite")
    meta = await backend.upload(src)
    assert meta.exists
    dest = tmp_path / "dst.bin"
    await backend.download(dest)
    assert dest.read_bytes() == b"hello-azurite"


async def test_lease_acquire_release(container_url, credential, tmp_path: Path) -> None:
    from fireflyframework_agentic.storage import AzureBlobBackend
    backend = AzureBlobBackend(container_url, "y.sqlite", credential=credential)
    src = tmp_path / "src.bin"
    src.write_bytes(b"v")
    await backend.upload(src)
    token = await backend.acquire_lock(timeout=5.0)
    await backend.release_lock(token)


async def test_database_store_e2e_against_azurite(container_url, credential, tmp_path: Path) -> None:
    import sqlite3
    from fireflyframework_agentic.storage import AzureBlobBackend, DatabaseStore
    backend = AzureBlobBackend(container_url, "e2e.sqlite", credential=credential)
    store = DatabaseStore(backend, store_id="azurite-e2e", cache_root=tmp_path / "cache")
    async with store.for_write() as session:
        conn = sqlite3.connect(session.path)
        conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('hi')")
        conn.commit()
        conn.close()

    # Fresh reader sees what we wrote.
    reader_store = DatabaseStore(backend, store_id="azurite-e2e-2",
                                 cache_root=tmp_path / "cache2")
    path, _ = await reader_store.ensure_fresh()
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT v FROM t").fetchall()
    conn.close()
    assert rows == [("hi",)]
```

- [ ] **Step 6: Verify Azurite test is correctly skipped without the env var**

Run: `uv run pytest tests/integration/storage/test_azure_backend_azurite.py -q`
Expected: `s` (skipped) lines, no failures.

- [ ] **Step 7: Run full storage suite as regression check**

Run: `uv run pytest tests/unit/storage/ tests/integration/storage/ -q`
Expected: unit tests PASS, integration SKIP.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/fireflyframework_agentic/storage/azure_backend.py src/fireflyframework_agentic/storage/__init__.py tests/integration/storage/test_azure_backend_azurite.py
git commit -m "feat(storage): AzureBlobBackend with lease + retry"
```

---

## Task 6: Wire `SqliteCorpus`

**Files:**
- Modify: `src/fireflyframework_agentic/rag/corpus.py`
- Modify: `tests/unit/rag/test_corpus.py` (smoke test for new constructor; existing tests stay green)

- [ ] **Step 1: Add tests for the new constructor surface**

Append to `tests/unit/rag/test_corpus.py`:

```python
from fireflyframework_agentic.storage import DatabaseStore, LocalBackend, WriteSession


async def test_sqlite_corpus_accepts_database_store(tmp_path):
    store = DatabaseStore(
        LocalBackend(tmp_path / "corpus.sqlite"),
        store_id="ut-corpus",
        cache_root=tmp_path / "cache",
    )
    c = SqliteCorpus(store)
    await c.initialise()
    chunks = [
        StoredChunk(chunk_id="d-0", doc_id="d", source_path="d.md",
                    index_in_doc=0, content="hello world", metadata={}),
    ]
    await c.upsert_chunks(chunks)
    rows = await c.query("SELECT chunk_id FROM chunks")
    assert rows[0]["chunk_id"] == "d-0"
    await c.close()


async def test_sqlite_corpus_session_kwarg_skips_own_lock(tmp_path):
    store = DatabaseStore(
        LocalBackend(tmp_path / "corpus.sqlite"),
        store_id="ut-corpus-session",
        cache_root=tmp_path / "cache",
    )
    c = SqliteCorpus(store)
    await c.initialise()
    async with store.for_write() as session:
        await c.upsert_chunks(
            [StoredChunk(chunk_id="x-0", doc_id="x", source_path="x.md",
                         index_in_doc=0, content="abc", metadata={})],
            session=session,
        )
    rows = await c.query("SELECT chunk_id FROM chunks WHERE chunk_id='x-0'")
    assert rows
    await c.close()
```

- [ ] **Step 2: Run these tests to verify they fail**

Run: `uv run pytest tests/unit/rag/test_corpus.py::test_sqlite_corpus_accepts_database_store -x -q`
Expected: FAIL (`SqliteCorpus.__init__` rejects `DatabaseStore`).

- [ ] **Step 3: Refactor `SqliteCorpus` to accept either a path or a `DatabaseStore`**

Replace the `SqliteCorpus` class body in `src/fireflyframework_agentic/rag/corpus.py` with:

```python
class SqliteCorpus:
    """SQLite-backed chunk store with FTS5 (BM25) over content.

    Constructor accepts either a path (back-compat: wrapped in a
    ``LocalBackend``-backed ``DatabaseStore`` automatically) or a
    pre-built ``DatabaseStore`` (preferred for Azure / remote storage).

    Read methods refresh the underlying connection when the
    DatabaseStore reports a new generation; write methods participate
    in a shared batch via the optional ``session`` kwarg.
    """

    def __init__(self, path_or_store: "str | Path | DatabaseStore") -> None:
        from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
        if isinstance(path_or_store, DatabaseStore):
            self._store = path_or_store
        else:
            p = Path(path_or_store)
            self._store = DatabaseStore(
                LocalBackend(p),
                store_id=f"local:{p.resolve()}",
            )
        self._conn: sqlite3.Connection | None = None
        self._generation: int = -1
        self._conn_lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        # Back-compat shim — some callers introspect this. Returns the
        # local cache path managed by the DatabaseStore.
        return self._store.cache_path

    async def initialise(self) -> None:
        async with self._store.for_write() as session:
            await asyncio.to_thread(self._init_schema_sync, session.path)

    def _init_schema_sync(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    async def close(self) -> None:
        async with self._conn_lock:
            if self._conn is not None:
                await asyncio.to_thread(self._conn.close)
                self._conn = None
        await self._store.close()

    async def _read_conn(self) -> sqlite3.Connection:
        path, generation = await self._store.ensure_fresh()
        async with self._conn_lock:
            if self._conn is None or generation != self._generation:
                if self._conn is not None:
                    await asyncio.to_thread(self._conn.close)
                self._conn = await asyncio.to_thread(_open_corpus_conn, path)
                self._generation = generation
            return self._conn

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        conn = await self._read_conn()
        return await asyncio.to_thread(self._query_sync, conn, sql, params or {})

    @staticmethod
    def _query_sync(conn: sqlite3.Connection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    async def upsert_chunks(
        self,
        chunks: Sequence[StoredChunk],
        *,
        session: "WriteSession | None" = None,
    ) -> None:
        if not chunks:
            return
        if session is None:
            async with self._store.for_write() as session:
                await self._upsert_in_session(session, list(chunks))
        else:
            await self._upsert_in_session(session, list(chunks))

    async def _upsert_in_session(self, session: "WriteSession", chunks: list[StoredChunk]) -> None:
        await asyncio.to_thread(self._upsert_chunks_sync, session.path, chunks)

    @staticmethod
    def _upsert_chunks_sync(path: Path, chunks: list[StoredChunk]) -> None:
        conn = _open_corpus_conn(path)
        try:
            conn.execute("BEGIN")
            try:
                for c in chunks:
                    conn.execute(
                        """INSERT OR REPLACE INTO chunks
                           (chunk_id, doc_id, source_path, index_in_doc, content, metadata)
                           VALUES (:chunk_id, :doc_id, :source_path, :index_in_doc, :content, :metadata)""",
                        {
                            "chunk_id": c.chunk_id,
                            "doc_id": c.doc_id,
                            "source_path": c.source_path,
                            "index_in_doc": c.index_in_doc,
                            "content": c.content,
                            "metadata": json.dumps(c.metadata),
                        },
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    async def delete_by_doc_id(
        self,
        doc_id: str,
        *,
        session: "WriteSession | None" = None,
    ) -> int:
        if session is None:
            async with self._store.for_write() as session:
                return await asyncio.to_thread(self._delete_by_doc_id_sync, session.path, doc_id)
        return await asyncio.to_thread(self._delete_by_doc_id_sync, session.path, doc_id)

    @staticmethod
    def _delete_by_doc_id_sync(path: Path, doc_id: str) -> int:
        conn = _open_corpus_conn(path)
        try:
            conn.execute("BEGIN")
            try:
                n = conn.execute(
                    "DELETE FROM chunks WHERE doc_id = :doc",
                    {"doc": doc_id},
                ).rowcount
                conn.execute("COMMIT")
                return n
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    async def bm25_search(self, query: str, *, top_k: int = 30) -> list[ChunkHit]:
        conn = await self._read_conn()
        return await asyncio.to_thread(self._bm25_search_sync, conn, query, top_k)

    @staticmethod
    def _bm25_search_sync(conn: sqlite3.Connection, query: str, top_k: int) -> list[ChunkHit]:
        match_expr = sanitize_fts_query(query)
        if not match_expr:
            return []
        try:
            cur = conn.execute(
                """SELECT c.chunk_id, c.content, c.metadata, c.doc_id, c.source_path,
                          bm25(chunks_fts) AS score
                   FROM chunks_fts
                   JOIN chunks c ON c.rowid = chunks_fts.rowid
                   WHERE chunks_fts MATCH :q
                   ORDER BY score
                   LIMIT :k""",
                {"q": match_expr, "k": top_k},
            )
        except sqlite3.OperationalError as exc:
            log.warning("bm25_search returned no results due to OperationalError: %s", exc)
            return []
        return [
            ChunkHit(
                chunk_id=r["chunk_id"],
                score=float(r["score"]),
                content=r["content"],
                metadata=json.loads(r["metadata"]),
                source_path=r["source_path"],
                doc_id=r["doc_id"],
            )
            for r in cur.fetchall()
        ]

    async def get_chunks(self, chunk_ids: list[str]) -> list[StoredChunk]:
        if not chunk_ids:
            return []
        placeholders = ",".join(f":id{i}" for i in range(len(chunk_ids)))
        params = {f"id{i}": cid for i, cid in enumerate(chunk_ids)}
        rows = await self.query(
            f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})",
            params,
        )
        return [
            StoredChunk(
                chunk_id=r["chunk_id"],
                doc_id=r["doc_id"],
                source_path=r["source_path"],
                index_in_doc=r["index_in_doc"],
                content=r["content"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]


def _open_corpus_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from fireflyframework_agentic.storage import DatabaseStore, WriteSession
```

- [ ] **Step 4: Run the full corpus test suite**

Run: `uv run pytest tests/unit/rag/test_corpus.py tests/unit/rag/test_telemetry_emission.py tests/unit/rag/retrieval/test_hybrid.py -x -q`
Expected: all PASS — including the existing `SqliteCorpus(tmp_path / "corpus.sqlite")` tests (back-compat path) AND the two new constructor tests.

- [ ] **Step 5: Run the broader rag test suite**

Run: `uv run pytest tests/unit/rag/ tests/rag/ tests/unit/content/sources/test_pipeline_integration.py -x -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/fireflyframework_agentic/rag/corpus.py tests/unit/rag/test_corpus.py
git commit -m "feat(rag): SqliteCorpus accepts DatabaseStore (with path back-compat)"
```

---

## Task 7: Wire `SqliteVecVectorStore`

**Files:**
- Modify: `src/fireflyframework_agentic/vectorstores/sqlite_vec_store.py`
- Modify: `tests/unit/vectorstores/test_sqlite_vec_store.py` (add new constructor smoke test)

- [ ] **Step 1: Add a test for the DatabaseStore constructor**

Append to `tests/unit/vectorstores/test_sqlite_vec_store.py`:

```python
async def test_sqlite_vec_store_accepts_database_store(tmp_path):
    from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
    store = DatabaseStore(
        LocalBackend(tmp_path / "vec.sqlite"),
        store_id="ut-vec",
        cache_root=tmp_path / "cache",
    )
    s = SqliteVecVectorStore(store, dimension=4)
    docs = [VectorDocument(id="a", text="x", metadata={}, embedding=[0.1, 0.2, 0.3, 0.4])]
    await s.upsert(docs, namespace="default")
    hits = await s.search([0.1, 0.2, 0.3, 0.4], top_k=1, namespace="default")
    assert hits and hits[0].document.id == "a"
    await s.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/vectorstores/test_sqlite_vec_store.py::test_sqlite_vec_store_accepts_database_store -x -q`
Expected: FAIL (constructor rejects DatabaseStore).

- [ ] **Step 3: Refactor `SqliteVecVectorStore`**

Edit `src/fireflyframework_agentic/vectorstores/sqlite_vec_store.py`:

Replace the `__init__`, `_initialise_sync`, `_ensure_ready`, and the four interface methods with versions that route through DatabaseStore. The constructor accepts EITHER the new positional `path_or_store` OR the legacy `db_path` keyword (so existing tests keep working without edit):

```python
class SqliteVecVectorStore(BaseVectorStore):
    def __init__(
        self,
        path_or_store: "str | Path | DatabaseStore | None" = None,
        dimension: int = 0,
        *,
        db_path: "str | Path | None" = None,
        table_name: str = "vec_chunks",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if path_or_store is None and db_path is None:
            raise TypeError("SqliteVecVectorStore requires path_or_store or db_path")
        target = path_or_store if path_or_store is not None else db_path
        from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
        if isinstance(target, DatabaseStore):
            self._store = target
        else:
            p = Path(target)
            self._store = DatabaseStore(
                LocalBackend(p),
                store_id=f"local:{p.resolve()}",
            )
        self._dim = dimension
        self._tbl = table_name
        self._shadow = f"{table_name}_shadow"
        self._conn: sqlite3.Connection | None = None
        self._generation: int = -1
        self._conn_lock = asyncio.Lock()

    async def _read_conn(self) -> sqlite3.Connection:
        path, generation = await self._store.ensure_fresh()
        async with self._conn_lock:
            if self._conn is None or generation != self._generation:
                if self._conn is not None:
                    await asyncio.to_thread(self._conn.close)
                self._conn = await asyncio.to_thread(self._open_conn_with_schema, path)
                self._generation = generation
            return self._conn

    def _open_conn_with_schema(self, path: Path) -> sqlite3.Connection:
        if sqlite_vec is None:
            raise ImportError(
                "sqlite-vec is required for SqliteVecVectorStore. "
                "Install with: pip install 'fireflyframework-agentic[vectorstores-sqlite-vec]'"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._shadow} (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                id    TEXT UNIQUE NOT NULL,
                ns    TEXT NOT NULL DEFAULT 'default'
            )
        """)
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {self._tbl}
            USING vec0(embedding float[{self._dim}] distance_metric=cosine)
        """)
        return conn

    async def _upsert(
        self,
        documents: list[VectorDocument],
        namespace: str,
        *,
        session: "WriteSession | None" = None,
    ) -> None:
        if session is None:
            async with self._store.for_write() as session:
                await asyncio.to_thread(self._upsert_via_path_sync, session.path, documents, namespace)
        else:
            await asyncio.to_thread(self._upsert_via_path_sync, session.path, documents, namespace)

    def _upsert_via_path_sync(self, path: Path, documents: list[VectorDocument], namespace: str) -> None:
        conn = self._open_conn_with_schema(path)
        try:
            self._upsert_sync_on(conn, documents, namespace)
        finally:
            conn.close()

    def _upsert_sync_on(self, conn: sqlite3.Connection, documents: list[VectorDocument], namespace: str) -> None:
        conn.execute("BEGIN")
        try:
            for doc in documents:
                conn.execute(
                    f"INSERT INTO {self._shadow}(id, ns) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET ns=excluded.ns",
                    (doc.id, namespace),
                )
                row = conn.execute(f"SELECT rowid FROM {self._shadow} WHERE id = ?", (doc.id,)).fetchone()
                rowid = row[0]
                conn.execute(f"DELETE FROM {self._tbl} WHERE rowid = ?", (rowid,))
                assert doc.embedding is not None
                conn.execute(
                    f"INSERT INTO {self._tbl}(rowid, embedding) VALUES(?, ?)",
                    (rowid, serialize_float32(doc.embedding)),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]:
        conn = await self._read_conn()
        return await asyncio.to_thread(self._search_sync, conn, query_embedding, top_k, namespace)

    def _search_sync(
        self,
        conn: sqlite3.Connection,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
    ) -> list[SearchResult]:
        rows = conn.execute(
            f"""
            SELECT s.id, v.distance
            FROM (
                SELECT rowid, distance
                FROM {self._tbl}
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            ) v
            JOIN {self._shadow} s ON s.rowid = v.rowid
            WHERE s.ns = ?
            """,
            (serialize_float32(query_embedding), top_k, namespace),
        ).fetchall()
        return [
            SearchResult(
                document=VectorDocument(id=row["id"], text="", metadata={}),
                score=1.0 - row["distance"],
            )
            for row in rows
        ]

    async def _delete(
        self,
        ids: list[str],
        namespace: str,
        *,
        session: "WriteSession | None" = None,
    ) -> None:
        if session is None:
            async with self._store.for_write() as session:
                await asyncio.to_thread(self._delete_via_path_sync, session.path, ids, namespace)
        else:
            await asyncio.to_thread(self._delete_via_path_sync, session.path, ids, namespace)

    def _delete_via_path_sync(self, path: Path, ids: list[str], namespace: str) -> None:
        if not ids:
            return
        conn = self._open_conn_with_schema(path)
        try:
            self._delete_sync_on(conn, ids, namespace)
        finally:
            conn.close()

    def _delete_sync_on(self, conn: sqlite3.Connection, ids: list[str], namespace: str) -> None:
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT rowid FROM {self._shadow} WHERE id IN ({ph}) AND ns = ?",
            (*ids, namespace),
        ).fetchall()
        rowids = [r[0] for r in rows]
        conn.execute("BEGIN")
        try:
            if rowids:
                rph = ",".join("?" * len(rowids))
                conn.execute(f"DELETE FROM {self._tbl} WHERE rowid IN ({rph})", rowids)
            conn.execute(
                f"DELETE FROM {self._shadow} WHERE id IN ({ph}) AND ns = ?",
                (*ids, namespace),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    async def close(self) -> None:
        async with self._conn_lock:
            if self._conn is not None:
                await asyncio.to_thread(self._conn.close)
                self._conn = None
        await self._store.close()


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from fireflyframework_agentic.storage import DatabaseStore, WriteSession
```

- [ ] **Step 4: Run all vectorstore tests**

Run: `uv run pytest tests/unit/vectorstores/ -x -q`
Expected: PASS — including the new DatabaseStore constructor test and all existing `db_path=` tests.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/vectorstores/sqlite_vec_store.py tests/unit/vectorstores/test_sqlite_vec_store.py
git commit -m "feat(vectorstores): SqliteVecVectorStore accepts DatabaseStore"
```

---

## Task 8: Coordinated batch in the ingest pipeline

**Files:**
- Modify: `src/fireflyframework_agentic/rag/ingest/pipeline.py`
- Modify: `src/fireflyframework_agentic/rag/agent.py`
- Modify: `tests/unit/rag/ingest/test_pipeline.py` (assert single upload)

- [ ] **Step 1: Read the existing ingest call site for context**

Run: `uv run python -c "import inspect, fireflyframework_agentic.rag.ingest.pipeline as p; print(p.__file__)"` and read lines 200-280 of that file. Identify the function that performs `corpus.upsert_chunks(...)` then `vector_store.upsert(...)`.

- [ ] **Step 2: Decide the wiring point**

If both `corpus` and `vector_store` are constructed against the **same** `DatabaseStore` (typical for `corpus_search`), the pipeline should wrap both writes in one `for_write`. If they have different stores (uncommon, e.g., chunks-on-local + vectors-elsewhere), call each independently. Detection:

```python
shared_store = (
    corpus._store
    if hasattr(corpus, "_store")
    and hasattr(vector_store, "_store")
    and corpus._store is vector_store._store
    else None
)
```

(Yes, this introspects a single underscore attribute. Acceptable cohesion within the framework's own modules; document with a comment.)

- [ ] **Step 3: Update the pipeline write block**

In `src/fireflyframework_agentic/rag/ingest/pipeline.py` around the existing
`await corpus.upsert_chunks(stored_chunks)` / `await vector_store.upsert(vector_docs)`
block, change to:

```python
shared_store = (
    corpus._store
    if hasattr(corpus, "_store")
    and hasattr(vector_store, "_store")
    and corpus._store is vector_store._store
    else None
)
if shared_store is not None:
    async with shared_store.for_write() as session:
        await corpus.upsert_chunks(stored_chunks, session=session)
        await vector_store.upsert(vector_docs, session=session)
else:
    await corpus.upsert_chunks(stored_chunks)
    await vector_store.upsert(vector_docs)
```

(Imports stay the same; `WriteSession` is not directly imported here — `session` is just passed through as an opaque object.)

Run the existing pipeline tests:

Run: `uv run pytest tests/unit/rag/ingest/test_pipeline.py -x -q`
Expected: all PASS (no behaviour change for the path-based test fixtures, since the new `path_or_store` constructor wraps each path in its own DatabaseStore — `corpus._store is vector_store._store` is False, so the legacy path is taken).

- [ ] **Step 4: Add a regression test that pins the single-upload behaviour**

Add to `tests/unit/rag/ingest/test_pipeline.py`:

```python
async def test_shared_store_results_in_one_upload(tmp_path):
    """When corpus and vector_store share a DatabaseStore, ingestion
    produces one upload per batch, not two."""
    from fireflyframework_agentic.rag.corpus import SqliteCorpus
    from fireflyframework_agentic.storage import DatabaseStore
    from fireflyframework_agentic.vectorstores.sqlite_vec_store import SqliteVecVectorStore
    from tests.unit.storage._fakes import InMemoryBackend

    backend = InMemoryBackend()
    store = DatabaseStore(backend, store_id="pipe", cache_root=tmp_path / "cache")
    corpus = SqliteCorpus(store)
    await corpus.initialise()
    vec = SqliteVecVectorStore(store, dimension=4)

    # Run the same low-level write the pipeline performs in shared-store mode.
    async with store.for_write() as session:
        await corpus.upsert_chunks(
            [StoredChunk(chunk_id="a-0", doc_id="a", source_path="a", index_in_doc=0,
                         content="hello", metadata={})],
            session=session,
        )
        await vec.upsert(
            [VectorDocument(id="a-0", text="hello", metadata={}, embedding=[0.1, 0.2, 0.3, 0.4])],
            namespace="default",
            session=session,
        )

    # Initialise also uploads once → expect 2 total: init + this batch.
    assert backend.uploads == 2
    await corpus.close()
    await vec.close()
```

(Imports `StoredChunk`, `VectorDocument` should already be present near the top of the file.)

- [ ] **Step 5: Run pipeline tests**

Run: `uv run pytest tests/unit/rag/ingest/ -x -q`
Expected: PASS.

- [ ] **Step 6: Update `rag/agent.py` to construct one shared store**

Inspect `src/fireflyframework_agentic/rag/agent.py` line 97 where the corpus is built and line 193 where the vector store is built. Refactor so they share one `DatabaseStore`:

```python
# Replace:
#   self._corpus = SqliteCorpus(self.root / "corpus.sqlite")
# with:
from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
self._db_store = DatabaseStore(
    LocalBackend(self.root / "corpus.sqlite"),
    store_id=f"corpus_search:{self.root.resolve()}",
)
self._corpus = SqliteCorpus(self._db_store)

# In the vector_store factory (line 193 area):
return SqliteVecVectorStore(self._db_store, dimension=self.embed_dimension)
```

- [ ] **Step 7: Smoke test the corpus_search path**

Run: `uv run pytest tests/examples/corpus_search/test_query_path.py -x -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/fireflyframework_agentic/rag/ingest/pipeline.py src/fireflyframework_agentic/rag/agent.py tests/unit/rag/ingest/test_pipeline.py
git commit -m "feat(rag): coordinated ingest batch via shared DatabaseStore"
```

---

## Task 9: corpus_search example backend env toggle

**Files:**
- Modify: `examples/corpus_search/cli.py`
- Modify: `src/fireflyframework_agentic/rag/agent.py` (accept an injected store)

- [ ] **Step 1: Make `CorpusAgent` accept an injected store**

In `src/fireflyframework_agentic/rag/agent.py`, locate the constructor that holds the line modified in Task 8 step 6 (around line 97 of the original file, now building a `DatabaseStore` from `LocalBackend(self.root / "corpus.sqlite")`).

Two changes:

1. Add a new keyword-only parameter `db_store: "DatabaseStore | None" = None` to the constructor signature, alongside (and after) the existing keyword-only parameters. Do not remove or rename any existing parameter.
2. Replace the unconditional `DatabaseStore(...)` construction added in Task 8 with a guarded version that uses the injected store when present:

```python
if db_store is None:
    from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
    db_store = DatabaseStore(
        LocalBackend(self.root / "corpus.sqlite"),
        store_id=f"corpus_search:{self.root.resolve()}",
    )
self._db_store = db_store
self._corpus = SqliteCorpus(db_store)
```

The vector store factory at the bottom of the same class (around line 193) already returns `SqliteVecVectorStore(self._db_store, dimension=self.embed_dimension)` after Task 8 — no further change.

Add the type-only forward reference at the bottom of the module:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from fireflyframework_agentic.storage import DatabaseStore
```

- [ ] **Step 2: Wire the env var in `cli.py`**

In `examples/corpus_search/cli.py`, add a helper near `_check_keys`:

```python
def _build_db_store(root: Path) -> "DatabaseStore":
    from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
    backend_kind = os.environ.get("CORPUS_SEARCH_BACKEND", "local")
    if backend_kind == "local":
        backend = LocalBackend(root / "corpus.sqlite")
    elif backend_kind == "azure":
        from fireflyframework_agentic.storage import AzureBlobBackend
        from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
        container_url = os.environ["CORPUS_SEARCH_AZURE_CONTAINER_URL"]
        blob_name = os.environ.get("CORPUS_SEARCH_AZURE_BLOB_NAME", "corpus.sqlite")
        backend = AzureBlobBackend(container_url, blob_name, credential=DefaultAzureCredential())
    else:
        raise SystemExit(f"Unknown CORPUS_SEARCH_BACKEND={backend_kind!r}")
    return DatabaseStore(backend, store_id=f"corpus_search:{root.resolve()}")
```

In `_run_ingest`, `_run_query`, and `_run_show_chunk`, pass the built store into `CorpusAgent(...)`:

```python
db_store = _build_db_store(args.root)
agent = CorpusAgent(
    root=args.root,
    ...,
    db_store=db_store,
)
```

For `_run_show_chunk`, replace `SqliteCorpus(corpus_path)` with `SqliteCorpus(_build_db_store(args.root))`.

- [ ] **Step 3: Smoke test the local default**

Run: `CORPUS_SEARCH_BACKEND=local uv run python -c "from examples.corpus_search.cli import _build_db_store; from pathlib import Path; s = _build_db_store(Path('./kg')); print(s.store_id)"`
Expected output starts with `corpus_search:`.

- [ ] **Step 4: Smoke test the azure path raises clearly without env**

Run: `CORPUS_SEARCH_BACKEND=azure uv run python -c "from examples.corpus_search.cli import _build_db_store; from pathlib import Path; _build_db_store(Path('./kg'))"`
Expected: `KeyError: 'CORPUS_SEARCH_AZURE_CONTAINER_URL'` (or similar — anyway, it must fail loudly, not silently).

- [ ] **Step 5: Commit**

```bash
git add examples/corpus_search/cli.py src/fireflyframework_agentic/rag/agent.py
git commit -m "feat(corpus_search): CORPUS_SEARCH_BACKEND env toggle (local|azure)"
```

---

## Task 10: Azurite-parameterised E2E tests for corpus_search

**Files:**
- Modify: `tests/examples/corpus_search/test_query_path.py`
- Modify: `tests/integration/test_ingest_with_real_vectorstore.py`

- [ ] **Step 1: Add a parametrised fixture that returns a (DatabaseStore, label) pair**

Append to `tests/examples/corpus_search/test_query_path.py`:

```python
import os
import uuid

import pytest

_HAVE_AZURITE = bool(os.environ.get("AZURITE_CONNECTION_STRING"))

_BACKENDS = ["local"]
if _HAVE_AZURITE:
    _BACKENDS.append("azurite")


@pytest.fixture(params=_BACKENDS)
def db_store(request, tmp_path):
    from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
    if request.param == "local":
        backend = LocalBackend(tmp_path / "corpus.sqlite")
    else:
        from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]
        from fireflyframework_agentic.storage import AzureBlobBackend
        svc = BlobServiceClient.from_connection_string(os.environ["AZURITE_CONNECTION_STRING"])
        container = f"e2e-{uuid.uuid4().hex}"
        svc.create_container(container)
        backend = AzureBlobBackend(
            f"{svc.url}{container}",
            "corpus.sqlite",
            credential=svc.credential,
        )
        request.addfinalizer(lambda: svc.delete_container(container))
    return DatabaseStore(backend, store_id=f"e2e-{request.param}",
                        cache_root=tmp_path / "cache")
```

- [ ] **Step 2: Convert one existing test to parameterise over `db_store`**

Pick the first test in the file. Wherever it builds `SqliteCorpus(tmp_path / "corpus.sqlite")`, change to `SqliteCorpus(db_store)`. Same for any vector store. Keep all other assertions identical.

- [ ] **Step 3: Run unparameterised baseline (Azurite skipped)**

Run: `uv run pytest tests/examples/corpus_search/test_query_path.py -x -q`
Expected: only the `local` parameter runs; PASS.

- [ ] **Step 4: Repeat for `tests/integration/test_ingest_with_real_vectorstore.py`**

Apply the same fixture + substitution pattern. Mark the test module
`pytestmark = [pytest.mark.nightly]` if it isn't already (this is a real-LLM/real-vectorstore test).

- [ ] **Step 5: Run the full PR-gate test suite as a final regression check**

Run: `uv run pytest -x -q -m "not nightly"`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/examples/corpus_search/test_query_path.py tests/integration/test_ingest_with_real_vectorstore.py
git commit -m "test(storage): parameterise corpus_search E2E over local + Azurite backends"
```

---

## Final verification

- [ ] **Step 1: Full regression across what this PR touches**

Run: `uv run pytest tests/unit/storage/ tests/unit/rag/ tests/unit/vectorstores/ tests/examples/corpus_search/ -q`
Expected: all PASS. No skipped tests we didn't intend to skip.

- [ ] **Step 2: Type check (basic mode)**

Run: `uv run pyright src/fireflyframework_agentic/storage src/fireflyframework_agentic/rag/corpus.py src/fireflyframework_agentic/vectorstores/sqlite_vec_store.py 2>&1 | head -50`
Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Manual smoke (corpus_search ingest + query in local mode)**

Run, against a small drop folder:

```bash
mkdir -p /tmp/firefly-smoke/drop
echo "Hello firefly" > /tmp/firefly-smoke/drop/hello.txt
CORPUS_SEARCH_BACKEND=local uv run python -m examples.corpus_search ingest \
    --folder /tmp/firefly-smoke/drop \
    --root /tmp/firefly-smoke/kg \
    --embed-model openai:text-embedding-3-small \
    --embed-dimension 1536
ls /tmp/firefly-smoke/kg/corpus.sqlite
```

Expected: ingest run completes; `corpus.sqlite` exists.

If you can also start Azurite locally (`docker run -p 10000:10000 mcr.microsoft.com/azure-storage/azurite`), repeat with `CORPUS_SEARCH_BACKEND=azure` and the appropriate env vars.

- [ ] **Step 4: Final commit (if anything cleaned up)**

```bash
git status
# If clean, no commit needed.
# Otherwise:
git add ...
git commit -m "chore: cleanup after db storage backend wiring"
```
