"""Tests for agents/cache.py."""

from __future__ import annotations

import time

from fireflyframework_agentic.agents.cache import ResultCache


class TestResultCache:
    def test_get_miss_returns_none(self) -> None:
        cache = ResultCache()
        assert cache.get("model", "prompt") is None

    def test_put_then_get(self) -> None:
        cache = ResultCache()
        cache.put("model", "prompt", "result")
        assert cache.get("model", "prompt") == "result"

    def test_ttl_expiry(self) -> None:
        cache = ResultCache(ttl_seconds=0.01)
        cache.put("m", "p", "v")
        time.sleep(0.02)
        assert cache.get("m", "p") is None

    def test_max_size_eviction(self) -> None:
        cache = ResultCache(max_size=2, ttl_seconds=0)
        cache.put("m", "a", 1)
        cache.put("m", "b", 2)
        cache.put("m", "c", 3)
        # 'a' should have been evicted (LRU)
        assert cache.get("m", "a") is None
        assert cache.get("m", "c") == 3

    def test_invalidate(self) -> None:
        cache = ResultCache()
        cache.put("m", "p", "v")
        assert cache.invalidate("m", "p") is True
        assert cache.get("m", "p") is None
        assert cache.invalidate("m", "p") is False

    def test_clear(self) -> None:
        cache = ResultCache()
        cache.put("m", "a", 1)
        cache.put("m", "b", 2)
        cache.clear()
        assert len(cache) == 0

    def test_stats(self) -> None:
        cache = ResultCache()
        cache.put("m", "p", "v")
        cache.get("m", "p")  # hit
        cache.get("m", "miss")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
