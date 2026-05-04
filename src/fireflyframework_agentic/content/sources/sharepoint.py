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

"""SharePoint :class:`ContentSource` backed by Microsoft Graph.

Per the framework's Zero-Trust auth model (issue #98), Core-layer
components do **not** mint tokens. They receive a bearer token from the
caller and validate / use it. This source therefore takes a
``token_provider`` callable and delegates token acquisition (federated
credentials, On-Behalf-Of, managed identity, vault-backed secrets, ...)
to whatever the integrator supplies — see
:mod:`fireflyframework_agentic.security.azure` for built-in helpers.

Incremental sync uses Graph's ``/drives/{id}/root/delta`` endpoint,
returning a stable ``deltaLink`` cursor that the caller persists between
runs via :meth:`commit_delta` after all downstream work has succeeded.
Downloads go through a local cache keyed by item id; etag-based dedupe
makes repeated runs cheap.

Required Graph permission: prefer ``Sites.Selected`` (per-site grant)
over the broader ``Sites.Read.All`` / ``Files.Read.All``. A leaked token
is only as scoped as the consented application permissions.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from fireflyframework_agentic.content.sources.base import RawFile

logger = logging.getLogger(__name__)

GRAPH_HOST = "https://graph.microsoft.com/"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

TokenProvider = Callable[[], Awaitable[str]]
"""Async callable returning a bearer token for Microsoft Graph.

