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

"""Domain records for the ingestion module.

These models are pure value objects: they hold data and validate it through
Pydantic, but never perform I/O. Adapters and services compose them.

Note: RawFile is defined in content.sources.base and re-exported here for
convenience so callers can use a single import path.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fireflyframework_agentic.content.sources.base import RawFile


class TypedRecord(BaseModel):
    """A single row produced by a mapping script, targeted at a table."""

    table: str
    row: dict[str, Any]


class IngestionError(BaseModel):
    """A non-fatal error captured during a run."""

    kind: str
    message: str
    file_source_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    """Outcome of a single IngestionService.run_* invocation."""

    files_processed: int = 0
    records_written: dict[str, int] = Field(default_factory=dict)
    errors: list[IngestionError] = Field(default_factory=list)
    run_id: str | None = None


__all__ = ["IngestionError", "IngestionResult", "RawFile", "TypedRecord"]
