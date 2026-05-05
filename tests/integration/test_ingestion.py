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

"""End-to-end integration tests for the ingestion pipeline.

These tests run the real :class:`SharePointSource` against a SharePoint
test site provisioned in an isolated tenant. They are skipped unless the
required environment variables are set, so contributors without the test
infra can still run the unit suite.

Required environment variables:

* ``FIREFLY_TEST_TENANT_ID``
* ``FIREFLY_TEST_CLIENT_ID``
* ``FIREFLY_TEST_CLIENT_SECRET``
* ``FIREFLY_TEST_DRIVE_ID``

See ``tests/integration/SETUP.md`` for the full reference setup
(``rg-firefly-test``, ``kv-firefly-test``, App Registration with
``Sites.Selected``, federated credential).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

REQUIRED_ENV = (
    "FIREFLY_TEST_TENANT_ID",
    "FIREFLY_TEST_CLIENT_ID",
    "FIREFLY_TEST_CLIENT_SECRET",
    "FIREFLY_TEST_DRIVE_ID",
)


def _missing_env() -> list[str]:
    return [k for k in REQUIRED_ENV if not os.environ.get(k)]


pytestmark = pytest.mark.skipif(
    bool(_missing_env()),
    reason=(
        "integration tests require the firefly test infra; "
        f"missing env vars: {_missing_env()}. "
        "See tests/integration/SETUP.md."
    ),
)


@pytest.fixture
def integration_config(tmp_path: Path):
    from fireflyframework_agentic.ingestion.adapters.sources import (
        SharePointSourceConfig,
    )

    return SharePointSourceConfig(
        tenant_id_secret="FIREFLY_TEST_TENANT_ID",
        client_id_secret="FIREFLY_TEST_CLIENT_ID",
        client_secret_secret="FIREFLY_TEST_CLIENT_SECRET",
        drive_id=os.environ["FIREFLY_TEST_DRIVE_ID"],
        cache_dir=tmp_path / "cache",
        delta_file=tmp_path / "delta.json",
    )


async def test_real_sharepoint_round_trip(integration_config):
    """Lists changed items, fetches one, asserts it lands in the cache.

    The test site is expected to contain at least one CSV with synthetic
    data. The conftest in this folder uploads a fresh fixture per run,
    keyed by ``runs/<test-id>/`` to keep tests isolated.
    """
    from fireflyframework_agentic.ingestion.adapters import EnvSecretsProvider
    from fireflyframework_agentic.ingestion.adapters.sources import SharePointSource

    secrets = EnvSecretsProvider()
    async with SharePointSource(integration_config, secrets) as source:
        files = []
        async for raw in source.list_changed(None):
            files.append(raw)
            if len(files) >= 1:
                break
        assert files, "test site should contain at least one item"
        local = await source.fetch(files[0])
        assert local.exists()
        assert local.stat().st_size > 0
        assert files[0].fetched_at <= datetime.now(UTC)
