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
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from examples.corpus_search.sharepoint_source import (
    SharePointSource,
    SharePointSourceConfig,
)
from fireflyframework_agentic.content.sources import (
    ContentSource,
    RawFile,
)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "drive-1"


def _config(tmp_path: Path) -> SharePointSourceConfig:
    return SharePointSourceConfig(
        drive_id=DRIVE_ID,
        cache_dir=tmp_path / "cache",
        delta_file=tmp_path / "delta.json",
    )


def _token_provider(token: str = "fake-token"):
    async def _provider() -> str:
        return token

    return _provider


def _counting_token_provider(token: str = "fake-token"):
    calls = [0]

    async def _provider() -> str:
        calls[0] += 1
        return token

    return _provider, calls


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
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
    assert isinstance(source, ContentSource)


async def test_token_provider_is_called_per_request(tmp_path: Path) -> None:
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
            delta_url: httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.deltaLink": (f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=cursor"),
                },
            ),
        }
    )
    provider, calls = _counting_token_provider()
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=provider, http_client=client)
        async for _ in source.list_changed(None):
            pass
    assert calls[0] >= 1


async def test_authorization_header_is_set_from_provider(tmp_path: Path) -> None:
    seen_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("Authorization", ""))
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.deltaLink": f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=c",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(
            _config(tmp_path),
            token_provider=_token_provider("supplied-token"),
            http_client=client,
        )
        async for _ in source.list_changed(None):
            pass
    assert seen_headers and all(h == "Bearer supplied-token" for h in seen_headers)


