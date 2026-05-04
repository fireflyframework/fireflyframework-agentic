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

"""Unit tests for SharePointSource via httpx.MockTransport."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from fireflyframework_agentic.content.sources import (
    ContentSource,
    RawFile,
    SharePointSource,
    SharePointSourceConfig,
)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "drive-1"


def _config(tmp_path: Path) -> SharePointSourceConfig:
    return SharePointSourceConfig(
        drive_id=DRIVE_ID,
        cache_dir=tmp_path / "cache",
        delta_file=tmp_path / "delta.json",
    )


def _creds() -> dict[str, str]:
    return {
        "tenant_id": "tenant-1",
        "client_id": "client-1",
        "client_secret": "client-secret-1",
    }


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"access_token": "fake-token", "expires_in": 3600, "token_type": "Bearer"},
    )


def _make_handler(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, response in routes.items():
            if url.startswith(prefix):
                return response
        return httpx.Response(404, json={"error": f"no mock for {url}"})

    return httpx.MockTransport(handler)


async def test_sharepoint_source_satisfies_protocol(tmp_path: Path) -> None:
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
    assert isinstance(source, ContentSource)


async def test_acquires_token_on_first_request(tmp_path: Path) -> None:
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
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        async for _ in source.list_changed(None):
            pass
        assert source._token is not None
        assert source._token.access_token == "fake-token"


async def test_list_changed_yields_files_and_does_not_auto_commit(tmp_path: Path) -> None:
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
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        result = [f async for f in source.list_changed(None)]

        assert len(result) == 1
        assert result[0].name == "Q1.csv"
        assert result[0].source_id == "sharepoint:item-1"
        assert result[0].mime_type == "text/csv"
        assert result[0].etag == "abc"
        assert result[0].metadata["item_id"] == "item-1"
        assert result[0].metadata["parent_path"] == "/drives/x/root:/Sales"

        # Regression: list_changed must NOT auto-commit (PR #84 did, we don't).
        assert not (tmp_path / "delta.json").exists()
        assert await source.pending_cursor() == "https://example/delta-1"


async def test_pending_cursor_returns_none_before_iteration(tmp_path: Path) -> None:
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        assert await source.pending_cursor() is None


async def test_list_changed_paginates_via_next_link(tmp_path: Path) -> None:
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
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["a.csv", "b.csv"]
    assert await source.pending_cursor() == "delta-final"


async def test_list_changed_filters_by_root_folder(tmp_path: Path) -> None:
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
    cfg = _config(tmp_path).model_copy(update={"root_folder": "/Sales"})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, **_creds(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["in.csv"]


async def test_list_changed_filters_by_mime_type(tmp_path: Path) -> None:
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
    cfg = _config(tmp_path).model_copy(update={"mime_types": ["text/csv"]})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, **_creds(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["ok.csv"]


async def test_etag_falls_back_to_quick_xor_hash(tmp_path: Path) -> None:
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": _token_response(),
            delta_url: httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "i",
                            "name": "x.csv",
                            "size": 1,
                            "file": {
                                "mimeType": "text/csv",
                                "hashes": {"quickXorHash": "fallback-hash"},
                            },
                            "parentReference": {"path": "/x"},
                        }
                    ],
                    "@odata.deltaLink": "d",
                },
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert result[0].etag == "fallback-hash"


async def test_fetch_downloads_and_caches(tmp_path: Path) -> None:
    content_url_prefix = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/items/item-1/content"
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": _token_response(),
            content_url_prefix: httpx.Response(200, content=b"id,name\n1,Alpha\n"),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        raw = RawFile(
            source_id="sharepoint:item-1",
            name="Q1.csv",
            mime_type="text/csv",
            size_bytes=16,
            etag="v1",
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        local = await source.fetch(raw)
    assert local.read_bytes() == b"id,name\n1,Alpha\n"
    meta = json.loads((local.with_suffix(local.suffix + ".meta.json")).read_text())
    assert meta["etag"] == "v1"


async def test_fetch_uses_cache_on_etag_match(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    target = cfg.cache_dir / "item-1" / "Q1.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
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
        source = SharePointSource(cfg, **_creds(), http_client=client)
        raw = RawFile(
            source_id="sharepoint:item-1",
            name="Q1.csv",
            mime_type="text/csv",
            size_bytes=14,
            etag="v1",
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        local = await source.fetch(raw)
    assert local.read_bytes() == b"cached-content"
    assert all("/items/item-1/content" not in c for c in calls)


async def test_fetch_rejects_unprefixed_source_id(tmp_path: Path) -> None:
    transport = _make_handler({"https://login.microsoftonline.com/": _token_response()})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        raw = RawFile(
            source_id="s3:foo",
            name="x",
            mime_type="text/csv",
            size_bytes=0,
            etag="e",
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(ValueError, match="unexpected source_id"):
            await source.fetch(raw)


async def test_current_cursor_returns_none_when_missing(tmp_path: Path) -> None:
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        assert await source.current_cursor() is None


async def test_current_cursor_reads_persisted_value(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.delta_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.delta_file.write_text(json.dumps({"delta_link": "saved-cursor"}))
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, **_creds(), http_client=client)
        assert await source.current_cursor() == "saved-cursor"


async def test_commit_delta_writes_payload(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, **_creds(), http_client=client)
        await source.commit_delta("the-cursor")
    payload = json.loads(cfg.delta_file.read_text())
    assert payload["delta_link"] == "the-cursor"
    assert "committed_at" in payload


async def test_token_is_reused_across_calls(tmp_path: Path) -> None:
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
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        async for _ in source.list_changed(None):
            pass
        async for _ in source.list_changed(None):
            pass
    assert token_calls == 1


async def test_raises_for_status_on_token_failure(tmp_path: Path) -> None:
    transport = _make_handler(
        {
            "https://login.microsoftonline.com/": httpx.Response(
                401,
                json={"error": "unauthorized"},
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), **_creds(), http_client=client)
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in source.list_changed(None):
                pass
