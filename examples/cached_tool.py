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

"""CachedTool example — transparent memoisation for deterministic tools.

Demonstrates:
- ``CachedTool`` wrapping a slow tool with TTL-based caching.
- Cache hits (same arguments) vs misses (different arguments).
- TTL expiry and re-execution.
- ``invalidate()`` and ``clear()`` for cache management.
- ``max_entries`` eviction.

Usage::

    uv run python examples/cached_tool.py

.. note:: This example does NOT require an OpenAI API key.
"""

from __future__ import annotations

import asyncio
import time


async def main() -> None:
    from fireflyframework_agentic.tools.cached import CachedTool

    # -- Define a "slow" tool that simulates network latency ------------------

    class SlowLookupTool:
        """Simulates an expensive lookup (e.g. database or API call)."""

        def __init__(self):
            self.call_count = 0

        @property
        def name(self) -> str:
            return "slow_lookup"

        @property
        def description(self) -> str:
            return "Looks up data (simulated 100ms latency)"

        async def execute(self, *, query: str) -> str:
            self.call_count += 1
            await asyncio.sleep(0.1)  # Simulate latency
            return f"Result for '{query}' (call #{self.call_count})"

    inner = SlowLookupTool()
    cached = CachedTool(inner, ttl_seconds=2.0, max_entries=3)

    # ── 1. Cache hit vs miss ────────────────────────────────────────────
    print("=== CachedTool: Hit vs Miss ===\n")

    t0 = time.perf_counter()
    r1 = await cached.execute(query="hello")
    t1 = time.perf_counter()
    print(f"  1st call: {r1}  ({(t1 - t0) * 1000:.0f}ms, call_count={inner.call_count})")

    t0 = time.perf_counter()
    r2 = await cached.execute(query="hello")
    t1 = time.perf_counter()
    print(f"  2nd call: {r2}  ({(t1 - t0) * 1000:.0f}ms, CACHE HIT, call_count={inner.call_count})")

    t0 = time.perf_counter()
    r3 = await cached.execute(query="world")
    t1 = time.perf_counter()
    print(f"  3rd call: {r3}  ({(t1 - t0) * 1000:.0f}ms, CACHE MISS, call_count={inner.call_count})")

    # ── 2. TTL expiry ───────────────────────────────────────────────────
    print("\n=== CachedTool: TTL Expiry ===\n")

    short_cached = CachedTool(inner, ttl_seconds=0.2)
    inner.call_count = 0

    await short_cached.execute(query="ttl-test")
    print(f"  Before TTL: call_count={inner.call_count}")

    await short_cached.execute(query="ttl-test")
    print(f"  Cache hit : call_count={inner.call_count}")

    await asyncio.sleep(0.25)  # Wait for TTL to expire

    await short_cached.execute(query="ttl-test")
    print(f"  After TTL : call_count={inner.call_count} (re-executed)")

    # ── 3. Invalidate and clear ─────────────────────────────────────────
    print("\n=== CachedTool: Cache Management ===\n")

    inner.call_count = 0
    mgmt = CachedTool(inner, ttl_seconds=60.0)

    await mgmt.execute(query="a")
    await mgmt.execute(query="b")
    print(f"  Cache size: {mgmt.cache_size} (entries)")

    removed = mgmt.invalidate(query="a")
    print(f"  Invalidated 'a': {removed}")
    print(f"  Cache size after invalidate: {mgmt.cache_size}")

    cleared = mgmt.clear()
    print(f"  Cleared {cleared} entries. Size: {mgmt.cache_size}")

    # ── 4. Max entries eviction ─────────────────────────────────────────
    print("\n=== CachedTool: Max Entries Eviction ===\n")

    inner.call_count = 0
    small = CachedTool(inner, ttl_seconds=60.0, max_entries=2)

    await small.execute(query="x")
    await small.execute(query="y")
    await small.execute(query="z")  # Evicts 'x'
    print(f"  After 3 distinct queries (max_entries=2): size={small.cache_size}")

    # 'x' was evicted — next call re-executes
    inner.call_count = 0
    await small.execute(query="x")
    print(f"  Re-fetching evicted 'x': call_count={inner.call_count}")

    print(f"\n  repr: {cached!r}")
    print("\nCachedTool demo complete.")


if __name__ == "__main__":
    asyncio.run(main())
