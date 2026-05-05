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

"""SQLite sink: builds a normalized database from typed records.

Stdlib-only (sqlite3). On every :meth:`begin` the target tables are
dropped and recreated from the schema, so the database always reflects
the current run. Identifiers (table/column names) are validated through
:func:`fireflyframework_agentic.security.identifiers.validate_identifier`
before any string interpolation; values always go through ``?``
placeholders.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from fireflyframework_agentic.ingestion.domain import (
    ColumnSpec,
    ColumnType,
    IngestionError,
    TableSpec,
    TargetSchema,
    TypedRecord,
)
from fireflyframework_agentic.security.identifiers import validate_identifier

logger = logging.getLogger(__name__)


_SQLITE_TYPES: dict[ColumnType, str] = {
    "string": "TEXT",
    "integer": "INTEGER",
    "float": "REAL",
    "boolean": "INTEGER",
    "date": "TEXT",
    "datetime": "TEXT",
    "json": "TEXT",
}


class SQLiteSink:
    """SQLite sink with idempotent rebuild on every run.

    Each call to :meth:`begin` drops any pre-existing tables in the
    schema and recreates them. Rows are validated against
    :class:`ColumnSpec` before insertion; invalid rows are skipped and
    accumulated in :attr:`validation_errors`.

    Parameters:
        db_path: Path to the SQLite file, or ``":memory:"`` for an
            ephemeral in-process database. Defaults to ``":memory:"``.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._schema: TargetSchema | None = None
        self._counts: dict[str, int] = {}
        self.validation_errors: list[IngestionError] = []

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SQLiteSink: begin() must be called first")
        return self._conn

    def begin(self, schema: TargetSchema) -> None:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA foreign_keys = ON")
        self._schema = schema
        self._counts = {t.name: 0 for t in schema.tables}
        self.validation_errors = []
        # Drop in reverse order so FK targets survive until their referrers
        # have been dropped; recreate in declared order.
        for table in reversed(schema.tables):
            self._conn.execute(f"DROP TABLE IF EXISTS {self._quote(table.name)}")
        for table in schema.tables:
            self._conn.execute(self._create_table_sql(table))
        self._conn.commit()

    def write(self, records: Iterable[TypedRecord]) -> None:
        if self._conn is None or self._schema is None:
            raise RuntimeError("SQLiteSink: begin() must be called first")
        for record in records:
            try:
                table = self._schema.table(record.table)
            except KeyError:
                self.validation_errors.append(
                    IngestionError(
                        kind="UnknownTable",
                        message=f"record references unknown table {record.table!r}",
                        details={"row": record.row},
                    )
                )
                continue
            coerced = self._validate_and_coerce(table, record.row)
            if coerced is None:
                continue
            placeholders = ", ".join(["?"] * len(table.columns))
            cols = ", ".join(self._quote(c.name) for c in table.columns)
            sql = f"INSERT INTO {self._quote(table.name)} ({cols}) VALUES ({placeholders})"
            self._conn.execute(sql, [self._adapt(c, coerced[c.name]) for c in table.columns])
            self._counts[table.name] += 1
        self._conn.commit()

    def finalize(self) -> dict[str, int]:
        if self._conn is not None:
            self._conn.commit()
        return dict(self._counts)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _validate_and_coerce(self, table: TableSpec, row: dict[str, Any]) -> dict[str, Any] | None:
        coerced: dict[str, Any] = {}
        for column in table.columns:
            value = row.get(column.name)
            if value is None:
                if column.nullable:
                    coerced[column.name] = None
                    continue
                self.validation_errors.append(
                    IngestionError(
                        kind="RowValidationError",
                        message=(f"column {table.name}.{column.name} is non-nullable but row provided no value"),
                        details={"row": row},
                    )
                )
                return None
            try:
                coerced[column.name] = self._coerce(column, value)
            except (TypeError, ValueError) as exc:
                self.validation_errors.append(
                    IngestionError(
                        kind="RowValidationError",
                        message=(f"column {table.name}.{column.name} ({column.type}): {exc}"),
                        details={"row": row, "value": repr(value)},
                    )
                )
                return None
        unknown = set(row) - {c.name for c in table.columns}
        if unknown:
            self.validation_errors.append(
                IngestionError(
                    kind="RowValidationError",
                    message=(f"row contains unknown columns for table {table.name}: {sorted(unknown)}"),
                    details={"row": row},
                )
            )
            return None
        return coerced

    @staticmethod
    def _coerce(column: ColumnSpec, value: Any) -> Any:
        if column.enum_values is not None and value not in column.enum_values:
            raise ValueError(f"value {value!r} not in enum {column.enum_values}")
        ctype = column.type
        if ctype == "string":
            return str(value)
        if ctype == "integer":
            if isinstance(value, bool):
                raise TypeError("bool is not a valid integer")
            return int(value)
        if ctype == "float":
            if isinstance(value, bool):
                raise TypeError("bool is not a valid float")
            return float(value)
        if ctype == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                low = value.strip().lower()
                if low in {"true", "1", "yes", "y"}:
                    return True
                if low in {"false", "0", "no", "n"}:
                    return False
                raise ValueError(f"cannot parse boolean from {value!r}")
            raise TypeError(f"cannot coerce {type(value).__name__} to boolean")
        if ctype == "date":
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            if isinstance(value, str):
                return date.fromisoformat(value)
            raise TypeError(f"cannot coerce {type(value).__name__} to date")
        if ctype == "datetime":
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value)
            raise TypeError(f"cannot coerce {type(value).__name__} to datetime")
        if ctype == "json":
            return value
        raise ValueError(f"unknown column type {ctype!r}")

    @staticmethod
    def _adapt(column: ColumnSpec, value: Any) -> Any:
        """Convert a coerced Python value to a sqlite3-compatible scalar."""
        if value is None:
            return None
        ctype = column.type
        if ctype == "boolean":
            return 1 if value else 0
        if ctype == "date":
            return value.isoformat()
        if ctype == "datetime":
            return value.isoformat()
        if ctype == "json":
            return json.dumps(value)
        return value

    def _create_table_sql(self, table: TableSpec) -> str:
        cols = []
        for c in table.columns:
            sqlite_type = _SQLITE_TYPES[c.type]
            constraints: list[str] = []
            if not c.nullable:
                constraints.append("NOT NULL")
            if c.primary_key:
                constraints.append("PRIMARY KEY")
            constraint_clause = (" " + " ".join(constraints)) if constraints else ""
            cols.append(f"{self._quote(c.name)} {sqlite_type}{constraint_clause}")
        for fk in table.foreign_keys:
            cols.append(
                f"FOREIGN KEY ({self._quote(fk.column)}) "
                f"REFERENCES {self._quote(fk.references_table)}({self._quote(fk.references_column)})"
            )
        return f"CREATE TABLE {self._quote(table.name)} ({', '.join(cols)})"

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + validate_identifier(identifier) + '"'
