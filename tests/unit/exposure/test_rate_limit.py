"""Tests for exposure/rest/middleware.py rate limiting."""

from __future__ import annotations

from fireflyframework_agentic.exposure.rest.middleware import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=10)
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is True

    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=10)
        limiter.is_allowed("c")
        limiter.is_allowed("c")
        assert limiter.is_allowed("c") is False

    def test_separate_keys(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=10)
        assert limiter.is_allowed("a") is True
        assert limiter.is_allowed("b") is True
        assert limiter.is_allowed("a") is False
