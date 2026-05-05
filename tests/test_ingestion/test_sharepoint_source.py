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

"""Tests for SharePointSource using httpx.MockTransport.

The Microsoft Graph endpoints are stubbed so the adapter can be exercised
end-to-end (auth -> list -> fetch -> delta) without a real tenant. Real
integration tests live in tests/integration/test_ingestion.py and run only
when the firefly test infra is provisioned.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from fireflyframework_agentic.ingestion.adapters import EnvSecretsProvider
from fireflyframework_agentic.ingestion.adapters.sources import (
    SharePointSource,
    SharePointSourceConfig,
)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "drive-1"


def _config(tmp_path: Path) -> SharePointSourceConfig:
    return SharePointSourceConfig(
        tenant_id_secret="TENANT",
        client_id_secret="CLIENT",
        client_secret_secret="SECRET",
        drive_id=DRIVE_ID,
        cache_dir=tmp_path / "cache",
        delta_file=tmp_path / "delta.json",
    )


def _secrets() -> EnvSecretsProvider:
    return EnvSecretsProvider({"TENANT": "tenant-1", "CLIENT": "client-1", "SECRET": "client-secret-1"})


def _make_handler(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    """Build a MockTransport that dispatches by request URL."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, response in routes.items():
            if url.startswith(prefix):
                return response
        return httpx.Response(404, json={"error": f"no mock for {url}"})

    return httpx.MockTransport(handler)


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"access_token": "fake-token", "expires_in": 3600, "token_type": "Bearer"},
    )


async def test_acquires_token_on_first_request(tmp_path: Path):
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": _token_response(),
            delta_url: httpx.Response(
                200,
                json={"value": [], "@odata.deltaLink": "https://example/delta-cursor"},
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), _secrets(), http_client=client)
        # consume the iterator
        async for _ in source.list_changed(None):
            pass
        # token should be cached
        assert source._token is not None
        assert source._token.access_token == "fake-token"


async def test_list_changed_yields_files_and_persists_delta(tmp_path: Path):
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    items = [
        {
            "id": "item-1",
            "name": "Q1.csv",
            "size": 12,
            "eTag": '"abc"',
            "file": {"mimeType": "text/csv"},
            "parentReference": {"path": "/drives/x/root:/Sales"},
        },
        {"id": "item-2", "name": "ignored", "deleted": {"state": "deleted"}},
        {
            "id": "item-3",
            "name": "folder",
            "size": 0,
            "parentReference": {"path": "/drives/x/root:/Sales"},
            # no "file" -> not a file (folder)
        },
    ]
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": _token_response(),
            delta_url: httpx.Response(
                200,
                json={"value": items, "@odata.deltaLink": "https://example/delta-1"},
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), _secrets(), http_client=client)
        result = [f async for f in source.list_changed(None)]

    assert len(result) == 1
    assert result[0].name == "Q1.csv"
    assert result[0].source_id == "sharepoint:item-1"
    assert result[0].mime_type == "text/csv"
    assert result[0].etag == "abc"

    delta_data = json.loads((tmp_path / "delta.json").read_text())
    assert delta_data["delta_link"] == "https://example/delta-1"


