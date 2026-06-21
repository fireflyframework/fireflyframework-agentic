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

"""CachedTool single-flights concurrent identical misses."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from fireflyframework_agentic.tools.cached import CachedTool


class _SlowTool:
    name = "slow"
    description = "an expensive tool"

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **kwargs: Any) -> str:
        self.calls += 1
        await asyncio.sleep(0.02)
        return "value"


@pytest.mark.asyncio
async def test_concurrent_misses_run_the_tool_once():
    tool = _SlowTool()
    cached = CachedTool(tool, ttl_seconds=60)
    results = await asyncio.gather(*[cached.execute(q="x") for _ in range(8)])
    assert results == ["value"] * 8
    assert tool.calls == 1  # stampede prevented — leader computed, followers awaited


@pytest.mark.asyncio
async def test_failure_does_not_cache_and_clears_inflight():
    class _Flaky:
        name = "flaky"
        description = "d"

        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, **kwargs: Any) -> str:
            self.calls += 1
            await asyncio.sleep(0.01)
            raise RuntimeError("boom")

    flaky = _Flaky()
    cached = CachedTool(flaky, ttl_seconds=60)
    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.gather(*[cached.execute(q="y") for _ in range(4)])
    # A subsequent call retries (the failure was not cached, in-flight cleared).
    with pytest.raises(RuntimeError):
        await cached.execute(q="y")
    assert cached.cache_size == 0
