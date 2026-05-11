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

"""AzureBlobBackend tests against Azurite.

Azurite is sourced via the session-scoped ``azurite_connection_string``
fixture in ``tests/conftest.py``: it uses ``AZURITE_CONNECTION_STRING``
when set, otherwise auto-starts an Azurite container if Docker is
available, otherwise skips.
"""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.nightly]


@pytest.fixture
def container_url(azurite_connection_string: str, tmp_path: Path):
    from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]

    svc = BlobServiceClient.from_connection_string(azurite_connection_string)
    name = f"dbstore-{uuid.uuid4().hex}"
    svc.create_container(name)
    yield f"{svc.url}{name}"
    with contextlib.suppress(Exception):
        svc.delete_container(name)


@pytest.fixture
def credential(azurite_connection_string: str) -> object:
    from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]

    svc = BlobServiceClient.from_connection_string(azurite_connection_string)
    return svc.credential


async def test_round_trip_upload_download(container_url, credential, tmp_path: Path) -> None:
    from examples.corpus_search.azure_backend import AzureBlobBackend

    backend = AzureBlobBackend(container_url, "x.sqlite", credential=credential)
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello-azurite")
    meta = await backend.upload(src)
    assert meta.exists
    dest = tmp_path / "dst.bin"
    await backend.download(dest)
    assert dest.read_bytes() == b"hello-azurite"


async def test_lease_acquire_release(container_url, credential, tmp_path: Path) -> None:
    from examples.corpus_search.azure_backend import AzureBlobBackend

    backend = AzureBlobBackend(container_url, "y.sqlite", credential=credential)
    src = tmp_path / "src.bin"
    src.write_bytes(b"v")
    await backend.upload(src)
    token = await backend.acquire_lock(timeout=5.0)
    await backend.release_lock(token)


async def test_database_store_e2e_against_azurite(container_url, credential, tmp_path: Path) -> None:
    import sqlite3

    from examples.corpus_search.azure_backend import AzureBlobBackend
    from fireflyframework_agentic.storage import DatabaseStore

    backend = AzureBlobBackend(container_url, "e2e.sqlite", credential=credential)
    store = DatabaseStore(backend, store_id="azurite-e2e", cache_root=tmp_path / "cache")
    async with store.for_write() as session:
        conn = sqlite3.connect(session.path)
        conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('hi')")
        conn.commit()
        conn.close()

    reader_store = DatabaseStore(backend, store_id="azurite-e2e-2", cache_root=tmp_path / "cache2")
    path, _ = await reader_store.ensure_fresh()
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT v FROM t").fetchall()
    conn.close()
    assert rows == [("hi",)]
