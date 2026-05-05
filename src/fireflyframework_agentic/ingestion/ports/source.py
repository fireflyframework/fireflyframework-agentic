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

"""DataSourcePort: protocol for external data sources."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from fireflyframework_agentic.ingestion.domain import RawFile


@runtime_checkable
class DataSourcePort(Protocol):
    """Lists, fetches, and tracks delta state of an external data source.

    Implementations are responsible for authentication, pagination, and
    persisting any cursor needed to resume incremental sync.
    """

    def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:
        """Yield files that changed since the given cursor.

        Args:
            since: Opaque cursor returned by a previous run, or ``None`` to
                list everything.
        """
        ...

    async def fetch(self, file: RawFile) -> Path:
        """Download *file* into the local cache and return its path.

        The implementation is expected to dedupe by ``file.etag`` so that
        repeated calls for unchanged files are cheap.
        """
        ...

    async def commit_delta(self, cursor: str) -> None:
        """Persist *cursor* so the next run can resume incrementally."""
        ...

    async def current_cursor(self) -> str | None:
        """Return the cursor persisted from the previous successful run."""
        ...
