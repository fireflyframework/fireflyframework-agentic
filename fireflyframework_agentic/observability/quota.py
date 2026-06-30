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

"""API rate limit management.

This module provides production-grade rate limiting and adaptive backoff
for LLM API calls. Budget enforcement now lives in
:class:`fireflyframework_agentic.observability.budget.BudgetGate`; this module
only handles request-rate concerns.

Example:
    Basic rate-limit management::

        from fireflyframework_agentic.observability.quota import QuotaManager

        quota = QuotaManager(rate_limits={"openai:gpt-4o": 60})  # 60 req/min

        if not quota.check_rate_limit_available("openai:gpt-4o"):
            await asyncio.sleep(quota.get_backoff_delay("openai:gpt-4o"))

        quota.record_request("openai:gpt-4o")
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import defaultdict

from fireflyframework_agentic.config import get_config
from fireflyframework_agentic.exceptions import RateLimitError

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe sliding window rate limiter.

    Implements a sliding window algorithm to enforce rate limits per key
    (typically model or agent). Tracks timestamps of requests within a
    configurable time window.

    Parameters:
        max_requests: Maximum requests allowed per window.
        window_seconds: Time window duration in seconds.

    Example::

        limiter = RateLimiter(max_requests=60, window_seconds=60.0)

        if limiter.is_allowed("openai:gpt-4o"):
            # Make API call
            limiter.record("openai:gpt-4o")
        else:
            # Wait or reject request
            raise RateLimitError("Rate limit exceeded")
    """

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Check if a request is within the rate limit.

        Args:
            key: Identifier for the rate limit bucket (e.g., model name).

        Returns:
            True if request is allowed, False if rate limit would be exceeded.
        """
        with self._lock:
            now = time.monotonic()
            ts = self._timestamps[key]

            # Remove timestamps outside the window
            ts[:] = [t for t in ts if now - t < self._window]

            return len(ts) < self._max

    def record(self, key: str) -> None:
        """Record a request timestamp.

        Args:
            key: Identifier for the rate limit bucket.
        """
        with self._lock:
            now = time.monotonic()
            self._timestamps[key].append(now)

    def get_remaining(self, key: str) -> int:
        """Get the number of remaining requests in the current window.

        Args:
            key: Identifier for the rate limit bucket.

        Returns:
            Number of requests remaining before hitting the limit.
        """
        with self._lock:
            now = time.monotonic()
            ts = self._timestamps.get(key, [])
            ts[:] = [t for t in ts if now - t < self._window]
            return max(0, self._max - len(ts))

    def reset(self, key: str | None = None) -> None:
        """Reset rate limit counters.

        Args:
            key: If provided, reset only this key. If None, reset all keys.
        """
        with self._lock:
            if key is None:
                self._timestamps.clear()
            else:
                self._timestamps.pop(key, None)


class AdaptiveBackoff:
    """Adaptive exponential backoff for 429 (rate limit) responses.

    Implements exponential backoff with jitter for handling rate limit
    errors. Automatically increases backoff delay on consecutive failures
    and resets on success.

    Parameters:
        base_delay: Initial backoff delay in seconds.
        max_delay: Maximum backoff delay in seconds.
        multiplier: Exponential backoff multiplier.
        jitter: Whether to add random jitter (0-50% of delay).

    Example::

        backoff = AdaptiveBackoff(base_delay=1.0, max_delay=60.0)

        for attempt in range(max_retries):
            try:
                result = await make_api_call()
                backoff.reset("openai:gpt-4o")  # Success
                break
            except RateLimitError:
                backoff.record_failure("openai:gpt-4o")
                delay = backoff.get_delay("openai:gpt-4o")
                await asyncio.sleep(delay)
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        jitter: bool = True,
    ) -> None:
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._multiplier = multiplier
        self._jitter = jitter
        self._failure_counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def record_failure(self, key: str) -> None:
        """Record a rate limit failure.

        Args:
            key: Identifier for the backoff bucket (e.g., model name).
        """
        with self._lock:
            self._failure_counts[key] += 1
            logger.debug("Backoff failure recorded for %s (count=%d)", key, self._failure_counts[key])

    def reset(self, key: str) -> None:
        """Reset backoff counter after a successful request.

        Args:
            key: Identifier for the backoff bucket.
        """
        with self._lock:
            if key in self._failure_counts:
                del self._failure_counts[key]
                logger.debug("Backoff reset for %s", key)

    def get_delay(self, key: str) -> float:
        """Calculate the backoff delay for the current failure count.

        Args:
            key: Identifier for the backoff bucket.

        Returns:
            Backoff delay in seconds, with optional jitter.
        """
        with self._lock:
            failures = self._failure_counts.get(key, 0)

        # Exponential backoff: base * multiplier^(failures - 1)
        # First failure (failures=1) gives base_delay
        # Second failure (failures=2) gives base_delay * multiplier
        exponent = max(0, failures - 1)
        delay = min(self._base_delay * (self._multiplier**exponent), self._max_delay)

        # Add jitter: random value between 0% and 50% of delay
        if self._jitter:
            jitter_amount = delay * random.uniform(0.0, 0.5)
            delay += jitter_amount

        return delay

    def get_failure_count(self, key: str) -> int:
        """Get the current failure count for a key.

        Args:
            key: Identifier for the backoff bucket.

        Returns:
            Number of consecutive failures.
        """
        with self._lock:
            return self._failure_counts.get(key, 0)


