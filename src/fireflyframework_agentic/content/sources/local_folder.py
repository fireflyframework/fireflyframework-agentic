# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Filesystem :class:`ContentSource` — yields files under a local folder.

Mirrors the cursor-based contract of remote sources (SharePoint, S3) so a
single ingest pipeline can serve both local and remote corpora. v1 is
delta-less: every call to :meth:`list_changed` lists everything under the
folder. The :class:`fireflyframework_agentic.rag.ingest.ledger.IngestLedger`
already dedupes by content hash so re-listing is cheap; mtime-based delta
is a future enhancement.
"""

from __future__ import annotations

import inspect
import logging
import mimetypes
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from fireflyframework_agentic.content.sources.base import RawFile
from fireflyframework_agentic.pipeline.triggers.folder_watcher import FolderWatcher

logger = logging.getLogger(__name__)


class LocalFolderSourceConfig(BaseModel):
    folder: Path
    include_hidden: bool = Field(
        default=False,
        description="When False (default), files whose name begins with '.' are skipped.",
    )
    exclude_predicate: Callable[[Path], bool] | None = Field(
        default=None,
        description=(
            "Optional callable; when it returns True for a file path, the file is "
            "skipped. Used by callers that route certain extensions to a separate "
            "pipeline (e.g. CSV/Excel handled by structured ingest)."
        ),
        exclude=True,
    )

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("exclude_predicate")
    @classmethod
    def _reject_async_predicate(
        cls,
        v: Callable[[Path], bool] | None,
    ) -> Callable[[Path], bool] | None:
        """Reject async callables — list_changed calls the predicate
        synchronously, so an async function would return a coroutine
        (truthy) which would silently filter every file."""
        if v is not None and inspect.iscoroutinefunction(v):
            raise ValueError(
                "exclude_predicate must be a sync callable; an async predicate "
                "would return a coroutine which is truthy and would silently "
                "filter every file"
            )
        return v


class LocalFolderSource:
    """A :class:`ContentSource` over a local directory tree."""

    def __init__(self, config: LocalFolderSourceConfig) -> None:
        self._folder = Path(config.folder).resolve()
        self._include_hidden = config.include_hidden
        self._exclude_predicate = config.exclude_predicate
        self._watcher = FolderWatcher(folder=self._folder)

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:  # noqa: ARG002
        # ``since`` is intentionally unused in v1 — see module docstring.
        for path in sorted(self._folder.rglob("*")):
            if not path.is_file():
                continue
            if not self._include_hidden and self._watcher.is_hidden(path):
                continue
            if self._exclude_predicate is not None and self._exclude_predicate(path):
                continue
            try:
                stat = path.stat()
            except OSError as exc:
                logger.warning("stat failed for %s: %s", path, exc)
                continue
            rel = path.relative_to(self._folder).as_posix()
            mime_type, _ = mimetypes.guess_type(path.name)
            yield RawFile(
                source_id=f"local:{self._folder}/{rel}",
                name=path.name,
                mime_type=mime_type or "",
                size_bytes=stat.st_size,
                etag=f"{stat.st_mtime_ns}:{stat.st_size}",
                fetched_at=datetime.now(UTC),
                metadata={"absolute_path": str(path.resolve()), "relative_path": rel},
            )

    async def fetch(self, file: RawFile) -> Path:
        return Path(file.metadata["absolute_path"])

    async def current_cursor(self) -> str | None:
        return None

    async def pending_cursor(self) -> str | None:
        return None

    async def commit_delta(self, cursor: str) -> None:  # noqa: ARG002
        return None
