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
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RawFile(BaseModel):
    """A file discovered in an external source and (possibly) cached locally.

    Attributes:
        source_id: Stable identifier across runs, including the source kind.
            Convention: ``"<source>:<path>"``, e.g. ``"sharepoint:Sales/Q1.xlsx"``.
        name: Display name of the file (no path).
        mime_type: MIME type as reported by the source. May be empty for
            sources that do not provide it.
        size_bytes: File size in bytes.
        etag: Opaque token used to deduplicate fetches across runs.
        fetched_at: When the file was last fetched into the local cache.
        local_path: Absolute path to the cached copy on local disk.
    """

    source_id: str
    name: str
    mime_type: str = ""
    size_bytes: int = 0
    etag: str = ""
    fetched_at: datetime
    local_path: Path


class TypedRecord(BaseModel):
    """A single row produced by a mapping script, targeted at a table.

    Attributes:
        table: Name of the destination table in the target schema.
        row: Column-to-value mapping. Keys must match :class:`TableSpec`
            columns; values are validated by the sink against :class:`ColumnSpec`.
    """

    table: str
    row: dict[str, Any]


class IngestionError(BaseModel):
    """A non-fatal error captured during a run.

    Attributes:
        kind: Error category (e.g. ``"NoMapperFound"``, ``"MappingScriptError"``,
            ``"RowValidationError"``).
        message: Human-readable description.
        file_source_id: Source identifier of the file the error relates to,
            if applicable.
        details: Free-form structured context useful for debugging.
    """

    kind: str
    message: str
    file_source_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    """Outcome of a single :meth:`IngestionService.run_*` invocation.

    Attributes:
        files_processed: Number of files successfully mapped (errors excluded).
        records_written: Map of table name to row count actually written.
        errors: Non-fatal errors captured during the run.
        run_id: Identifier passed to the run for traceability, if any.
            Echoed back from the caller; the service does not generate it.
    """

    files_processed: int = 0
    records_written: dict[str, int] = Field(default_factory=dict)
    errors: list[IngestionError] = Field(default_factory=list)
    run_id: str | None = None