The provider owns caching, refresh, and credential handling. It is
called once per outbound Graph request, so it should cache aggressively.
See :class:`fireflyframework_agentic.security.azure.EntraOBOClient` and
``DefaultAzureCredential`` for typical implementations.
"""


def _assert_graph_url(url: str) -> None:
    """Refuse to send the bearer token to anything that is not Graph.

    Cursors persisted between runs (``delta_file``) and ``@odata.nextLink``
    values returned by Graph are followed verbatim by :meth:`list_changed`.
    A tampered file or a malicious response could otherwise redirect
    requests — and the bearer token they carry — to an attacker host.
    """
    if not url.startswith(GRAPH_HOST):
        raise ValueError(f"refusing to send authenticated request to non-Graph URL: {url!r}")


class SharePointSourceConfig(BaseModel):
    """Configuration for :class:`SharePointSource`.

    Attributes:
        drive_id: Target SharePoint document library (Graph drive) id.
        root_folder: Optional path within the drive used to filter delta
            items. Items whose ``parentReference.path`` does not contain
            this folder are skipped.
        mime_types: Optional whitelist of MIME types. Items not in the
            whitelist are skipped. Empty means accept all.
        cache_dir: Local directory for downloaded raw files.
        delta_file: File where the delta cursor is persisted between runs.
        request_timeout_seconds: Per-request timeout for Graph calls when
            this source owns its ``httpx.AsyncClient``.
    """

    drive_id: str
    root_folder: str | None = None
    mime_types: list[str] = Field(default_factory=list)
    cache_dir: Path
    delta_file: Path
    request_timeout_seconds: float = Field(default=30.0, gt=0.0)


class SharePointSource:
    """Microsoft Graph backed implementation of :class:`ContentSource`.

    Args:
        config: Drive, filtering, and on-disk locations.
        token_provider: Async callable that returns a Graph bearer token.
            Called once per outbound request — the provider owns caching
            and refresh. The framework never sees the underlying
            credential material.
        http_client: Optional pre-built :class:`httpx.AsyncClient`. If
            not supplied, the source owns a client and closes it on
            :meth:`aclose`.
    """

    def __init__(
        self,
        config: SharePointSourceConfig,
        *,
        token_provider: TokenProvider,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._client = http_client or httpx.AsyncClient(
            timeout=config.request_timeout_seconds,
        )
        self._owns_client = http_client is None
        self._pending_cursor: str | None = None
        self._config.cache_dir.mkdir(parents=True, exist_ok=True)
        self._config.delta_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache_root_resolved = self._config.cache_dir.resolve()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> SharePointSource:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # -- HTTP -------------------------------------------------------------

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send an authenticated, non-streaming request to Graph.

        ``url`` MUST be a Graph URL — caller is responsible for asserting
        this before invoking. We assert again defensively.
        """
        _assert_graph_url(url)
        token = await self._token_provider()
        headers = kwargs.pop("headers", {}) or {}
        headers["Authorization"] = f"Bearer {token}"
        # Never follow redirects with the Authorization header attached;
        # cross-origin redirect targets must be handled explicitly.
        response = await self._client.request(method, url, headers=headers, follow_redirects=False, **kwargs)
        response.raise_for_status()
        return response

    # -- delta state ------------------------------------------------------

    async def current_cursor(self) -> str | None:
        if not self._config.delta_file.exists():
            return None
        try:
            data = json.loads(self._config.delta_file.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        cursor = data.get("delta_link")
        if cursor is None:
            return None
        # Persisted cursor is followed as-is by list_changed and carries
        # the bearer token. Treat the file as untrusted input.
        try:
            _assert_graph_url(cursor)
        except ValueError:
            logger.warning("ignoring persisted delta cursor that is not a Graph URL: %r", cursor)
            return None
        return cursor

    async def pending_cursor(self) -> str | None:
        return self._pending_cursor

    async def commit_delta(self, cursor: str) -> None:
        _assert_graph_url(cursor)
        payload = {"delta_link": cursor, "committed_at": datetime.now(UTC).isoformat()}
        target = self._config.delta_file
        tmp = target.with_suffix(target.suffix + ".tmp")
        # Atomic + restricted permissions: the cursor is followed by
        # later runs while bearing a token; another process should not
        # be able to pivot it.
        tmp.write_text(json.dumps(payload, indent=2))
        # Filesystems without POSIX perms (e.g. some Windows mounts)
        # silently ignore chmod; that is acceptable.
        with contextlib.suppress(OSError):
            os.chmod(tmp, 0o600)
        os.replace(tmp, target)

    # -- listing ----------------------------------------------------------

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:
        # Reset pending state so a second pass on the same instance does
        # not inherit a cursor from an earlier run.
        self._pending_cursor = None
        url = since or (f"{GRAPH_ROOT}/drives/{self._config.drive_id}/root/delta")
        _assert_graph_url(url)
        while True:
            response = await self._request("GET", url)
            body = response.json()
            for item in body.get("value", []):
                raw = self._item_to_raw_file(item)
                if raw is not None:
                    yield raw
            next_link = body.get("@odata.nextLink")
            delta_link = body.get("@odata.deltaLink")
            if delta_link is not None:
                # deltaLink will be persisted via commit_delta later;
                # validate now so a malicious response cannot poison
                # the on-disk cursor.
                _assert_graph_url(delta_link)
                self._pending_cursor = delta_link
            if next_link:
                _assert_graph_url(next_link)
                url = next_link
                continue
            break

    def _item_to_raw_file(self, item: dict[str, Any]) -> RawFile | None:
        if "deleted" in item:
            return None
        if "file" not in item:
            return None
        if self._config.root_folder is not None:
            parent_path = (item.get("parentReference") or {}).get("path", "")
            if self._config.root_folder not in parent_path:
                return None
        mime = (item.get("file") or {}).get("mimeType", "")
        if self._config.mime_types and mime not in self._config.mime_types:
            return None
        item_id = item.get("id")
        if not item_id:
            return None
        name = item.get("name", item_id)
        etag = (item.get("eTag") or item.get("file", {}).get("hashes", {}).get("quickXorHash") or "").strip('"')
        parent_path = (item.get("parentReference") or {}).get("path", "")
        return RawFile(
            source_id=f"sharepoint:{item_id}",
            name=name,
            mime_type=mime,
            size_bytes=int(item.get("size") or 0),
            etag=etag,
            fetched_at=datetime.now(UTC),
            metadata={"item_id": item_id, "parent_path": parent_path},
        )

    # -- fetching ---------------------------------------------------------

    async def fetch(self, file: RawFile) -> Path:
        item_id = self._item_id_from_source_id(file.source_id)
        local_path = self._cache_path_for(item_id, file.name)
        meta_path = local_path.with_suffix(local_path.suffix + ".meta.json")

        if local_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                if meta.get("etag") and meta["etag"] == file.etag:
                    logger.debug("cache hit for %s (etag %s)", file.source_id, file.etag)
                    return local_path
            except (OSError, json.JSONDecodeError):
                logger.debug("cache metadata unreadable for %s; refetching content", file.source_id, exc_info=True)

        url = f"{GRAPH_ROOT}/drives/{self._config.drive_id}/items/{item_id}/content"
        # Manual redirect handling: Graph 302s /content to a storage URL.
        # We MUST NOT forward the Authorization header to that host.
        download_url, headers = await self._resolve_download_url(url)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = local_path.with_suffix(local_path.suffix + ".part")
        async with self._client.stream("GET", download_url, headers=headers, follow_redirects=False) as response:
            response.raise_for_status()
            with tmp.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
        tmp.replace(local_path)
        meta_path.write_text(
            json.dumps({"etag": file.etag, "fetched_at": datetime.now(UTC).isoformat()}),
        )
        return local_path

    async def _resolve_download_url(self, url: str) -> tuple[str, dict[str, str]]:
        """Resolve the redirected download URL for ``url``.

        Issues an authenticated request against Graph; if Graph responds
        with a 3xx redirect (typical for ``/content`` -> Azure storage),
        the resulting URL is returned **without** the Authorization
        header, so the bearer token is not leaked to the storage host.
        Otherwise the original Graph URL is returned with auth.
        """
        _assert_graph_url(url)
        token = await self._token_provider()
        auth_headers = {"Authorization": f"Bearer {token}"}
        response = await self._client.request("GET", url, headers=auth_headers, follow_redirects=False)
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise httpx.HTTPStatusError(
                        "redirect without Location",
                        request=response.request,
                        response=response,
                    )
                if not location.startswith("https://"):
                    raise ValueError(f"refusing to follow non-https redirect target: {location!r}")
                return location, {}
            response.raise_for_status()
        finally:
            await response.aclose()
        return url, auth_headers

    # -- helpers ----------------------------------------------------------

    def _cache_path_for(self, item_id: str, name: str) -> Path:
        """Resolve a per-item cache path safely under ``cache_dir``.

        Graph-supplied ``item_id`` and ``name`` are untrusted: callers
        cannot assume they are free of path separators, ``..`` segments,
        or backslashes. We collapse to a single safe segment per
        component and assert the resolved path stays inside the cache
        root before returning it.
        """
        safe_id = _sanitise_segment(item_id) or "unknown-id"
        safe_name = _sanitise_segment(Path(name.replace("\\", "/")).name) or "file"
        candidate = (self._config.cache_dir / safe_id / safe_name).resolve()
        if not _is_relative_to(candidate, self._cache_root_resolved):
            raise ValueError(f"refusing to write outside cache_dir: {candidate} not under {self._cache_root_resolved}")
        return candidate

    @staticmethod
    def _item_id_from_source_id(source_id: str) -> str:
        if not source_id.startswith("sharepoint:"):
            raise ValueError(f"unexpected source_id {source_id!r}")
        return source_id.removeprefix("sharepoint:")


def _sanitise_segment(value: str) -> str:
    """Reduce a string to a safe single-path-segment identifier.

    Keeps alphanumerics, dot, underscore, hyphen; collapses everything
    else (including ``/``, ``\\``, NUL, control chars) to underscore.
    A leading-dot-only result (``.`` or ``..``) is rejected to prevent
    cwd / parent references — the caller substitutes a default.
    """
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in value)
    if cleaned in {"", ".", ".."}:
        return ""
    return cleaned


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
