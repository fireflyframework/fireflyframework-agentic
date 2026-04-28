"""Tests for tool timeout functionality — BaseTool.timeout and ToolTimeoutError."""

from __future__ import annotations

import asyncio

import pytest

from fireflyframework_agentic.exceptions import ToolTimeoutError
from fireflyframework_agentic.tools.base import BaseTool


class _SlowTool(BaseTool):
    """Tool that sleeps for a configurable duration."""

    def __init__(self, sleep_seconds: float = 1.0, **kwargs):
        super().__init__("slow_tool", **kwargs)
        self._sleep = sleep_seconds

    async def _execute(self, **kwargs):
        await asyncio.sleep(self._sleep)
        return "done"


class _FastTool(BaseTool):
    """Tool that returns immediately."""

    def __init__(self, **kwargs):
        super().__init__("fast_tool", **kwargs)

    async def _execute(self, **kwargs):
        return "fast"


class TestToolTimeout:
    async def test_timeout_raises(self):
        tool = _SlowTool(sleep_seconds=5.0, timeout=0.05)
        with pytest.raises(ToolTimeoutError, match="timed out"):
            await tool.execute()

    async def test_no_timeout_succeeds(self):
        tool = _FastTool(timeout=1.0)
        result = await tool.execute()
        assert result == "fast"

    async def test_no_timeout_configured(self):
        tool = _FastTool()
        assert tool._timeout is None
        result = await tool.execute()
        assert result == "fast"


class TestToolTimeoutEdgeCases:
    async def test_zero_timeout_raises(self):
        """A timeout of 0.0 is essentially instant timeout, should raise."""
        tool = _SlowTool(sleep_seconds=1.0, timeout=0.0)
        with pytest.raises(ToolTimeoutError):
            await tool.execute()

    async def test_generous_timeout_succeeds(self):
        """A generous timeout should not interfere with fast tools."""
        tool = _FastTool(timeout=10.0)
        result = await tool.execute()
        assert result == "fast"

    async def test_timeout_error_message_contains_tool_name(self):
        tool = _SlowTool(sleep_seconds=5.0, timeout=0.01)
        with pytest.raises(ToolTimeoutError, match="slow_tool"):
            await tool.execute()
