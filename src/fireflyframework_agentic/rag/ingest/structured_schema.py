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

from pydantic import BaseModel


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


class TableSpec(BaseModel):
    name: str
    columns: list[ColumnSpec]


class TargetSchema(BaseModel):
    tables: list[TableSpec]


class SchemaFeedback(BaseModel):
    approved: bool
    corrections: str = ""
