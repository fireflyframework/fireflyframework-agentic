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

"""SQLite query tool for agents: SELECT-only access to structured ingestion data."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

_SELECT_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


def query_sqlite(db_path: str | Path, sql: str) -> list[dict[str, Any]]:
    """Execute a SELECT-only query against a SQLite database.

    Args:
        db_path: Path to the SQLite database file.
        sql: SQL statement to execute. Must start with SELECT.

    Returns:
        List of rows as dicts mapping column name to value.

    Raises:
        ValueError: If sql is not a SELECT statement.
        sqlite3.Error: If the query fails.
    """
    if not _SELECT_RE.match(sql):
        raise ValueError("Only SELECT statements are permitted")
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        return [dict(row) for row in cur.fetchall()]
