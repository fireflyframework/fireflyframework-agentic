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

"""Shared scaffolding for Postgres-backed pipeline backends.

The checkpointer and audit-log backends both need the same boilerplate:
optional-dep guard on ``psycopg``, ``dsn`` xor ``connection`` constructor
check, table-name validation, and lazy idempotent DDL on first write. This
module centralizes it so each backend only has to declare its DDL and
default table name.
"""

from __future__ import annotations

from typing import Any

try:
    import psycopg as _psycopg  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    _psycopg = None  # type: ignore[assignment]


class PsycopgBackend:
    """Base class for backends that persist into a single Postgres table.

    Subclasses set the class attribute ``_DDL`` to a format string with a
    single ``{table}`` placeholder, and pass their human-readable name and
    default table to ``__init__``. The base class handles the rest:

    * Raises ``ImportError`` if the ``postgres`` extra is not installed.
    * Enforces ``dsn`` xor ``connection``.
    * Validates ``table_name`` against SQL injection (interpolated into DDL).
    * Opens the connection (with ``autocommit=True``) when only ``dsn`` is given.
    * Applies the DDL lazily and idempotently on first ``_ensure_table()`` call.
    """

    _DDL: str = ""

    def __init__(
        self,
        *,
        kind: str,
        dsn: str | None,
        connection: Any,
        table_name: str,
    ) -> None:
        if _psycopg is None:
            raise ImportError(
                f"{kind} requires the 'postgres' extra. Install with: pip install fireflyframework-agentic[postgres]"
            )
        if (dsn is None) == (connection is None):
            raise ValueError(f"{kind} needs exactly one of `dsn` or `connection`.")
        # Table name is interpolated into DDL — validate strictly to avoid SQL injection.
        if not table_name.replace("_", "").isalnum():
            raise ValueError(f"Invalid table_name {table_name!r}: must be alphanumeric/underscore only.")
        self._conn = connection if connection is not None else _psycopg.connect(dsn, autocommit=True)
        self._table = table_name
        self._ddl_applied = False

    def _ensure_table(self) -> None:
        if self._ddl_applied:
            return
        with self._conn.cursor() as cur:
            cur.execute(self._DDL.format(table=self._table))
        self._ddl_applied = True
