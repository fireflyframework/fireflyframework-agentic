# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Azure blob storage backed :class:`CorpusBackendRegistry`.

Activate by setting on the MCP server::

    CORPUS_BACKEND_REGISTRY_FACTORY=examples.corpus_search.azure_corpus_registry:build_registry
    CORPUS_AZURE_CONTAINER_URL=https://<account>.blob.core.windows.net/<container>

The registry stores each corpus as a single ``<corpus_id>.sqlite`` blob
in the container; :class:`AzureBlobBackend` (in the same package) gives
each per-corpus :class:`DatabaseStore` leased writes against its blob,
and listing walks the container's blobs to recover corpus ids.

Authentication is via ``DefaultAzureCredential`` so the same code runs
under managed identity (Container Apps) and ``az login`` (local dev).
The framework never sees the Azure SDKs directly — only this example
module — keeping the core vendor-neutral.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
from azure.storage.blob import ContainerClient  # type: ignore[import-not-found]

from examples.corpus_search.azure_backend import AzureBlobBackend
from fireflyframework_agentic.storage import StorageBackend

_CONTAINER_URL_ENV = "CORPUS_AZURE_CONTAINER_URL"
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
    """:class:`CorpusBackendRegistry` impl backed by an Azure blob container."""

    def __init__(self, container_url: str) -> None:
        self._container_url = container_url.rstrip("/")
        # ``DefaultAzureCredential`` picks the right credential chain at
        # acquisition time. We hold one instance for the lifetime of the
        # registry so token caches survive across calls.
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
            # than surfacing slashes in corpus_ids that nothing else
            # in the system can route to.
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

    Reads the container URL from the environment so operators don't
    have to pass parameters through the env-var-spec mechanism.
    """
    container_url = os.environ.get(_CONTAINER_URL_ENV)
    if not container_url:
        raise RuntimeError(
            f"{_CONTAINER_URL_ENV} must be set to the blob container URL "
            "(e.g. https://<account>.blob.core.windows.net/<container>) for the "
            "Azure-backed corpus registry."
        )
    return AzureCorpusBackendRegistry(container_url)


__all__ = ["AzureCorpusBackendRegistry", "build_registry"]
