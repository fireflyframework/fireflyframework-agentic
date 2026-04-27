"""Tests for tools/cached.py — CachedTool wrapper."""

from __future__ import annotations

import asyncio
import time

from fireflyframework_agentic.tools.cached import CachedTool, _CacheEntry


class _CounterTool:
    """Tool that counts how many times it has been executed."""

    def __init__(self):
        self.call_count = 0

    @property
    def name(self) -> str:
        return "counter"

    @property
    def description(self) -> str:
        return "counts calls"

    async def execute(self, **kwargs):
        self.call_count += 1
        return f"result-{self.call_count}"


class TestCachedTool:
    async def test_cache_hit(self):
        inner = _CounterTool()
        cached = CachedTool(inner, ttl_seconds=60)
        r1 = await cached.execute(q="hello")
        r2 = await cached.execute(q="hello")
        assert r1 == r2 == "result-1"
        assert inner.call_count == 1  # Only called once

    async def test_cache_miss_different_args(self):
        inner = _CounterTool()
        cached = CachedTool(inner, ttl_seconds=60)
        r1 = await cached.execute(q="a")
        r2 = await cached.execute(q="b")
        assert r1 == "result-1"
        assert r2 == "result-2"
        assert inner.call_count == 2

    async def test_ttl_expiry(self):
        inner = _CounterTool()
        cached = CachedTool(inner, ttl_seconds=0.01)
        await cached.execute(q="x")
        await asyncio.sleep(0.02)  # Wait for TTL
        await cached.execute(q="x")
        assert inner.call_count == 2  # Cache expired, called again

    async def test_zero_ttl_passthrough(self):
        inner = _CounterTool()
        cached = CachedTool(inner, ttl_seconds=0)
        await cached.execute(q="x")
        await cached.execute(q="x")
        assert inner.call_count == 2  # No caching

    async def test_max_entries_eviction(self):
        inner = _CounterTool()
        cached = CachedTool(inner, ttl_seconds=60, max_entries=2)
        await cached.execute(q="a")
        await cached.execute(q="b")
        await cached.execute(q="c")  # Evicts 'a'
        assert cached.cache_size == 2

        # 'a' was evicted; calling it again re-executes
        inner.call_count = 0
        await cached.execute(q="a")
        assert inner.call_count == 1

    def test_invalidate(self):
        inner = _CounterTool()
        cached = CachedTool(inner, ttl_seconds=60)
        key = cached._make_key({"q": "hello"})
        cached._cache[key] = _CacheEntry("cached-val", time.monotonic() + 60)
        assert cached.invalidate(q="hello") is True
        assert cached.invalidate(q="hello") is False  # Already gone

    def test_clear(self):
        inner = _CounterTool()
        cached = CachedTool(inner, ttl_seconds=60)
        key = cached._make_key({"q": "x"})
        cached._cache[key] = _CacheEntry("v", time.monotonic() + 60)
        assert cached.clear() == 1
        assert cached.cache_size == 0

    def test_name_and_description_delegated(self):
        inner = _CounterTool()
        cached = CachedTool(inner)
        assert cached.name == "counter"
        assert cached.description == "counts calls"

    def test_repr(self):
        inner = _CounterTool()
        cached = CachedTool(inner, ttl_seconds=120)
        assert "CachedTool" in repr(cached)
        assert "120" in repr(cached)

    def test_import_from_package(self):
        from fireflyframework_agentic.tools import CachedTool as CachedToolAlias

        assert CachedToolAlias is CachedTool