async def test_list_changed_yields_files_and_does_not_auto_commit(tmp_path: Path) -> None:
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    delta_cursor = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=cursor-1"
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
            delta_url: httpx.Response(
                200,
                json={"value": items, "@odata.deltaLink": delta_cursor},
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        result = [f async for f in source.list_changed(None)]

        assert len(result) == 1
        assert result[0].name == "Q1.csv"
        assert result[0].source_id == "sharepoint:item-1"
        assert result[0].mime_type == "text/csv"
        assert result[0].etag == "abc"
        assert result[0].metadata["item_id"] == "item-1"
        assert result[0].metadata["parent_path"] == "/drives/x/root:/Sales"

        assert not (tmp_path / "delta.json").exists()
        assert await source.pending_cursor() == delta_cursor


async def test_pending_cursor_returns_none_before_iteration(tmp_path: Path) -> None:
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        assert await source.pending_cursor() is None


async def test_list_changed_paginates_via_next_link(tmp_path: Path) -> None:
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    next_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=page2"
    final_cursor = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=final"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
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
                    "@odata.deltaLink": final_cursor,
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["a.csv", "b.csv"]
    assert await source.pending_cursor() == final_cursor


async def test_list_changed_filters_by_root_folder(tmp_path: Path) -> None:
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
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
                    "@odata.deltaLink": (f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=d"),
                },
            ),
        }
    )
    cfg = _config(tmp_path).model_copy(update={"root_folder": "/Sales"})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, token_provider=_token_provider(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["in.csv"]


async def test_list_changed_filters_by_mime_type(tmp_path: Path) -> None:
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
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
                    "@odata.deltaLink": (f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=d"),
                },
            ),
        }
    )
    cfg = _config(tmp_path).model_copy(update={"mime_types": ["text/csv"]})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, token_provider=_token_provider(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert [r.name for r in result] == ["ok.csv"]


async def test_etag_falls_back_to_quick_xor_hash(tmp_path: Path) -> None:
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
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
                    "@odata.deltaLink": (f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=d"),
                },
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        result = [f async for f in source.list_changed(None)]
    assert result[0].etag == "fallback-hash"


async def test_fetch_downloads_directly_when_graph_returns_200(tmp_path: Path) -> None:
    content_url_prefix = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/items/item-1/content"
    transport = _make_handler(
        {
            content_url_prefix: httpx.Response(200, content=b"id,name\n1,Alpha\n"),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
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


async def test_fetch_strips_authorization_on_redirect(tmp_path: Path) -> None:
    """Graph 302s /content to a storage URL; bearer token must NOT be forwarded."""
    content_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/items/item-1/content"
    storage_url = "https://eu-storage.example.com/blob/item-1?sig=opaque"
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append((url, request.headers.get("Authorization", "")))
        if url == content_url:
            return httpx.Response(302, headers={"Location": storage_url})
        if url == storage_url:
            return httpx.Response(200, content=b"binary-payload")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        raw = RawFile(
            source_id="sharepoint:item-1",
            name="Q1.csv",
            mime_type="text/csv",
            size_bytes=14,
            etag="v1",
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        local = await source.fetch(raw)
    assert local.read_bytes() == b"binary-payload"
    # First call (Graph) carried the bearer token; the storage URL did not.
    auth_for_graph = next(auth for url, auth in seen if url == content_url)
    auth_for_storage = next(auth for url, auth in seen if url == storage_url)
    assert auth_for_graph.startswith("Bearer ")
    assert auth_for_storage == ""


async def test_fetch_refuses_non_https_redirect(tmp_path: Path) -> None:
    content_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/items/item-1/content"
    transport = _make_handler(
        {
            content_url: httpx.Response(302, headers={"Location": "http://attacker.example.com/leak"}),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        raw = RawFile(
            source_id="sharepoint:item-1",
            name="Q1.csv",
            mime_type="text/csv",
            size_bytes=0,
            etag="v1",
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(ValueError, match="non-https redirect"):
            await source.fetch(raw)


async def test_fetch_uses_cache_on_etag_match(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    target = cfg.cache_dir / "item-1" / "Q1.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"cached-content")
    target.with_suffix(target.suffix + ".meta.json").write_text(json.dumps({"etag": "v1"}))

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500, text="should not be called")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, token_provider=_token_provider(), http_client=client)
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
    assert calls == []


async def test_fetch_rejects_unprefixed_source_id(tmp_path: Path) -> None:
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
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
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        assert await source.current_cursor() is None


async def test_current_cursor_reads_persisted_value(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.delta_file.parent.mkdir(parents=True, exist_ok=True)
    cursor_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=saved"
    cfg.delta_file.write_text(json.dumps({"delta_link": cursor_url}))
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, token_provider=_token_provider(), http_client=client)
        assert await source.current_cursor() == cursor_url


async def test_current_cursor_rejects_non_graph_url(tmp_path: Path) -> None:
    """Tampered delta file pointing at attacker host must NOT be returned."""
    cfg = _config(tmp_path)
    cfg.delta_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.delta_file.write_text(json.dumps({"delta_link": "https://attacker.example.com/steal-token"}))
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, token_provider=_token_provider(), http_client=client)
        assert await source.current_cursor() is None


async def test_list_changed_rejects_non_graph_since_cursor(tmp_path: Path) -> None:
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        with pytest.raises(ValueError, match="non-Graph URL"):
            async for _ in source.list_changed("https://attacker.example.com/page"):
                pass


async def test_list_changed_rejects_non_graph_next_link(tmp_path: Path) -> None:
    delta_url = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta"
    transport = _make_handler(
        {
            delta_url: httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": "https://attacker.example.com/page2",
                },
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        with pytest.raises(ValueError, match="non-Graph URL"):
            async for _ in source.list_changed(None):
                pass


async def test_commit_delta_rejects_non_graph_cursor(tmp_path: Path) -> None:
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(_config(tmp_path), token_provider=_token_provider(), http_client=client)
        with pytest.raises(ValueError, match="non-Graph URL"):
            await source.commit_delta("https://attacker.example.com/cursor")


async def test_commit_delta_writes_atomically_with_restricted_perms(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cursor = f"{GRAPH_ROOT}/drives/{DRIVE_ID}/root/delta?token=c"
    transport = _make_handler({})
    async with httpx.AsyncClient(transport=transport) as client:
        source = SharePointSource(cfg, token_provider=_token_provider(), http_client=client)
        await source.commit_delta(cursor)
    payload = json.loads(cfg.delta_file.read_text())
    assert payload["delta_link"] == cursor
    assert "committed_at" in payload
    # No leftover .tmp file.
    assert not cfg.delta_file.with_suffix(cfg.delta_file.suffix + ".tmp").exists()
    if os.name == "posix":
        mode = stat.S_IMODE(cfg.delta_file.stat().st_mode)
        assert mode == 0o600


# --- adversarial cache-path tests ----------------------------------------


@pytest.mark.parametrize(
    ("item_id", "name"),
    [
        ("..", "evil.txt"),
        ("../../etc", "passwd"),
        ("ok-id", ".."),
        ("ok-id", "../../../escape"),
        ("ok-id", "a/b/c.txt"),
        ("ok-id", "a\\b\\c.txt"),
        ("ok-id", "foo\x00bar"),
        ("ok-id", "."),
        ("", ""),
    ],
)
def test_cache_path_stays_under_cache_dir(tmp_path: Path, item_id: str, name: str) -> None:
    cfg = _config(tmp_path)
    transport = _make_handler({})
    client = httpx.AsyncClient(transport=transport)
    source = SharePointSource(cfg, token_provider=_token_provider(), http_client=client)
    resolved = source._cache_path_for(item_id, name)
    cache_root = cfg.cache_dir.resolve()
    assert resolved.is_relative_to(cache_root), f"{resolved} escaped {cache_root}"
