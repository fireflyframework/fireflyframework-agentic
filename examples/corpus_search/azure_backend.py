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

"""Azure Blob Storage backed corpus storage for the corpus_search example.

This module bundles two related pieces:

* :class:`AzureBlobBackend` — the :class:`StorageBackend` implementation
  used by :class:`DatabaseStore`. One backend per corpus, each pointing
  at a single sqlite blob with leased writes.
* :class:`AzureCorpusBackendRegistry` + :func:`build_registry` — the
  :class:`CorpusBackendRegistry` activated on the MCP server via
  ``CORPUS_BACKEND_REGISTRY_FACTORY=examples.corpus_search.azure_backend:build_registry``.
  Maps each corpus to a ``<corpus_id>.sqlite`` blob in a configured
  container and enumerates by listing the container.

Both authenticate via ``DefaultAzureCredential`` so the same code runs
under managed identity (Container Apps) and ``az login`` (local dev).
``azure-storage-blob`` is imported lazily inside the constructors so a
host without the SDK installed can still import this module; callers
only pay the import cost when they actually construct an instance.

Requires the corpus_search example deps (which include
``azure-storage-blob`` and ``azure-identity``); the framework itself
stays vendor-neutral.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
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
        # Lease ID currently held; used to authorise writes on the
        # leased blob (Azure rejects writes without it once a lease is
        # acquired). None means no lease is held.
        self._active_lease_id: str | None = None

    @property
    def kind(self) -> str:
        return "azure_blob"

    def _check_renew_failure(self) -> None:
        if self._renew_failure is not None:
            failure = self._renew_failure
            self._renew_failure = None
            raise StorageLeaseError("lease renewal failed mid-operation") from failure

    async def metadata(self) -> StorageMetadata:
        self._check_renew_failure()
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
        self._check_renew_failure()
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
        self._check_renew_failure()
        return await asyncio.to_thread(self._upload_sync, src, if_match, if_none_match)

    def _upload_sync(
        self,
        src: Path,
        if_match: str | None,
        if_none_match: str | None,
    ) -> StorageMetadata:
        # azure-core's MatchConditions enum maps semantically rather than
        # by HTTP header name:
        #   IfNotModified -> If-Match: <etag>   (succeed iff etag matches)
        #   IfMissing     -> If-None-Match: *   (succeed iff blob absent)
        kwargs: dict[str, Any] = {"overwrite": True}
        if if_match:
            kwargs["etag"] = if_match
            kwargs["match_condition"] = self._match_condition("IfNotModified")
        elif if_none_match == "*":
            kwargs["match_condition"] = self._match_condition("IfMissing")
        # Once a lease is held on the blob, every subsequent write must
        # include the lease ID or Azure rejects with 412.
        if self._active_lease_id is not None:
            kwargs["lease"] = self._active_lease_id
        try:
            with open(src, "rb") as f:
                self._client.upload_blob(data=f, **kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 412:
                raise StorageLeaseError("conditional check failed") from exc
            if _is_retryable(exc):
                raise StorageTransientError(f"upload transient: {exc}") from exc
            raise
        # Always re-stat to get the canonical etag (the upload response
        # and get_blob_properties may format the etag differently — using
        # the metadata read keeps subsequent if_match calls consistent).
        return self._metadata_sync()

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
        now = datetime.now(UTC)
        token = LockToken(
            token=lease.id,
            acquired_at=now,
            expires_at=now + timedelta(seconds=self._lease_duration_s),
        )
        self._renew_failure = None
        self._active_lease_id = lease.id
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
        self._check_renew_failure()
        if self._renew_task is not None:
            self._renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._renew_task
            self._renew_task = None
        self._active_lease_id = None
        if token.token == "<no-blob-yet>":
            return
        try:
            from azure.storage.blob import BlobLeaseClient  # type: ignore[import-not-found]

            lease = BlobLeaseClient(self._client, lease_id=token.token)
            await asyncio.to_thread(lease.release)
        except Exception as exc:
            log.warning("release_lock: %s", exc)


# ---------- corpus registry ------------------------------------------------
#
# Activate on the MCP server via:
#   CORPUS_BACKEND_REGISTRY_FACTORY=examples.corpus_search.azure_backend:build_registry
#   CORPUS_AZURE_CONTAINER_URL=https://<account>.blob.core.windows.net/<container>

_CONTAINER_URL_ENV = "CORPUS_AZURE_CONTAINER_URL"
_MI_CLIENT_ID_ENV = "CORPUS_AZURE_MANAGED_IDENTITY_CLIENT_ID"
_SQLITE_SUFFIX = ".sqlite"


def _blob_name_for(corpus_id: str) -> str:
    """Map ``corpus_id`` to the blob name that stores its sqlite file.

    Kept as a single function so :meth:`AzureCorpusBackendRegistry.list_corpora`
    (which strips the suffix to recover the corpus_id from a blob name)
    stays in sync with :meth:`AzureCorpusBackendRegistry.backend_for`
    (which constructs the blob name from the corpus_id).
    """
    return f"{corpus_id}{_SQLITE_SUFFIX}"


class AzureCorpusBackendRegistry:
    """:class:`CorpusBackendRegistry` impl backed by an Azure blob container.

    Stores each corpus as a single ``<corpus_id>.sqlite`` blob in the
    container; per-corpus :class:`DatabaseStore` instances get leased
    writes against their blob via :class:`AzureBlobBackend` above.
    Listing walks the container to recover corpus ids.
    """

    def __init__(self, container_url: str, *, managed_identity_client_id: str | None = None) -> None:
        # ``DefaultAzureCredential`` is imported lazily so this module
        # is importable without the Azure SDK installed; constructing
        # the registry is when the cost is paid.
        from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]

        self._container_url = container_url.rstrip("/")
        # When a managed identity client id is supplied, pin
        # ``ManagedIdentityCredential`` to it explicitly. Otherwise the
        # SDK picks ``AZURE_CLIENT_ID`` from the env, which on this
        # service is the OAuth App Registration's client id — not a
        # managed identity — so the MI step of the credential chain
        # fails with "No User Assigned … Managed Identity found for
        # specified ClientId". Passing the kwarg overrides only the MI
        # step; other credentials in the chain (env, workload identity,
        # az CLI for local dev) are unaffected.
        if managed_identity_client_id:
            self._credential = DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)
        else:
            self._credential = DefaultAzureCredential()

    @property
    def source(self) -> str:
        return self._container_url

    def backend_for(self, corpus_id: str) -> StorageBackend:
        return AzureBlobBackend(
            self._container_url,
            _blob_name_for(corpus_id),
            credential=self._credential,
        )

    async def list_corpora(self) -> list[dict[str, Any]]:
        from azure.storage.blob import ContainerClient  # type: ignore[import-not-found]

        client = ContainerClient.from_container_url(self._container_url, credential=self._credential)
        # ``ContainerClient.list_blobs`` is sync; offload to a thread so
        # the event loop stays responsive when a container holds many
        # blobs (and so its HTTP client doesn't block other tools).
        blobs = await asyncio.to_thread(lambda: list(client.list_blobs()))
        out: list[dict[str, Any]] = []
        for blob in blobs:
            name = blob.name
            if not name.endswith(_SQLITE_SUFFIX):
                continue
            corpus_id = name[: -len(_SQLITE_SUFFIX)]
            # Sub-paths within the container aren't part of the
            # corpus_id contract; skip blobs in nested folders rather
            # than surfacing slashes in corpus_ids that nothing else in
            # the system can route to.
            if "/" in corpus_id or not corpus_id:
                continue
            modified = blob.last_modified
            out.append(
                {
                    "corpus_id": corpus_id,
                    "size_bytes": blob.size,
                    "modified": modified.isoformat() if modified is not None else None,
                }
            )
        out.sort(key=lambda r: r["corpus_id"])
        return out


def build_registry() -> AzureCorpusBackendRegistry:
    """Factory entry point referenced by ``CORPUS_BACKEND_REGISTRY_FACTORY``.

    Reads the container URL from ``CORPUS_AZURE_CONTAINER_URL`` and an
    optional managed-identity client id from
    ``CORPUS_AZURE_MANAGED_IDENTITY_CLIENT_ID``. The MI env var is
    needed whenever the host also sets ``AZURE_CLIENT_ID`` to something
    that isn't a managed identity (e.g. the MCP server uses
    ``AZURE_CLIENT_ID`` for OAuth audience validation, which would
    otherwise confuse ``DefaultAzureCredential``'s MI step).
    """
    container_url = os.environ.get(_CONTAINER_URL_ENV)
    if not container_url:
        raise RuntimeError(
            f"{_CONTAINER_URL_ENV} must be set to the blob container URL "
            "(e.g. https://<account>.blob.core.windows.net/<container>) for the "
            "Azure-backed corpus registry."
        )
    return AzureCorpusBackendRegistry(
        container_url,
        managed_identity_client_id=os.environ.get(_MI_CLIENT_ID_ENV),
    )
