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

"""Unit tests for SQL injection detection."""

from __future__ import annotations

from typing import Any

import pytest

from fireflyframework_agentic.exceptions import ToolError
from fireflyframework_agentic.tools.builtins.database import DatabaseTool


class TestDatabaseTool(DatabaseTool):
    """Test implementation of DatabaseTool."""

    async def _execute_query(self, query: str, params: dict[str, Any] | None) -> Any:
        return [{"result": "ok"}]


@pytest.mark.asyncio
class TestSQLInjectionDetection:
    """Test suite for SQL injection detection."""

    async def test_safe_query_allowed(self):
        """Test that safe queries are allowed."""
        tool = TestDatabaseTool()

        # Should not raise
        result = await tool._execute(query="SELECT * FROM users WHERE id = ?")
        assert result == [{"result": "ok"}]

    async def test_string_concatenation_detected(self):
        """Test detection of string concatenation (non-parameterized queries)."""
        tool = TestDatabaseTool()

        # SQL concatenation patterns that suggest non-parameterized queries
        with pytest.raises(ToolError, match="String concatenation"):
            await tool._execute(query="SELECT * FROM users WHERE name = '' + 'input'")

    async def test_multiple_statements_detected(self):
        """Test detection of multiple statements (SQL injection attempt)."""
        tool = TestDatabaseTool()

        dangerous_queries = [
            "SELECT * FROM users; DROP TABLE users;",
            "SELECT * FROM users; DELETE FROM users;",
            "SELECT * FROM users; UPDATE users SET admin = 1;",
        ]

        for query in dangerous_queries:
            with pytest.raises(ToolError, match="SQL injection attempt"):
                await tool._execute(query=query)

    async def test_always_true_conditions_detected(self):
        """Test detection of always-true conditions (authentication bypass)."""
        tool = TestDatabaseTool()

        dangerous_queries = [
            "SELECT * FROM users WHERE name = 'admin' OR '1'='1'",
            "SELECT * FROM users WHERE name = 'admin' OR 1=1",
        ]

        for query in dangerous_queries:
            with pytest.raises(ToolError, match="SQL injection attempt"):
                await tool._execute(query=query)

    async def test_union_select_detected(self):
        """Test detection of UNION-based injection."""
        tool = TestDatabaseTool()

        with pytest.raises(ToolError, match="potential injection"):
            await tool._execute(query="SELECT name FROM users UNION SELECT password FROM credentials")

    async def test_information_schema_detected(self):
        """Test detection of information schema access (reconnaissance)."""
        tool = TestDatabaseTool()

        with pytest.raises(ToolError, match="reconnaissance attempt"):
            await tool._execute(query="SELECT * FROM information_schema.tables")

    async def test_time_based_injection_detected(self):
        """Test detection of time-based blind injection."""
        tool = TestDatabaseTool()

        dangerous_queries = [
            "SELECT * FROM users WHERE id = 1 AND SLEEP(5)",
            "SELECT * FROM users; WAITFOR DELAY '00:00:05'",
        ]

        for query in dangerous_queries:
            with pytest.raises(ToolError, match="injection attempt"):
                await tool._execute(query=query)

    async def test_file_operations_detected(self):
        """Test detection of file operations (data exfiltration)."""
        tool = TestDatabaseTool()

        dangerous_queries = [
            "SELECT * FROM users INTO OUTFILE '/tmp/dump.txt'",
            "SELECT LOAD_FILE('/etc/passwd')",
        ]

        for query in dangerous_queries:
            with pytest.raises(ToolError, match="file"):
                await tool._execute(query=query)

    async def test_detection_can_be_disabled(self):
        """Test that injection detection can be disabled."""
        tool = TestDatabaseTool(enable_injection_detection=False)

        # Should not raise even with dangerous query
        result = await tool._execute(query="SELECT * FROM users; DROP TABLE users;")
        assert result == [{"result": "ok"}]

    async def test_parameterized_query_recommended(self):
        """Test that error messages recommend parameterized queries."""
        tool = TestDatabaseTool()

        with pytest.raises(ToolError, match="Use parameterized queries"):
            await tool._execute(query="SELECT * FROM users WHERE name = '' + 'value'")
