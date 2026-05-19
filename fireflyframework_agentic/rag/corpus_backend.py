# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Pluggable storage layer for the corpus RAG MCP tools.

The MCP tools (:mod:`fireflyframework_agentic.tools.builtins.corpus_rag`)
need two operations from their storage layer:

* **Per-corpus lookup** — given a ``corpus_id``, return the
  :class:`~fireflyframework_agentic.storage.StorageBackend` whose
  sqlite file is the canonical artifact for that corpus.
* **Enumeration** — list every corpus the server can see, with size +
  modified timestamps.

Bundling both behind a single :class:`CorpusBackendRegistry` keeps the
two operations consistent (e.g. the local registry walks
``CORPUS_ROOT`` for both; an Azure registry talks to one container for
both).

The framework ships :class:`LocalCorpusBackendRegistry`. Non-filesystem
implementations — Azure Blob, S3, GCS — live in ``examples/`` so the
framework stays vendor-neutral and doesn't pull cloud SDKs as direct
dependencies. Selection at runtime is via the
``CORPUS_BACKEND_REGISTRY_FACTORY`` env var, parsed by
:func:`resolve_registry_factory`, mirroring the
``FIREFLY_MCP_TOKEN_STORE_FACTORY`` pattern used by the MCP auth layer.
"""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fireflyframework_agentic.storage import LocalBackend, StorageBackend

_DEFAULT_CORPUS_ROOT = "/tmp/firefly/corpora"
_CORPUS_SQLITE_NAME = "corpus.sqlite"


@runtime_checkable
class CorpusBackendRegistry(Protocol):
    """How the MCP corpus tools find the storage for a given corpus."""

    @property
    def source(self) -> str:
        """Human-readable source label.

        Surfaced in :func:`list_corpora`'s ``corpus_root`` field so an
        operator can tell at a glance whether the server is reading from
        a local directory, a blob container, or something else. Free-
        form; no parser depends on it.
        """
        ...

    def backend_for(self, corpus_id: str) -> StorageBackend:
        """Return the :class:`StorageBackend` for *corpus_id*.

        Called from :func:`_agent_for` once per corpus and cached. The
        same instance is reused for the lifetime of the process, so an
        implementation can hold long-lived clients / credentials in the
        returned backend.
        """
        ...

    async def list_corpora(self) -> list[dict[str, Any]]:
        """Return every corpus this registry can serve.

        Each entry must carry ``corpus_id`` (str), ``size_bytes``
        (int or None), ``modified`` (ISO-8601 str or None). Caller
        sorts and filters the result; implementations don't apply the
        authorisation contextvar themselves.
        """
        ...


class LocalCorpusBackendRegistry:
    """Filesystem-backed registry: each corpus is a directory under
    ``CORPUS_ROOT`` containing ``corpus.sqlite``.

    The directory layout matches what shipped with the original MCP
    server, so existing on-disk state is forward-compatible.

    Args:
        root: Optional override for the filesystem root. ``None`` reads
            from ``CORPUS_ROOT`` env var, falling back to
            ``/tmp/firefly/corpora`` to match the framework's default.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root_override = root

    @property
    def root(self) -> Path:
        if self._root_override is not None:
            return self._root_override
        return Path(os.path.expandvars(os.environ.get("CORPUS_ROOT", _DEFAULT_CORPUS_ROOT)))

    @property
    def source(self) -> str:
        return str(self.root)

    def backend_for(self, corpus_id: str) -> StorageBackend:
        return LocalBackend(self.root / corpus_id / _CORPUS_SQLITE_NAME)

    async def list_corpora(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        root = self.root
        if not root.is_dir():
            return out
        for entry in sorted(root.iterdir()):
            sqlite_path = entry / _CORPUS_SQLITE_NAME
            if not (entry.is_dir() and sqlite_path.is_file()):
                continue
            st = sqlite_path.stat()
            out.append(
                {
                    "corpus_id": entry.name,
                    "size_bytes": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
                }
            )
        return out


def resolve_registry_factory(spec: str):
    """Resolve a ``"module.path:callable"`` factory string.

    The callable must take no arguments and return a
    :class:`CorpusBackendRegistry`. Errors carry enough context for an
    operator to fix the env var without source-diving (the alternative
    — a bare ``ImportError`` at first tool call — makes ops debugging
    painful, matching the pattern in
    :mod:`fireflyframework_agentic.exposure.mcp.http_cli`).
    """
    module_path, _, attr = spec.partition(":")
    if not module_path or not attr:
        raise RuntimeError(f"CORPUS_BACKEND_REGISTRY_FACTORY must look like 'pkg.mod:callable', got {spec!r}")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise RuntimeError(
            f"Cannot import corpus backend registry factory module {module_path!r}: {exc}. "
            "Check the module is installed and importable from the server's "
            "Python path. For Azure-backed corpora install the corpus_search "
            "example deps and point at "
            "'examples.corpus_search.azure_corpus_registry:build_registry'."
        ) from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise RuntimeError(f"Factory {spec!r} resolved to a module without attribute {attr!r}") from exc


__all__ = [
    "CorpusBackendRegistry",
    "LocalCorpusBackendRegistry",
    "resolve_registry_factory",
]
