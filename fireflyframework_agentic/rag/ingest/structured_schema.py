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

"""Domain models for structured data ingestion schema."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ColumnType(StrEnum):
    string = "string"
    integer = "integer"
    float_ = "float"
    boolean = "boolean"
    date = "date"
    datetime = "datetime"
    json = "json"


class ColumnSpec(BaseModel):
    name: str
    type: ColumnType
    nullable: bool = True
    primary_key: bool = False
    foreign_key: str | None = None
    """References another table's column as ``"<table>.<column>"`` (e.g. ``"customers.id"``)."""
    unit: str | None = None
    """Human-readable unit for the values stored in this column
    (e.g. ``"USD millions"``, ``"headcount"``, ``"percent"``, ``"days"``).

    Optional and free-form. When set, the SQL retriever's schema context
    surfaces the unit to the agent, and the answerer is instructed to
    include the unit alongside any numeric quantity it cites for this
    column. When ``None``, the answerer is instructed to either ask the
    user or flag the ambiguity in the response rather than presenting a
    unit-less number.
    """


class TableSpec(BaseModel):
    name: str
    columns: list[ColumnSpec]


class TargetSchema(BaseModel):
    tables: list[TableSpec] = Field(default_factory=list)
    """List of inferred tables. Defaults to ``[]`` so a model returning
    ``{}`` (the common failure mode on messy / non-tabular inputs)
    passes validation instead of triggering pydantic-ai's retry storm.
    Callers that need a non-empty schema must check ``schema.tables``
    explicitly and surface the emptiness to the user themselves.
    """


class SchemaFeedback(BaseModel):
    approved: bool
    corrections: str = ""
