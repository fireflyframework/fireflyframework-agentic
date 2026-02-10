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

"""Tests for all nine built-in tools."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from fireflyframework_genai.exceptions import ToolError
from fireflyframework_genai.tools.builtins.calculator_tool import CalculatorTool
from fireflyframework_genai.tools.builtins.database import DatabaseTool
from fireflyframework_genai.tools.builtins.datetime_tool import DateTimeTool
from fireflyframework_genai.tools.builtins.filesystem import FileSystemTool
from fireflyframework_genai.tools.builtins.http import HttpTool
from fireflyframework_genai.tools.builtins.json_tool import JsonTool
from fireflyframework_genai.tools.builtins.search import SearchResult, SearchTool
from fireflyframework_genai.tools.builtins.shell import ShellTool
from fireflyframework_genai.tools.builtins.text_tool import TextTool

# ---------------------------------------------------------------------------
# DateTimeTool
# ---------------------------------------------------------------------------


class TestDateTimeTool:
    @pytest.fixture()
    def tool(self) -> DateTimeTool:
        return DateTimeTool()

    async def test_now_returns_iso_string(self, tool: DateTimeTool) -> None:
        result = await tool.execute(action="now")
        assert isinstance(result, str)
        # Should contain a date-like pattern
        assert re.match(r"\d{4}-\d{2}-\d{2}", result)

    async def test_date_action(self, tool: DateTimeTool) -> None:
        result = await tool.execute(action="date")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", result)

    async def test_time_action(self, tool: DateTimeTool) -> None:
        result = await tool.execute(action="time")
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", result)

    async def test_timestamp_action(self, tool: DateTimeTool) -> None:
        result = await tool.execute(action="timestamp")
        assert isinstance(result, float)
        assert result > 0

    async def test_timezones_action(self, tool: DateTimeTool) -> None:
        result = await tool.execute(action="timezones")
        assert isinstance(result, list)
        assert "UTC" in result

    async def test_custom_timezone(self, tool: DateTimeTool) -> None:
        result = await tool.execute(action="date", timezone="US/Eastern")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", result)

    async def test_custom_format(self, tool: DateTimeTool) -> None:
        result = await tool.execute(action="now", format="%Y/%m/%d")
        assert re.fullmatch(r"\d{4}/\d{2}/\d{2}", result)

    async def test_unknown_action_raises(self, tool: DateTimeTool) -> None:
        with pytest.raises(Exception, match="Unknown action"):
            await tool.execute(action="invalid")

    async def test_tool_metadata(self, tool: DateTimeTool) -> None:
        assert tool.name == "datetime"
        assert "datetime" in tool.tags
        assert len(tool.parameters) == 3


# ---------------------------------------------------------------------------
# JsonTool
# ---------------------------------------------------------------------------


class TestJsonTool:
    @pytest.fixture()
    def tool(self) -> JsonTool:
        return JsonTool()

    async def test_validate_valid_json(self, tool: JsonTool) -> None:
        result = await tool.execute(action="validate", data='{"key": "value"}')
        assert result["valid"] is True

    async def test_validate_invalid_json(self, tool: JsonTool) -> None:
        result = await tool.execute(action="validate", data="not json")
        assert result["valid"] is False
        assert "error" in result

    async def test_parse(self, tool: JsonTool) -> None:
        result = await tool.execute(action="parse", data='{"a": 1, "b": [2, 3]}')
        assert result == {"a": 1, "b": [2, 3]}

    async def test_extract_nested(self, tool: JsonTool) -> None:
        data = '{"address": {"city": "NYC", "zip": "10001"}}'
        result = await tool.execute(action="extract", data=data, path="address.city")
        assert result == "NYC"

    async def test_extract_list_index(self, tool: JsonTool) -> None:
        data = '{"items": ["a", "b", "c"]}'
        result = await tool.execute(action="extract", data=data, path="items.1")
        assert result == "b"

    async def test_extract_missing_key_raises(self, tool: JsonTool) -> None:
        with pytest.raises(Exception, match="not found"):
            await tool.execute(action="extract", data='{"a": 1}', path="b")

    async def test_format(self, tool: JsonTool) -> None:
        result = await tool.execute(action="format", data='{"a":1}')
        assert '"a": 1' in result
        assert "\n" in result  # pretty-printed

    async def test_keys(self, tool: JsonTool) -> None:
        result = await tool.execute(action="keys", data='{"x": 1, "y": 2, "z": 3}')
        assert result == ["x", "y", "z"]

    async def test_keys_non_object_raises(self, tool: JsonTool) -> None:
        with pytest.raises(Exception, match="JSON object"):
            await tool.execute(action="keys", data="[1, 2, 3]")

    async def test_unknown_action_raises(self, tool: JsonTool) -> None:
        with pytest.raises(Exception, match="Unknown action"):
            await tool.execute(action="invalid", data="{}")

    async def test_tool_metadata(self, tool: JsonTool) -> None:
        assert tool.name == "json"
        assert "json" in tool.tags


# ---------------------------------------------------------------------------
# TextTool
# ---------------------------------------------------------------------------


class TestTextTool:
    @pytest.fixture()
    def tool(self) -> TextTool:
        return TextTool()

    async def test_count_words(self, tool: TextTool) -> None:
        result = await tool.execute(action="count", text="hello world foo bar", unit="words")
        assert result == {"words": 4}

    async def test_count_chars(self, tool: TextTool) -> None:
        result = await tool.execute(action="count", text="abc", unit="chars")
        assert result == {"chars": 3}

    async def test_count_sentences(self, tool: TextTool) -> None:
        result = await tool.execute(action="count", text="Hello. World! Yes?", unit="sentences")
        assert result["sentences"] == 3

    async def test_count_lines(self, tool: TextTool) -> None:
        result = await tool.execute(action="count", text="line1\nline2\nline3", unit="lines")
        assert result == {"lines": 3}

    async def test_extract_emails(self, tool: TextTool) -> None:
        text = "Contact alice@example.com or bob@test.org for info"
        result = await tool.execute(action="extract", text=text, pattern=r"[\w.+-]+@[\w.-]+")
        assert result == ["alice@example.com", "bob@test.org"]

    async def test_truncate(self, tool: TextTool) -> None:
        text = "one two three four five six"
        result = await tool.execute(action="truncate", text=text, max_words=3)
        assert result == "one two three..."

    async def test_truncate_no_change(self, tool: TextTool) -> None:
        text = "one two"
        result = await tool.execute(action="truncate", text=text, max_words=10)
        assert result == "one two"

    async def test_replace(self, tool: TextTool) -> None:
        result = await tool.execute(action="replace", text="foo bar foo", pattern="foo", replacement="baz")
        assert result == "baz bar baz"

    async def test_split(self, tool: TextTool) -> None:
        result = await tool.execute(action="split", text="a,b,c", pattern=",")
        assert result == ["a", "b", "c"]

    async def test_unknown_action_raises(self, tool: TextTool) -> None:
        with pytest.raises(Exception, match="Unknown action"):
            await tool.execute(action="invalid", text="hi")

    async def test_tool_metadata(self, tool: TextTool) -> None:
        assert tool.name == "text"
        assert "text" in tool.tags


# ---------------------------------------------------------------------------
# CalculatorTool
# ---------------------------------------------------------------------------


class TestCalculatorTool:
    @pytest.fixture()
    def tool(self) -> CalculatorTool:
        return CalculatorTool()

    async def test_basic_arithmetic(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="2 + 3 * 4")
        assert result["result"] == 14

    async def test_division(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="10 / 4")
        assert result["result"] == 2.5

    async def test_floor_division(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="10 // 3")
        assert result["result"] == 3

    async def test_modulo(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="10 % 3")
        assert result["result"] == 1

    async def test_power(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="2 ** 10")
        assert result["result"] == 1024

    async def test_unary_negative(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="-5 + 3")
        assert result["result"] == -2

    async def test_math_constant_pi(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="pi * 2")
        assert abs(result["result"] - math.pi * 2) < 1e-10

    async def test_sqrt_function(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="sqrt(144)")
        assert result["result"] == 12.0

    async def test_nested_expression(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="(2 + 3) * (4 - 1)")
        assert result["result"] == 15

    async def test_invalid_expression_returns_error(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="2 +")
        assert "error" in result

    async def test_division_by_zero_returns_error(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="1 / 0")
        assert "error" in result

    async def test_disallowed_function_returns_error(self, tool: CalculatorTool) -> None:
        result = await tool.execute(expression="__import__('os')")
        assert "error" in result

    async def test_tool_metadata(self, tool: CalculatorTool) -> None:
        assert tool.name == "calculator"
        assert "math" in tool.tags
        assert "calculator" in tool.tags


# ---------------------------------------------------------------------------
# HttpTool - verify async threading wrapper
# ---------------------------------------------------------------------------


class TestHttpToolAsync:
    def test_has_do_request_method(self) -> None:
        """HttpTool should have a _do_request_urllib method for threaded execution."""
        tool = HttpTool(use_pool=False)
        assert hasattr(tool, "_do_request_urllib")
        assert callable(tool._do_request_urllib)

    def test_metadata(self) -> None:
        tool = HttpTool(use_pool=False)
        assert tool.name == "http"
        assert "http" in tool.tags

    async def test_get_request_via_mock(self) -> None:
        """Test that HttpTool makes a real GET via urllib and returns structured data."""
        tool = HttpTool(use_pool=False)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await tool.execute(url="https://example.com/api", method="GET")
        assert result["status"] == 200
        assert result["body"] == '{"ok": true}'

    async def test_post_request_via_mock(self) -> None:
        tool = HttpTool(use_pool=False)
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.headers = {}
        mock_resp.read.return_value = b"created"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await tool.execute(url="https://example.com/api", method="POST", body='{"x":1}')
        assert result["status"] == 201
        assert result["body"] == "created"

    async def test_default_headers_forwarded(self) -> None:
        tool = HttpTool(use_pool=False, default_headers={"Authorization": "Bearer test"})
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            await tool.execute(url="https://example.com")
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer test"


# ---------------------------------------------------------------------------
# FileSystemTool
# ---------------------------------------------------------------------------


class TestFileSystemTool:
    @pytest.fixture()
    def tool(self, tmp_path: Path) -> FileSystemTool:
        return FileSystemTool(base_dir=tmp_path)

    async def test_write_and_read(self, tool: FileSystemTool, tmp_path: Path) -> None:
        await tool.execute(action="write", path="hello.txt", content="Hello World")
        result = await tool.execute(action="read", path="hello.txt")
        assert result == "Hello World"

    async def test_write_creates_parents(self, tool: FileSystemTool, tmp_path: Path) -> None:
        await tool.execute(action="write", path="sub/dir/file.txt", content="nested")
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"

    async def test_list_directory(self, tool: FileSystemTool, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        result = await tool.execute(action="list", path=".")
        assert "a.txt" in result
        assert "b.txt" in result

    async def test_path_traversal_rejected(self, tool: FileSystemTool) -> None:
        with pytest.raises(ToolError, match="escapes the sandbox"):
            await tool.execute(action="read", path="../../etc/passwd")

    async def test_unknown_action_raises(self, tool: FileSystemTool) -> None:
        with pytest.raises(Exception, match="Unknown action"):
            await tool.execute(action="delete", path="x")

    def test_metadata(self, tool: FileSystemTool) -> None:
        assert tool.name == "filesystem"
        assert "filesystem" in tool.tags


# ---------------------------------------------------------------------------
# ShellTool
# ---------------------------------------------------------------------------


class TestShellTool:
    async def test_allowed_command(self) -> None:
        tool = ShellTool(allowed_commands=["echo"])
        result = await tool.execute(command="echo hello")
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    async def test_rejected_command(self) -> None:
        tool = ShellTool(allowed_commands=["echo"])
        with pytest.raises(ToolError, match="not in the allowed list"):
            await tool.execute(command="rm -rf /")

    async def test_empty_allowlist_rejects_all(self) -> None:
        tool = ShellTool(allowed_commands=[])
        with pytest.raises(ToolError, match="not in the allowed list"):
            await tool.execute(command="ls")

    async def test_empty_command_raises(self) -> None:
        tool = ShellTool(allowed_commands=["echo"])
        with pytest.raises(Exception, match="Empty command"):
            await tool.execute(command="")

    async def test_working_dir(self, tmp_path: Path) -> None:
        tool = ShellTool(allowed_commands=["pwd"], working_dir=tmp_path)
        result = await tool.execute(command="pwd")
        assert str(tmp_path) in result["stdout"]

    async def test_timeout(self) -> None:
        tool = ShellTool(allowed_commands=["sleep"], timeout=0.1)
        with pytest.raises(ToolError, match="timed out"):
            await tool.execute(command="sleep 10")

    def test_metadata(self) -> None:
        tool = ShellTool()
        assert tool.name == "shell"
        assert "shell" in tool.tags


# ---------------------------------------------------------------------------
# DatabaseTool (abstract — test via concrete subclass)
# ---------------------------------------------------------------------------


class _InMemoryDatabaseTool(DatabaseTool):
    """Minimal concrete implementation for testing base-class behaviour."""

    def __init__(self, *, data: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._data = data or []

    async def _execute_query(self, query: str, params: dict[str, Any] | None) -> list[dict[str, Any]]:
        return [{"query": query, "params": params, "rows": self._data}]


class TestDatabaseTool:
    async def test_select_allowed_in_read_only(self) -> None:
        tool = _InMemoryDatabaseTool(read_only=True, data=[{"id": 1}])
        result = await tool.execute(query="SELECT * FROM users", params=None)
        assert result[0]["rows"] == [{"id": 1}]

    async def test_with_query_allowed_in_read_only(self) -> None:
        tool = _InMemoryDatabaseTool(read_only=True)
        result = await tool.execute(query="WITH cte AS (SELECT 1) SELECT * FROM cte")
        assert result[0]["query"].startswith("WITH")

    async def test_write_rejected_in_read_only(self) -> None:
        tool = _InMemoryDatabaseTool(read_only=True)
        with pytest.raises(ToolError, match="read-only"):
            await tool.execute(query="INSERT INTO users VALUES (1, 'test')")

    async def test_delete_rejected_in_read_only(self) -> None:
        tool = _InMemoryDatabaseTool(read_only=True)
        with pytest.raises(ToolError, match="read-only"):
            await tool.execute(query="DELETE FROM users WHERE id = 1")

    async def test_write_allowed_when_not_read_only(self) -> None:
        tool = _InMemoryDatabaseTool(read_only=False)
        result = await tool.execute(query="INSERT INTO users VALUES (1, 'test')")
        assert result[0]["query"].startswith("INSERT")

    async def test_params_forwarded(self) -> None:
        tool = _InMemoryDatabaseTool(read_only=False)
        result = await tool.execute(query="SELECT * FROM users WHERE id = :id", params={"id": 42})
        assert result[0]["params"] == {"id": 42}

    def test_metadata(self) -> None:
        tool = _InMemoryDatabaseTool()
        assert tool.name == "database"
        assert "database" in tool.tags


# ---------------------------------------------------------------------------
# SearchTool (abstract — test via concrete subclass)
# ---------------------------------------------------------------------------


class _StubSearchTool(SearchTool):
    """Returns canned results for testing."""

    async def _search(self, query: str, max_results: int) -> list[SearchResult]:
        return [
            SearchResult(title=f"Result {i}", url=f"https://example.com/{i}", snippet=f"About {query}")
            for i in range(min(max_results, 3))
        ]


class TestSearchTool:
    async def test_returns_serialised_results(self) -> None:
        tool = _StubSearchTool(max_results=5)
        results = await tool.execute(query="python async")
        assert isinstance(results, list)
        assert len(results) == 3
        assert results[0]["title"] == "Result 0"
        assert results[0]["url"] == "https://example.com/0"
        assert "python async" in results[0]["snippet"]

    async def test_max_results_respected(self) -> None:
        tool = _StubSearchTool(max_results=1)
        results = await tool.execute(query="test")
        assert len(results) == 1

    def test_metadata(self) -> None:
        tool = _StubSearchTool()
        assert tool.name == "search"
        assert "search" in tool.tags


# ---------------------------------------------------------------------------
# BaseTool → Pydantic AI bridge (FireflyAgent._resolve_tools)
# ---------------------------------------------------------------------------


class TestResolveToolsBridge:
    """Verify that FireflyAgent auto-converts BaseTool/ToolKit to pydantic_ai.Tool."""

    def test_base_tool_converted(self) -> None:
        from pydantic_ai import Tool as PydanticTool

        from fireflyframework_genai.agents.base import FireflyAgent

        calc = CalculatorTool()
        resolved = FireflyAgent._resolve_tools([calc])
        assert len(resolved) == 1
        assert isinstance(resolved[0], PydanticTool)

    def test_toolkit_expanded(self) -> None:
        from pydantic_ai import Tool as PydanticTool

        from fireflyframework_genai.agents.base import FireflyAgent
        from fireflyframework_genai.tools.toolkit import ToolKit

        kit = ToolKit("utils", [DateTimeTool(), JsonTool()])
        resolved = FireflyAgent._resolve_tools([kit])
        assert len(resolved) == 2
        assert all(isinstance(t, PydanticTool) for t in resolved)

    def test_plain_function_passes_through(self) -> None:
        from fireflyframework_genai.agents.base import FireflyAgent

        async def my_tool(x: str) -> str:
            return x

        resolved = FireflyAgent._resolve_tools([my_tool])
        assert len(resolved) == 1
        assert resolved[0] is my_tool

    def test_mixed_tools(self) -> None:
        from pydantic_ai import Tool as PydanticTool

        from fireflyframework_genai.agents.base import FireflyAgent

        async def my_tool(x: str) -> str:
            return x

        resolved = FireflyAgent._resolve_tools([CalculatorTool(), my_tool])
        assert len(resolved) == 2
        assert isinstance(resolved[0], PydanticTool)
        assert resolved[1] is my_tool
