"""Tests for tools/composer.py."""

from __future__ import annotations

from typing import Any

import pytest

from fireflyframework_agentic.exceptions import ToolError
from fireflyframework_agentic.tools.composer import (
    ConditionalComposer,
    FallbackComposer,
    SequentialComposer,
)


class _FakeTool:
    def __init__(self, name: str, return_value: Any = None, *, fail: bool = False) -> None:
        self.name = name
        self.description = f"Fake {name}"
        self._return_value = return_value
        self._fail = fail

    async def execute(self, **kwargs: Any) -> Any:
        if self._fail:
            raise ToolError(f"{self.name} failed")
        return self._return_value if self._return_value is not None else kwargs.get("input", "default")


class TestSequentialComposer:
    async def test_pipes_output_through_tools(self) -> None:
        t1 = _FakeTool("upper", return_value="HELLO")
        t2 = _FakeTool("suffix", return_value="HELLO!")
        composer = SequentialComposer("seq", [t1, t2])
        result = await composer.execute(input="hello")
        assert result == "HELLO!"
        assert composer.name == "seq"

    async def test_empty_tools_returns_none(self) -> None:
        composer = SequentialComposer("empty", [])
        result = await composer.execute(input="x")
        assert result is None


class TestFallbackComposer:
    async def test_returns_first_success(self) -> None:
        t1 = _FakeTool("bad", fail=True)
        t2 = _FakeTool("good", return_value="ok")
        composer = FallbackComposer("fb", [t1, t2])
        result = await composer.execute(input="x")
        assert result == "ok"

    async def test_raises_when_all_fail(self) -> None:
        t1 = _FakeTool("bad1", fail=True)
        t2 = _FakeTool("bad2", fail=True)
        composer = FallbackComposer("fb", [t1, t2])
        with pytest.raises(ToolError, match="All 2 fallback tools failed"):
            await composer.execute(input="x")


class TestConditionalComposer:
    async def test_routes_to_correct_tool(self) -> None:
        t1 = _FakeTool("a", return_value="A")
        t2 = _FakeTool("b", return_value="B")
        composer = ConditionalComposer(
            "cond",
            router_fn=lambda **kw: "b",
            tool_map={"a": t1, "b": t2},
        )
        result = await composer.execute(input="x")
        assert result == "B"

    async def test_raises_for_unknown_tool(self) -> None:
        composer = ConditionalComposer(
            "cond",
            router_fn=lambda **kw: "unknown",
            tool_map={"a": _FakeTool("a")},
        )
        with pytest.raises(ToolError, match="unknown"):
            await composer.execute(input="x")
