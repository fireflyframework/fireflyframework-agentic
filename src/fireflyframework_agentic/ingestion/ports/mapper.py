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

"""MapperPort: protocol for converting raw files into typed records."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from fireflyframework_agentic.ingestion.domain import RawFile, TargetSchema, TypedRecord


@runtime_checkable
class MapperPort(Protocol):
    """Translates a RawFile (and its local cached path) into typed rows."""

    def supports(self, file: RawFile) -> bool:
        """Return whether this mapper can handle *file*."""
        ...

    def map(self, file: RawFile, path: Path, schema: TargetSchema) -> Iterator[TypedRecord]:
        """Yield typed records produced from *file*.

        Args:
            file: Metadata about the file (name, mime_type, source_id, etc.).
            path: Local path to the cached copy of the file on disk.
            schema: Target schema to validate emitted rows against.
        """
        ...