async def test_list_changed_paginates_via_next_link(tmp_path: Path):
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    next_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=page2"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://login.microsoftonline.com/"):
            return _token_response()
        if url == delta_url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "item-1",
                            "name": "a.csv",
                            "size": 1,
                            "eTag": '"e1"',
                            "file": {"mimeType": "text/csv"},
                            "parentReference": {"path": "/x"},
                        }
                    ],
                    "@odata.nextLink": next_url,
                },
            )
        if url == next_url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "item-2",
                            "name": "b.csv",
                            "size": 1,
                            "eTag": '"e2"',
                            "file": {"mimeType": "text/csv"},
                            "parentReference": {"path": "/x"},
                        }
                    ],
                    "@odata.deltaLink": "delta-final",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), _secrets(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["a.csv", "b.csv"]
    assert json.loads((tmp_path / "delta.json").read_text())["delta_link"] == "delta-final"


async def test_list_changed_filters_by_root_folder(tmp_path: Path):
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": _token_response(),
            delta_url: httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "in",
                            "name": "in.csv",
                            "size": 1,
                            "file": {"mimeType": "text/csv"},
                            "parentReference": {"path": "/drives/x/root:/Sales/Q1"},
                        },
                        {
                            "id": "out",
                            "name": "out.csv",
                            "size": 1,
                            "file": {"mimeType": "text/csv"},
                            "parentReference": {"path": "/drives/x/root:/Other"},
                        },
                    ],
                    "@odata.deltaLink": "d",
                },
            ),
        }
    )
    cfg = _config(tmp_path)
    cfg = cfg.model_copy(update={"root_folder": "/Sales"})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, _secrets(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["in.csv"]


async def test_list_changed_filters_by_mime_type(tmp_path: Path):
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": _token_response(),
            delta_url: httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "csv",
                            "name": "ok.csv",
                            "size": 1,
                            "file": {"mimeType": "text/csv"},
                            "parentReference": {"path": "/x"},
                        },
                        {
                            "id": "doc",
                            "name": "no.docx",
                            "size": 1,
                            "file": {"mimeType": "application/word"},
                            "parentReference": {"path": "/x"},
                        },
                    ],
                    "@odata.deltaLink": "d",
                },
            ),
        }
    )
    cfg = _config(tmp_path)
    cfg = cfg.model_copy(update={"mime_types": ["text/csv"]})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, _secrets(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["ok.csv"]


async def test_fetch_downloads_and_caches(tmp_path: Path):
    content_url_prefix = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/items/item-1/content"
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": _token_response(),
            content_url_prefix: httpx.Response(200, content=b"id,name\n1,Alpha\n"),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), _secrets(), http_client=client)
        from datetime import datetime as _dt

        from fireflyframework_agentic.ingestion.domain import RawFile

        raw = RawFile(
            source_id="sharepoint:item-1",
            name="Q1.csv",
            mime_type="text/csv",
            size_bytes=16,
            etag="v1",
            fetched_at=_dt(2026, 1, 1),
            local_path=tmp_path / "cache" / "item-1" / "Q1.csv",
        )
        local = await source.fetch(raw)
    assert local.read_bytes() == b"id,name\n1,Alpha\n"
    meta = json.loads((local.with_suffix(local.suffix + ".meta.json")).read_text())
    assert meta["etag"] == "v1"


async def test_fetch_uses_cache_on_etag_match(tmp_path: Path):
    """Second fetch with the same etag does NOT issue a content GET."""
    cfg = _config(tmp_path)
    target = cfg.cache_dir / "item-1" / "Q1.csv"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"cached-content")
    target.with_suffix(target.suffix + ".meta.json").write_text(json.dumps({"etag": "v1"}))

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.startswith("https://login.microsoftonline.com/"):
            return _token_response()
        return httpx.Response(500, text="should not be called")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, _secrets(), http_client=client)
        from datetime import datetime as _dt

        from fireflyframework_agentic.ingestion.domain import RawFile

        raw = RawFile(
            source_id="sharepoint:item-1",
            name="Q1.csv",
            etag="v1",
            fetched_at=_dt(2026, 1, 1),
            local_path=target,
        )
        local = await source.fetch(raw)
    assert local.read_bytes() == b"cached-content"
    # Only the auth call should have happened (or zero, since the token was
    # not yet acquired); but no /drives/.../content call.
    assert all("/items/item-1/content" not in c for c in calls)


async def test_current_cursor_returns_none_when_missing(tmp_path: Path):
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), _secrets(), http_client=client)
        assert await source.current_cursor() is None


async def test_current_cursor_reads_persisted_value(tmp_path: Path):
    cfg = _config(tmp_path)
    cfg.delta_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.delta_file.write_text(json.dumps({"delta_link": "saved-cursor"}))
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, _secrets(), http_client=client)
        assert await source.current_cursor() == "saved-cursor"


async def test_token_is_reused_across_calls(tmp_path: Path):
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        url = str(request.url)
        if url.startswith("https://login.microsoftonline.com/"):
            token_calls += 1
            return _token_response()
        if url.startswith(delta_url):
            return httpx.Response(200, json={"value": [], "@odata.deltaLink": "d"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), _secrets(), http_client=client)
        async for _ in source.list_changed(None):
            pass
        async for _ in source.list_changed(None):
            pass
    assert token_calls == 1


async def test_raises_for_status_on_token_failure(tmp_path: Path):
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": httpx.Response(401, json={"error": "unauthorized"}),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), _secrets(), http_client=client)
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in source.list_changed(None):
                pass