class QuotaManager:
    """Per-model rate-limit and adaptive-backoff manager.

    Wraps :class:`RateLimiter` and :class:`AdaptiveBackoff` for production LLM
    deployments. Budget enforcement has moved to
    :class:`fireflyframework_agentic.observability.budget.BudgetGate`; this
    manager covers only request-rate concerns.

    Parameters:
        rate_limits: Per-model rate limits as ``{model: requests_per_minute}``.
        rate_limit_window: Time window for rate limiting in seconds.
        enable_adaptive_backoff: Whether to use adaptive backoff for 429s.
        backoff_base_delay: Base delay for exponential backoff.
        backoff_max_delay: Maximum backoff delay.

    Example::

        quota = QuotaManager(
            rate_limits={
                "openai:gpt-4o": 60,
                "openai:gpt-4o-mini": 200,
            }
        )

        # Before making request
        quota.check_quota_before_request("openai:gpt-4o")

        # After request completes
        quota.record_request("openai:gpt-4o", success=True)

        # On 429 error
        try:
            result = await call_api()
        except RateLimitError:
            quota.record_rate_limit_error("openai:gpt-4o")
            delay = quota.get_backoff_delay("openai:gpt-4o")
            await asyncio.sleep(delay)
    """

    def __init__(
        self,
        *,
        rate_limits: dict[str, int] | None = None,
        rate_limit_window: float = 60.0,
        enable_adaptive_backoff: bool = True,
        backoff_base_delay: float = 1.0,
        backoff_max_delay: float = 60.0,
    ) -> None:
        self._rate_limits = rate_limits or {}
        self._rate_limit_window = rate_limit_window

        # Rate limiters per model
        self._limiters: dict[str, RateLimiter] = {}
        for model, max_requests in self._rate_limits.items():
            self._limiters[model] = RateLimiter(
                max_requests=max_requests,
                window_seconds=rate_limit_window,
            )

        # Adaptive backoff
        self._enable_backoff = enable_adaptive_backoff
        self._backoff = (
            AdaptiveBackoff(
                base_delay=backoff_base_delay,
                max_delay=backoff_max_delay,
            )
            if enable_adaptive_backoff
            else None
        )

    @property
    def backoff(self) -> AdaptiveBackoff | None:
        """The shared :class:`AdaptiveBackoff`, or ``None`` when disabled."""
        return self._backoff

    def check_rate_limit_available(self, model: str) -> bool:
        """Check if a request is within the rate limit for the model.

        Args:
            model: Model identifier (e.g., "openai:gpt-4o").

        Returns:
            True if request is allowed, False if rate limit would be exceeded.
        """
        limiter = self._limiters.get(model)
        if limiter is None:
            return True  # No rate limit configured for this model

        return limiter.is_allowed(model)

    def check_quota_before_request(self, model: str) -> None:
        """Check rate-limit constraints before making a request.

        Raises:
            RateLimitError: If rate limit would be exceeded.

        Args:
            model: Model identifier.
        """
        if not self.check_rate_limit_available(model):
            raise RateLimitError(
                f"Rate limit exceeded for model '{model}'. "
                f"Limit: {self._rate_limits.get(model, 0)} requests/{self._rate_limit_window}s"
            )

    def record_request(self, model: str, success: bool = True) -> None:
        """Record a completed request.

        Args:
            model: Model identifier.
            success: Whether the request succeeded (used for backoff reset).
        """
        limiter = self._limiters.get(model)
        if limiter:
            limiter.record(model)

        # Reset backoff on success
        if success and self._backoff:
            self._backoff.reset(model)

    def record_rate_limit_error(self, model: str) -> None:
        """Record a 429 (rate limit) error for adaptive backoff.

        Args:
            model: Model identifier.
        """
        if self._backoff:
            self._backoff.record_failure(model)
            logger.warning(
                "Rate limit error (429) for model '%s'. Failure count: %d, Recommended backoff: %.2fs",
                model,
                self._backoff.get_failure_count(model),
                self._backoff.get_delay(model),
            )

    def get_backoff_delay(self, model: str) -> float:
        """Get the recommended backoff delay after a rate limit error.

        Args:
            model: Model identifier.

        Returns:
            Backoff delay in seconds. Returns 0.0 if adaptive backoff is disabled.
        """
        if not self._backoff:
            return 0.0

        return self._backoff.get_delay(model)

    def get_rate_limit_remaining(self, model: str) -> int | None:
        """Get the remaining requests for a model's rate limit.

        Args:
            model: Model identifier.

        Returns:
            Number of remaining requests, or None if no limit is configured.
        """
        limiter = self._limiters.get(model)
        if limiter is None:
            return None

        return limiter.get_remaining(model)

    def reset_rate_limits(self, model: str | None = None) -> None:
        """Reset rate limit counters.

        Args:
            model: If provided, reset only this model. If None, reset all models.
        """
        if model is None:
            for limiter in self._limiters.values():
                limiter.reset()
        else:
            limiter = self._limiters.get(model)
            if limiter:
                limiter.reset(model)


def create_quota_manager_from_config() -> QuotaManager | None:
    """Create a QuotaManager from framework configuration.

    Returns:
        QuotaManager instance if quota management is enabled, None otherwise.
    """
    cfg = get_config()

    if not cfg.quota_enabled:
        return None

    return QuotaManager(
        rate_limits=cfg.quota_rate_limits,
        enable_adaptive_backoff=cfg.quota_adaptive_backoff,
    )


# Module-level default instance
default_quota_manager: QuotaManager | None = create_quota_manager_from_config()
