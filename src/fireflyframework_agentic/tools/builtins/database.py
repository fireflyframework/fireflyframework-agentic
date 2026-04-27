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

"""Built-in database query tool abstraction.

:class:`DatabaseTool` defines the interface for executing queries against
SQL or NoSQL databases.  Users must subclass and implement
:meth:`_execute_query` with their specific driver.
"""

from __future__ import annotations

import logging
import re
from abc import abstractmethod
from collections.abc import Sequence
from typing import Any

from fireflyframework_agentic.exceptions import ToolError
from fireflyframework_agentic.tools.base import BaseTool, GuardProtocol, ParameterSpec

logger = logging.getLogger(__name__)


class DatabaseTool(BaseTool):
    """Abstract database tool that users extend with their preferred driver.

    Subclasses must implement :meth:`_execute_query`.

    Parameters:
        name: Tool name (defaults to ``"database"``).
        read_only: If *True*, only SELECT-like queries are allowed.
        guards: Optional guard chain.
    """

    def __init__(
        self,
        *,
        name: str = "database",
        read_only: bool = True,
        enable_injection_detection: bool = True,
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(
            name,
            description="Execute database queries",
            tags=["database", "sql"],
            guards=guards,
            parameters=[
                ParameterSpec(name="query", type_annotation="str", description="SQL or query string", required=True),
                ParameterSpec(
                    name="params",
                    type_annotation="dict[str, Any] | None",
                    description="Query parameters",
                    required=False,
                    default=None,
                ),
            ],
        )
        self._read_only = read_only
        self._enable_injection_detection = enable_injection_detection

    async def _execute(self, **kwargs: Any) -> Any:
        query: str = kwargs["query"]
        params: dict[str, Any] | None = kwargs.get("params")

        # SQL injection detection
        if self._enable_injection_detection:
            self._validate_query_safety(query)

        if self._read_only:
            normalised = query.strip().upper()
            if not normalised.startswith("SELECT") and not normalised.startswith("WITH"):
                raise PermissionError("DatabaseTool is in read-only mode; only SELECT / WITH queries are allowed")

        return await self._execute_query(query, params)

    def _validate_query_safety(self, query: str) -> None:
        """Detect common SQL injection patterns.

        Raises:
            ToolError: If potentially unsafe SQL patterns are detected.

        Note:
            This is a heuristic-based defense-in-depth measure. It does NOT
            replace proper parameterization. Always use parameterized queries
            with the `params` argument instead of string interpolation.
        """
        # Normalize query for pattern matching
        query_lower = query.lower()

        # Dangerous patterns that suggest SQL injection
        unsafe_patterns = [
            # String concatenation in SQL (suggests non-parameterized query)
            (r"'\s*\+\s*'", "String concatenation detected (use parameterized queries)"),
            (r"'\s*\|\|\s*'", "String concatenation with || detected (use parameterized queries)"),
            (r"concat\s*\(", "CONCAT function detected (use parameterized queries)"),
            # Multiple statements (SQL injection attempts)
            (r";\s*drop\s+", "Multiple statements with DROP detected (SQL injection attempt)"),
            (r";\s*delete\s+", "Multiple statements with DELETE detected (SQL injection attempt)"),
            (r";\s*update\s+", "Multiple statements with UPDATE detected (SQL injection attempt)"),
            (r";\s*insert\s+", "Multiple statements with INSERT detected (SQL injection attempt)"),
            (r";\s*exec\s*\(", "Multiple statements with EXEC detected (SQL injection attempt)"),
            (r";\s*execute\s+", "Multiple statements with EXECUTE detected (SQL injection attempt)"),
            # Comment-based injection
            (r"--\s*$", "SQL comment at end of query (potential injection)"),
            (r"/\*.*\*/", "SQL block comment detected (potential injection)"),
            # Always-true conditions (authentication bypass)
            (r"'\s*or\s+'?1'?\s*=\s*'?1", "Always-true condition detected (SQL injection attempt)"),
            (r"'\s*or\s+1\s*=\s*1", "Always-true condition detected (SQL injection attempt)"),
            (r"'\s*or\s+'.*'\s*=\s*'", "Suspicious OR condition detected (potential injection)"),
            # Union-based injection
            (r"union\s+select", "UNION SELECT detected (potential injection)"),
            (r"union\s+all\s+select", "UNION ALL SELECT detected (potential injection)"),
            # Information schema access (reconnaissance)
            (r"information_schema\.", "Information schema access detected (reconnaissance attempt)"),
            (r"sys\.", "System catalog access detected (reconnaissance attempt)"),
            (r"pg_catalog\.", "PostgreSQL catalog access detected (reconnaissance attempt)"),
            # Time-based blind injection
            (r"sleep\s*\(", "SLEEP function detected (time-based injection attempt)"),
            (r"waitfor\s+delay", "WAITFOR DELAY detected (time-based injection attempt)"),
            (r"benchmark\s*\(", "BENCHMARK function detected (time-based injection attempt)"),
            # File operations (data exfiltration)
            (r"into\s+outfile", "INTO OUTFILE detected (file write attempt)"),
            (r"into\s+dumpfile", "INTO DUMPFILE detected (file write attempt)"),
            (r"load_file\s*\(", "LOAD_FILE detected (file read attempt)"),
            # Hex encoding (obfuscation)
            (r"0x[0-9a-f]{10,}", "Long hex string detected (potential obfuscation)"),
            # Stacked queries
            (r";\s*select", "Stacked query with SELECT detected"),
        ]

        for pattern, reason in unsafe_patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                logger.warning(
                    "SQL injection pattern detected in query: %s. Query: %s",
                    reason,
                    query[:100],
                )
                raise ToolError(
                    f"Unsafe SQL pattern detected: {reason}. "
                    f"Use parameterized queries with the 'params' argument instead of string interpolation."
                )

        # Warn if query contains unescaped quotes (might be injection)
        if re.search(r"'[^']*?{.*?}[^']*?'", query):
            logger.warning(
                "Query contains format string placeholders inside quotes (potential injection): %s",
                query[:100],
            )
            raise ToolError(
                "Format string placeholders detected inside quotes. "
                "Use parameterized queries with the 'params' argument."
            )

    @abstractmethod
    async def _execute_query(self, query: str, params: dict[str, Any] | None) -> Any:
        """Execute the query and return results.

        Parameters:
            query: The query string (SQL, NoSQL, etc.).
            params: Optional mapping of parameter names to values.

        Returns:
            Query results in a driver-specific format (typically a list of
            dicts for SQL databases).
        """
        ...
