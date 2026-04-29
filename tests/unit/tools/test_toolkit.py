"""Tests for tools/toolkit.py and tools/decorators.py."""

from __future__ import annotations

from typing import Any

from fireflyframework_agentic.tools.base import BaseTool
from fireflyframework_agentic.tools.decorators import firefly_tool, guarded, retryable
from fireflyframework_agentic.tools.guards import ValidationGuard
from fireflyframework_agentic.tools.registry import ToolRegistry
from fireflyframework_agentic.tools.toolkit import ToolKit


class _DummyTool(BaseTool):
    async def _execute(self, **kwargs: Any) -> Any:
        return "ok"


class TestToolKit:
    def test_properties(self) -> None:
        tk = ToolKit("kit", [_DummyTool("a"), _DummyTool("b")], tags=["x"])
        assert tk.name == "kit"
        assert len(tk) == 2
        assert tk.tags == ["x"]

    def test_register_and_unregister_all(self) -> None:
        registry = ToolRegistry()
        tk = ToolKit("kit", [_DummyTool("a"), _DummyTool("b")])
        tk.register_all(registry)
        assert registry.has("a")
        assert registry.has("b")
        tk.unregister_all(registry)
        assert not registry.has("a")

    def test_as_pydantic_tools(self) -> None:
        tk = ToolKit("kit", [_DummyTool("a")])
        pt = tk.as_pydantic_tools()
        assert len(pt) == 1
        assert pt[0].name == "a"

    def test_tools_returns_copy(self) -> None:
        tk = ToolKit("kit", [_DummyTool("a")])
        tools = tk.tools
        tools.append(_DummyTool("b"))
        assert len(tk.tools) == 1


class TestFireflyToolDecorator:
    async def test_creates_tool(self) -> None:
        @firefly_tool("test-ft", auto_register=False)
        async def my_tool(query: str) -> str:
            return f"result: {query}"

        assert my_tool.name == "test-ft"
        result = await my_tool.execute(query="hello")
        assert result == "result: hello"


class TestGuardedDecorator:
    async def test_appends_guard(self) -> None:
        @guarded(ValidationGuard(required_keys=["x"]))
        @firefly_tool("test-guarded", auto_register=False)
        async def my_tool(x: str) -> str:
            return x

        assert len(my_tool.guards) == 1


class TestRetryableDecorator:
    async def test_retries_on_failure(self) -> None:
        call_count = 0

        @retryable(max_retries=2, backoff=0.001)
        @firefly_tool("test-retry", auto_register=False)
        async def flaky(**kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient")
            return "ok"

        result = await flaky.execute()
        assert result == "ok"
        assert call_count == 3
