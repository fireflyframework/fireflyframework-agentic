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
from typing import Protocol, runtime_checkable

from fireflyframework_agentic.ingestion.domain import RawFile, TargetSchema, TypedRecord


@runtime_checkable
class MapperPort(Protocol):
    """Translates :class:`RawFile` into rows for the target schema."""

    def supports(self, file: RawFile) -> bool:
        """Return whether this mapper can handle *file*."""
        ...

    def map(self, file: RawFile, schema: TargetSchema) -> Iterator[TypedRecord]:
        """Yield typed records produced from *file*.

        The mapper must validate that emitted rows reference tables and
        columns declared in *schema*. Validation against column types is
        the sink's responsibility.
        """
        ...
