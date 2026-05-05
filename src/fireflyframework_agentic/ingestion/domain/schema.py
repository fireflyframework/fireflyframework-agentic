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

"""Target schema definition: tables, columns, types, foreign keys.

The schema is the contract between mapping scripts and the sink. It is loaded
from a YAML file at the start of a run and stays read-only thereafter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

ColumnType = Literal[
    "string",
    "integer",
    "float",
    "boolean",
    "date",
    "datetime",
    "json",
]


class ColumnSpec(BaseModel):
    """Specification of a single column.

    Attributes:
        name: Column name as it will appear in the sink.
        type: Logical type. Sinks map this to their native types.
        nullable: Whether NULL values are allowed.
        primary_key: Whether the column is part of the primary key.
        enum_values: If set, values outside this list are treated as
            invalid and the row is rejected.
    """

    name: str
    type: ColumnType
    nullable: bool = True
    primary_key: bool = False
    enum_values: list[str] | None = None


class ForeignKeySpec(BaseModel):
    """Specification of a foreign-key relationship.

    Attributes:
        column: Local column name on the table holding the FK.
        references_table: Target table name.
        references_column: Target column name (typically a primary key).
    """

    column: str
    references_table: str
    references_column: str


class TableSpec(BaseModel):
    """Specification of a single table.

    Attributes:
        name: Table name.
        columns: Ordered list of columns.
        foreign_keys: Foreign-key constraints to other tables in the schema.
    """

    name: str
    columns: list[ColumnSpec]
    foreign_keys: list[ForeignKeySpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_columns_unique(self) -> TableSpec:
        names = [c.name for c in self.columns]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate columns in table {self.name!r}: {names}")
        return self

    def column(self, name: str) -> ColumnSpec:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"column {name!r} not in table {self.name!r}")


class TargetSchema(BaseModel):
    """The full target schema: a set of tables with cross-references.

    Attributes:
        tables: List of :class:`TableSpec`. Order is the order in which the
            sink will create them; foreign-key targets must precede their
            referrers if the sink enforces FKs at create time.
    """

    tables: list[TableSpec]

    @model_validator(mode="after")
    def _check_tables_unique_and_fks_resolve(self) -> TargetSchema:
        names = [t.name for t in self.tables]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate table names: {names}")
        table_index = {t.name: t for t in self.tables}
        for t in self.tables:
            for fk in t.foreign_keys:
                if fk.references_table not in table_index:
                    raise ValueError(
                        f"foreign key {t.name}.{fk.column} -> "
                        f"{fk.references_table}.{fk.references_column}: "
                        f"target table not in schema"
                    )
                target = table_index[fk.references_table]
                if not any(c.name == fk.references_column for c in target.columns):
                    raise ValueError(
                        f"foreign key {t.name}.{fk.column} -> "
                        f"{fk.references_table}.{fk.references_column}: "
                        f"target column not in target table"
                    )
                if not any(c.name == fk.column for c in t.columns):
                    raise ValueError(
                        f"foreign key {t.name}.{fk.column} -> "
                        f"{fk.references_table}.{fk.references_column}: "
                        f"local column not in table"
                    )
        return self

    def table(self, name: str) -> TableSpec:
        for t in self.tables:
            if t.name == name:
                return t
        raise KeyError(f"table {name!r} not in schema")

    @classmethod
    def from_yaml(cls, path: str | Path) -> TargetSchema:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
