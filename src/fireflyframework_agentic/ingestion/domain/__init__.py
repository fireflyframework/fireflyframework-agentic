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

"""Pure domain models for the ingestion module."""

from fireflyframework_agentic.ingestion.domain.records import (
    IngestionError,
    IngestionResult,
    RawFile,
    TypedRecord,
)
from fireflyframework_agentic.ingestion.domain.schema import (
    ColumnSpec,
    ColumnType,
    ForeignKeySpec,
    TableSpec,
    TargetSchema,
)

__all__ = [
    "ColumnSpec",
    "ColumnType",
    "ForeignKeySpec",
    "IngestionError",
    "IngestionResult",
    "RawFile",
    "TableSpec",
    "TargetSchema",
    "TypedRecord",
]
