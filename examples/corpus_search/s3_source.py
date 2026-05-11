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

"""S3-backed :class:`ContentSource` (stub, not yet implemented).

This module ships as a Protocol-conformant placeholder so that the
:class:`ContentSource` contract is locked against a second concrete
implementation. The full :class:`S3SourceConfig` model is defined here
because it is part of the API surface that the future implementation
must honour.

Planned implementation: ``aioboto3`` client; ``list_objects_v2``
pagination filtered by ``LastModified`` against the persisted cursor;
ETag-based local cache; cursor = ISO 8601 timestamp of the most recent
``LastModified`` observed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel, Field

from fireflyframework_agentic.content.sources.base import RawFile

_NOT_IMPLEMENTED_HINT = (
    "S3Source is not yet implemented. When it lands it will require the "
    "[aws] extra: pip install fireflyframework-agentic[aws]."
)


class S3SourceConfig(BaseModel):
    """Configuration for :class:`S3Source` (stub).

    The fields below are part of the locked-in API for the eventual
    implementation. Constructing this model is supported and validated;
    constructing :class:`S3Source` itself raises :class:`NotImplementedError`.
    """

    bucket: str
    prefix: str | None = None
    region: str
    mime_types: list[str] = Field(default_factory=list)
    cache_dir: Path
    cursor_file: Path
    request_timeout_seconds: float = Field(default=30.0, gt=0.0)


class S3Source:
    """Protocol-conformant placeholder for an S3-backed :class:`ContentSource`."""

    def __init__(
        self,
        config: S3SourceConfig,
        *,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_HINT)

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:
        raise NotImplementedError(_NOT_IMPLEMENTED_HINT)
        yield  # pragma: no cover  -- async-generator marker

    async def fetch(self, file: RawFile) -> Path:
        raise NotImplementedError(_NOT_IMPLEMENTED_HINT)

    async def current_cursor(self) -> str | None:
        raise NotImplementedError(_NOT_IMPLEMENTED_HINT)

    async def pending_cursor(self) -> str | None:
        raise NotImplementedError(_NOT_IMPLEMENTED_HINT)

    async def commit_delta(self, cursor: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_HINT)
