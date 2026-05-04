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

"""ContentSource Protocol and the shared :class:`RawFile` data model."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True, frozen=True)
class RawFile:
    """A file discovered by a :class:`ContentSource`, before download or conversion.

    Attributes:
        source_id: Globally unique identifier, kind-prefixed by the originating
            source so consumers can route polymorphically without inspecting
            the source instance. Examples: ``sharepoint:01ABCDEF``,
            ``s3:my-bucket/path/to/file.pdf``.
        name: File name as exposed by the source.
        mime_type: Content type as reported by the source. May be empty when
            the source does not expose one.
        size_bytes: File size in bytes as reported by the source.
        etag: Opaque cache key used to detect content changes between runs.
            SharePoint uses the Microsoft Graph eTag, S3 the object ETag,
            etc. Callers MUST treat this as a black box.
        fetched_at: Time at which the source produced this descriptor.
        metadata: Source-specific extras that do not fit elsewhere on the
            record (parent path, last-modified-by, generation number, etc.).
    """

    source_id: str
    name: str
    mime_type: str
    size_bytes: int
    etag: str
    fetched_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ContentSource(Protocol):
    """An external system that yields files for ingestion.

    Sources are stateful with respect to their delta cursor. Calling
    :meth:`list_changed` with ``None`` lists everything; calling it with a
    cursor returned by :meth:`pending_cursor` of a previous run yields only
    items changed since that cursor.

    Implementations MUST NOT auto-commit during iteration. The caller is
    responsible for invoking :meth:`commit_delta` once all downstream work
    has succeeded, so that a crash mid-ingestion does not advance the cursor
    past files that were never persisted.
    """

    def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:
        """Yield files that changed since ``since``.

        Args:
            since: Cursor returned by a previous run, or ``None`` to list
                everything from scratch.
        """
        ...

    async def fetch(self, file: RawFile) -> Path:
        """Download ``file`` into the local cache and return its path.

        Implementations are expected to dedupe by ``file.etag`` so repeated
        calls for unchanged files are cheap.
        """
        ...

    async def current_cursor(self) -> str | None:
        """Return the cursor persisted from the previous successful run."""
        ...

    async def pending_cursor(self) -> str | None:
        """Return the cursor observed during the in-flight iteration but not
        yet committed.

        Returns ``None`` until :meth:`list_changed` has yielded at least one
        page that exposes a delta token.
        """
        ...

    async def commit_delta(self, cursor: str) -> None:
        """Persist ``cursor`` so the next run can resume incrementally."""
        ...
