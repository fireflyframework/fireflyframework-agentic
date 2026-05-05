# Copyright 2026 Firefly Software Solutions Inc
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

"""SharePoint data source backed by Microsoft Graph.

Implements :class:`DataSourcePort` against a single SharePoint document
library (drive). Authentication is OAuth2 client-credentials (app-only).
Incremental sync uses Graph's ``/drives/{id}/root/delta`` endpoint, which
returns a stable ``deltaLink`` cursor we persist to disk between runs.

Downloads go through a local cache keyed by item id; etag-based dedupe
makes repeated runs cheap.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from fireflyframework_agentic.ingestion.domain import RawFile
from fireflyframework_agentic.ingestion.ports import SecretsProvider

logger = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
TOKEN_LEEWAY_SECONDS = 60


class SharePointSourceConfig(BaseModel):
    """Configuration for :class:`SharePointSource`.

    Attributes:
        tenant_id_secret: Secret key (resolved through :class:`SecretsProvider`)
            holding the Azure AD tenant id.
        client_id_secret: Secret key holding the App Registration client id.
        client_secret_secret: Secret key holding the client secret.
        drive_id: Target SharePoint document library id.
        root_folder: Optional path within the drive used to filter delta items.
            Items whose ``parentReference.path`` does not start with this
            folder are skipped.
        mime_types: Optional whitelist of MIME types. Items not in the
            whitelist are skipped.
        cache_dir: Local directory for downloaded raw files.
        delta_file: File where the delta cursor is persisted between runs.
        request_timeout_seconds: Per-request timeout for Graph calls.
    """

    tenant_id_secret: str
    client_id_secret: str
    client_secret_secret: str
    drive_id: str
    root_folder: str | None = None
    mime_types: list[str] = Field(default_factory=list)
    cache_dir: Path
    delta_file: Path
    request_timeout_seconds: float = 30.0


class _Token(BaseModel):
    access_token: str
    expires_at: float


class SharePointSource:
    """Microsoft Graph backed implementation of :class:`DataSourcePort`."""

    def __init__(
        self,
        config: SharePointSourceConfig,
        secrets: SecretsProvider,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._client = http_client or httpx.AsyncClient(timeout=config.request_timeout_seconds)
        self._owns_client = http_client is None
        self._token: _Token | None = None
        self._config.cache_dir.mkdir(parents=True, exist_ok=True)
        self._config.delta_file.parent.mkdir(parents=True, exist_ok=True)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> SharePointSource:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # -- auth -------------------------------------------------------------

    async def _get_token(self) -> str:
        now = time.time()
        if self._token is not None and self._token.expires_at - TOKEN_LEEWAY_SECONDS > now:
            return self._token.access_token

        tenant_id = self._secrets.get(self._config.tenant_id_secret)
        client_id = self._secrets.get(self._config.client_id_secret)
        client_secret = self._secrets.get(self._config.client_secret_secret)

        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        response = await self._client.post(url, data=data)
        response.raise_for_status()
        body = response.json()
        self._token = _Token(
            access_token=body["access_token"],
            expires_at=now + float(body["expires_in"]),
        )
        return self._token.access_token

    async def _request(
        self,
        method: str,
        url: str,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        token = await self._get_token()
        headers = kwargs.pop("headers", {}) or {}
        headers["Authorization"] = f"Bearer {token}"
        if stream:
            follow_redirects = kwargs.pop("follow_redirects", False)
            request = self._client.build_request(method, url, headers=headers, **kwargs)
            response = await self._client.send(request, stream=True, follow_redirects=follow_redirects)
        else:
            response = await self._client.request(method, url, headers=headers, **kwargs)
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
        return data.get("delta_link")

    async def commit_delta(self, cursor: str) -> None:
        payload = {"delta_link": cursor, "committed_at": datetime.now(UTC).isoformat()}
        self._config.delta_file.write_text(json.dumps(payload, indent=2))

    # -- listing ----------------------------------------------------------

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:
        url = since or (f"{GRAPH_ROOT}/drives/{self._config.drive_id}/root/delta")
        delta_link: str | None = None
        while True:
            response = await self._request("GET", url)
            body = response.json()
            for item in body.get("value", []):
                raw = self._item_to_raw_file(item)
                if raw is not None:
                    yield raw
            next_link = body.get("@odata.nextLink")
            delta_link = body.get("@odata.deltaLink") or delta_link
            if next_link:
                url = next_link
                continue
            break
        if delta_link is not None:
            await self.commit_delta(delta_link)

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
        return RawFile(
            source_id=f"sharepoint:{item_id}",
            name=name,
            mime_type=mime,
            size_bytes=int(item.get("size") or 0),
            etag=etag,
            fetched_at=datetime.now(UTC),
            local_path=self._cache_path_for(item_id, name),
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
                pass

        url = f"{GRAPH_ROOT}/drives/{self._config.drive_id}/items/{item_id}/content"
        response = await self._request("GET", url, stream=True, follow_redirects=True)
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = local_path.with_suffix(local_path.suffix + ".part")
            with tmp.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
            tmp.replace(local_path)
        finally:
            await response.aclose()
        meta_path.write_text(json.dumps({"etag": file.etag, "fetched_at": datetime.now(UTC).isoformat()}))
        return local_path

    # -- helpers ----------------------------------------------------------

    def _cache_path_for(self, item_id: str, name: str) -> Path:
        return self._config.cache_dir / item_id / name

    @staticmethod
    def _item_id_from_source_id(source_id: str) -> str:
        if not source_id.startswith("sharepoint:"):
            raise ValueError(f"unexpected source_id {source_id!r}")
        return source_id.removeprefix("sharepoint:")
