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

"""Shared test fixtures for the fireflyframework-agentic test suite."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _clear_registries():
    """Reset global registries between tests to avoid cross-test contamination."""
    from fireflyframework_agentic.agents.registry import agent_registry
    from fireflyframework_agentic.reasoning.registry import reasoning_registry
    from fireflyframework_agentic.tools.registry import tool_registry

    agent_registry._agents.clear()
    tool_registry.clear()
    reasoning_registry.clear()
    yield
    agent_registry._agents.clear()
    tool_registry.clear()
    reasoning_registry.clear()


# Azurite dev key — public well-known constant from Microsoft's docs.
# Not a secret; identical across every Azurite installation.
_AZURITE_DEV_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


def _build_azurite_conn_string(host: str, port: int) -> str:
    return (
        "DefaultEndpointsProtocol=http;"
        "AccountName=devstoreaccount1;"
        f"AccountKey={_AZURITE_DEV_KEY};"
        f"BlobEndpoint=http://{host}:{port}/devstoreaccount1;"
    )


@pytest.fixture(scope="session")
def azurite_connection_string() -> Iterator[str]:
    """Yield an Azurite connection string for the test session.

    Resolution order:
    1. ``AZURITE_CONNECTION_STRING`` env var — used as-is (CI service
       container, manual ``docker run``, or shared instance).
    2. Else if ``docker`` is on PATH, start a one-shot Azurite container
       on a random host port for the test session and tear it down on
       exit.
    3. Else ``pytest.skip`` — Azurite is unavailable.

    Tests that need Azurite request this fixture lazily via
    ``request.getfixturevalue(...)`` so non-Azurite parametrisations
    (e.g. ``"local"``) still run on machines without Docker.
    """
    env_str = os.environ.get("AZURITE_CONNECTION_STRING")
    if env_str:
        yield env_str
        return

    if not shutil.which("docker"):
        pytest.skip("Azurite not configured: set AZURITE_CONNECTION_STRING or install Docker")

    container_id: str | None = None
    try:
        container_id = (
            subprocess.check_output(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "-P",
                    "mcr.microsoft.com/azure-storage/azurite",
                    "azurite-blob",
                    "--blobHost",
                    "0.0.0.0",
                ],
                stderr=subprocess.STDOUT,
            )
            .decode()
            .strip()
        )

        port_line = subprocess.check_output(["docker", "port", container_id, "10000/tcp"]).decode().splitlines()[0]
        # Lines look like "0.0.0.0:32768" — take the host port from the right.
        port = int(port_line.rsplit(":", 1)[-1])
        conn_str = _build_azurite_conn_string("127.0.0.1", port)

        # Wait up to 15s for Azurite to accept connections.
        from azure.storage.blob import BlobServiceClient

        deadline = time.monotonic() + 15.0
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                BlobServiceClient.from_connection_string(conn_str).get_service_properties()
                break
            except Exception as exc:  # noqa: BLE001 — retry loop
                last_err = exc
                time.sleep(0.3)
        else:
            raise RuntimeError(f"Azurite did not become ready within 15s: {last_err}")

        yield conn_str
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"Failed to start Azurite via Docker: {exc.output.decode(errors='replace')}")
    finally:
        if container_id:
            subprocess.run(
                ["docker", "stop", container_id],
                check=False,
                capture_output=True,
            )
