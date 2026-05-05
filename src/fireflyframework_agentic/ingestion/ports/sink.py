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

"""StructuredSinkPort: protocol for the downstream normalized store."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from fireflyframework_agentic.ingestion.domain import TargetSchema, TypedRecord


@runtime_checkable
class StructuredSinkPort(Protocol):
    """Receives typed records and materializes them in a downstream store."""

    def begin(self, schema: TargetSchema) -> None:
        """Initialize the sink against *schema* (e.g. CREATE TABLEs)."""
        ...

    def write(self, records: Iterable[TypedRecord]) -> None:
        """Write *records* to their target tables.

        Implementations validate each row against its :class:`TableSpec` and
        skip invalid rows, surfacing them via the service-level error
        accumulator. Implementations MUST NOT silently coerce types.
        """
        ...

    def finalize(self) -> dict[str, int]:
        """Commit pending writes and return per-table row counts."""
        ...

    def close(self) -> None:
        """Release any resources held by the sink."""
        ...
