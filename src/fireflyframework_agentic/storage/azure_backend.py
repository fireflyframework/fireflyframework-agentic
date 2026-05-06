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

"""AzureBlobBackend: sqlite file in Azure Blob Storage."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from datetime import UTC, datetime
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
            from azure.storage.blob import BlobClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise StoreUnavailableError(
                "azure-storage-blob is not installed; install with "
                "`pip install fireflyframework-agentic[storage-azure]`"
            ) from exc
        self._BlobClient = BlobClient
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
        new_etag = resp.get("etag") if isinstance(resp, dict) else getattr(resp, "etag", None)
        if new_etag is None:
            return self._metadata_sync()
        return StorageMetadata(
            etag=new_etag,
            size_bytes=src.stat().st_size,
            modified=datetime.now(UTC),
            exists=True,
        )

    @staticmethod
    def _match_condition(name: str) -> Any:
        from azure.core import MatchConditions  # type: ignore[import-not-found]

        return getattr(MatchConditions, name)

    async def acquire_lock(self, *, timeout: float) -> LockToken:
        deadline = asyncio.get_running_loop().time() + timeout
        last_exc: BaseException | None = None
        lease = None
        while lease is None:
            try:
                lease = await asyncio.to_thread(
                    self._client.acquire_lease,
                    self._lease_duration_s,
                )
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status == 409:  # lease already held
                    last_exc = exc
                    if asyncio.get_running_loop().time() >= deadline:
                        raise StorageLeaseError("lease busy") from exc
                    await asyncio.sleep(0.5)
                    continue
                if status == 404:
                    # Blob doesn't exist yet — first-write path. Return a
                    # synthetic non-blob lock; we'll race on the
                    # conditional upload (if_none_match='*').
                    return LockToken(
                        token="<no-blob-yet>",
                        acquired_at=datetime.now(UTC),
                        expires_at=None,
                    )
                if _is_retryable(exc):
                    last_exc = exc
                    if asyncio.get_running_loop().time() >= deadline:
                        raise StorageLeaseError("lease transient") from exc
                    await asyncio.sleep(0.5)
                    continue
                raise StoreUnavailableError(f"acquire_lease: {exc}") from exc
        _ = last_exc  # consumed above; referenced to satisfy linters
        token = LockToken(
            token=lease.id,
            acquired_at=datetime.now(UTC),
            expires_at=datetime.now(UTC),  # informational
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
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._renew_task
            self._renew_task = None
        if token.token == "<no-blob-yet>":
            return
        try:
            from azure.storage.blob import BlobLeaseClient  # type: ignore[import-not-found]

            lease = BlobLeaseClient(self._client, lease_id=token.token)
            await asyncio.to_thread(lease.release)
        except Exception as exc:
            log.warning("release_lock: %s", exc)
