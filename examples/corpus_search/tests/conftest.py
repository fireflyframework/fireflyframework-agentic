"""Put examples/corpus_search/ on sys.path so tests can import moved backends."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

# examples/corpus_search/ needs to be importable (azure_backend, sharepoint_source, etc.)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set dummy API key for pydantic-ai Anthropic agents during test collection
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

# Azurite connection-string env var consumed by the azurite_connection_string fixture
AZURITE_CONNECTION_STRING_ENV = "AZURITE_CONNECTION_STRING"

# Azurite dev key — public well-known constant from Microsoft's docs.
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
    """
    # The Azure SDK is required to talk to Azurite even if the env var is set
    pytest.importorskip("azure.storage.blob")

    env_str = os.environ.get(AZURITE_CONNECTION_STRING_ENV)
    if env_str:
        yield env_str
        return

    if not shutil.which("docker"):
        pytest.skip(f"Azurite not configured: set {AZURITE_CONNECTION_STRING_ENV} or install Docker")

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
                    "--skipApiVersionCheck",
                ],
                stderr=subprocess.STDOUT,
            )
            .decode()
            .strip()
        )

        port_line = subprocess.check_output(["docker", "port", container_id, "10000/tcp"]).decode().splitlines()[0]
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
            except Exception as exc:
                last_err = exc
                time.sleep(0.3)
        else:
            raise RuntimeError(f"Azurite did not become ready within 15s: {last_err}")

        yield conn_str
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"Failed to start Azurite via Docker: {exc.output.decode(errors='replace')}")
    finally:
        if container_id:
            subprocess.run(["docker", "kill", container_id], check=False, capture_output=True)
