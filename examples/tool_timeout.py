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

"""Tool timeout example — protecting against runaway tool execution.

Demonstrates:
- ``BaseTool(timeout=...)`` — per-tool execution timeout.
- ``ToolTimeoutError`` — raised when the timeout is exceeded.
- Graceful handling of timed-out tools.

Usage::

    uv run python examples/tool_timeout.py

.. note:: This example does NOT require an OpenAI API key.
"""

from __future__ import annotations

import asyncio

from fireflyframework_agentic.exceptions import ToolTimeoutError
from fireflyframework_agentic.tools.base import BaseTool


class FastTool(BaseTool):
    """A tool that completes quickly."""

    def __init__(self):
        super().__init__("fast_lookup", description="Returns instantly", timeout=2.0)

    async def _execute(self, *, query: str = "default") -> str:
        return f"Fast result for '{query}'"


class SlowTool(BaseTool):
    """A tool that simulates a long-running operation."""

    def __init__(self, sleep: float = 5.0, timeout: float = 0.5):
        super().__init__(
            "slow_api",
            description=f"Simulates a {sleep}s API call with {timeout}s timeout",
            timeout=timeout,
        )
        self._sleep = sleep

    async def _execute(self, *, query: str = "default") -> str:
        await asyncio.sleep(self._sleep)
        return f"Slow result for '{query}'"


class NoTimeoutTool(BaseTool):
    """A tool with no timeout configured (default behaviour)."""

    def __init__(self):
        super().__init__("no_timeout", description="No timeout set")

    async def _execute(self, *, query: str = "default") -> str:
        await asyncio.sleep(0.1)
        return f"No-timeout result for '{query}'"


async def main() -> None:
    # ── 1. Fast tool with generous timeout ───────────────────────────────
    print("=== Fast Tool (timeout=2.0s) ===\n")

    fast = FastTool()
    result = await fast.execute(query="hello")
    print(f"  Result: {result}")
    print(f"  Timeout: {fast._timeout}s")

    # ── 2. Slow tool that exceeds timeout ────────────────────────────────
    print("\n=== Slow Tool (sleep=5s, timeout=0.5s) ===\n")

    slow = SlowTool(sleep=5.0, timeout=0.5)
    try:
        await slow.execute(query="will-timeout")
        print("  ERROR: Should have raised ToolTimeoutError!")
    except ToolTimeoutError as e:
        print(f"  Caught ToolTimeoutError: {e}")
        print(f"  Tool name in error: {'slow_api' in str(e)}")

    # ── 3. Tool with no timeout ──────────────────────────────────────────
    print("\n=== No Timeout Tool ===\n")

    no_to = NoTimeoutTool()
    result = await no_to.execute(query="free")
    print(f"  Result: {result}")
    print(f"  Timeout: {no_to._timeout} (None = no limit)")

    # ── 4. Graceful error handling pattern ────────────────────────────────
    print("\n=== Graceful Timeout Handling ===\n")

    tools = [FastTool(), SlowTool(sleep=5.0, timeout=0.3), FastTool()]
    for tool in tools:
        try:
            result = await tool.execute(query="test")
            print(f"  ✔ {tool.name}: {result}")
        except ToolTimeoutError:
            print(f"  ✗ {tool.name}: timed out after {tool._timeout}s — using fallback")

    print("\nTool timeout demo complete.")


if __name__ == "__main__":
    asyncio.run(main())
