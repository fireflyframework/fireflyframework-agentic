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

"""API quota and rate limit management.

This module provides production-grade quota enforcement, rate limiting,
and adaptive backoff for LLM API calls. It integrates with the existing
:class:`~fireflyframework_genai.observability.usage.UsageTracker` to enforce:

- **Daily budget limits** in USD
- **Per-model rate limits** (requests per minute)
- **Adaptive backoff** for 429 (rate limit) responses
- **Token quota** tracking across agents

Example:
    Basic quota management::

        from fireflyframework_genai.observability.quota import QuotaManager

        quota = QuotaManager(
            daily_budget_usd=10.0,
            rate_limits={"openai:gpt-4o": 60}  # 60 req/min
        )

        # Check before making request
        if not quota.check_budget_available(cost_usd=0.05):
            raise QuotaError("Daily budget exceeded")

        if not quota.check_rate_limit_available("openai:gpt-4o"):
            # Apply adaptive backoff
            await asyncio.sleep(quota.get_backoff_delay("openai:gpt-4o"))

        # Record usage after request
        quota.record_request("openai:gpt-4o", cost_usd=0.05)
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import defaultdict
from datetime import UTC, date, datetime

from fireflyframework_genai.exceptions import BudgetExceededError, RateLimitError

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
    """Comprehensive quota and rate limit manager.

    Manages daily budget limits, per-model rate limits, and adaptive backoff
    for production LLM deployments. Integrates with UsageTracker for cost
    tracking and enforces hard limits.

    Parameters:
        daily_budget_usd: Maximum daily spending in USD. None = no limit.
        rate_limits: Per-model rate limits as ``{model: requests_per_minute}``.
        rate_limit_window: Time window for rate limiting in seconds.
        enable_adaptive_backoff: Whether to use adaptive backoff for 429s.
        backoff_base_delay: Base delay for exponential backoff.
        backoff_max_delay: Maximum backoff delay.

    Example::

        quota = QuotaManager(
            daily_budget_usd=100.0,
            rate_limits={
                "openai:gpt-4o": 60,
                "openai:gpt-4o-mini": 200,
            }
        )

        # Before making request
        quota.check_quota_before_request("openai:gpt-4o", estimated_cost=0.05)

        # After request completes
        quota.record_request("openai:gpt-4o", cost_usd=0.048, success=True)

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
        daily_budget_usd: float | None = None,
        rate_limits: dict[str, int] | None = None,
        rate_limit_window: float = 60.0,
        enable_adaptive_backoff: bool = True,
        backoff_base_delay: float = 1.0,
        backoff_max_delay: float = 60.0,
    ) -> None:
        self._daily_budget = daily_budget_usd
        self._rate_limits = rate_limits or {}
        self._rate_limit_window = rate_limit_window

        # Daily spend tracking
        self._daily_spend: float = 0.0
        self._spend_reset_date: date = datetime.now(UTC).date()
        self._spend_lock = threading.Lock()

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

    def check_budget_available(self, cost_usd: float) -> bool:
        """Check if the daily budget has room for the estimated cost.

        Args:
            cost_usd: Estimated cost of the request in USD.

        Returns:
            True if budget is available, False if exceeded.
        """
        if self._daily_budget is None:
            return True

        with self._spend_lock:
            self._maybe_reset_daily_spend()
            return self._daily_spend + cost_usd <= self._daily_budget

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

    def check_quota_before_request(self, model: str, estimated_cost: float = 0.0) -> None:
        """Check all quota constraints before making a request.

        Raises:
            BudgetExceededError: If daily budget would be exceeded.
            RateLimitError: If rate limit would be exceeded.

        Args:
            model: Model identifier.
            estimated_cost: Estimated cost of the request in USD.
        """
        # Check budget
        if not self.check_budget_available(estimated_cost):
            raise BudgetExceededError(
                f"Daily budget of ${self._daily_budget:.2f} would be exceeded. "
                f"Current spend: ${self._daily_spend:.2f}, "
                f"Requested: ${estimated_cost:.2f}"
            )

        # Check rate limit
        if not self.check_rate_limit_available(model):
            raise RateLimitError(
                f"Rate limit exceeded for model '{model}'. "
                f"Limit: {self._rate_limits.get(model, 0)} requests/{self._rate_limit_window}s"
            )

    def record_request(self, model: str, cost_usd: float, success: bool = True) -> None:
        """Record a completed request.

        Args:
            model: Model identifier.
            cost_usd: Actual cost of the request in USD.
            success: Whether the request succeeded (used for backoff reset).
        """
        # Record cost
        with self._spend_lock:
            self._maybe_reset_daily_spend()
            self._daily_spend += cost_usd

        # Record rate limit
        limiter = self._limiters.get(model)
        if limiter:
            limiter.record(model)

        # Reset backoff on success
        if success and self._backoff:
            self._backoff.reset(model)

        logger.debug(
            "Quota: recorded request for %s (cost=$%.4f, daily_spend=$%.4f/%s)",
            model,
            cost_usd,
            self._daily_spend,
            f"${self._daily_budget:.2f}" if self._daily_budget else "unlimited",
        )

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

    def get_daily_spend(self) -> float:
        """Get the current daily spend.

        Returns:
            Total spend for the current day in USD.
        """
        with self._spend_lock:
            self._maybe_reset_daily_spend()
            return self._daily_spend

    def get_budget_remaining(self) -> float | None:
        """Get the remaining daily budget.

        Returns:
            Remaining budget in USD, or None if no budget is configured.
        """
        if self._daily_budget is None:
            return None

        with self._spend_lock:
            self._maybe_reset_daily_spend()
            return max(0.0, self._daily_budget - self._daily_spend)

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

    def reset_daily_spend(self) -> None:
        """Manually reset the daily spend counter (for testing)."""
        with self._spend_lock:
            self._daily_spend = 0.0
            self._spend_reset_date = datetime.now(UTC).date()

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

    def _maybe_reset_daily_spend(self) -> None:
        """Reset daily spend if a new day has started (internal, not thread-safe)."""
        today = datetime.now(UTC).date()
        if today > self._spend_reset_date:
            logger.info(
                "Daily spend reset: $%.4f -> $0.00 (new day: %s)",
                self._daily_spend,
                today.isoformat(),
            )
            self._daily_spend = 0.0
            self._spend_reset_date = today


def create_quota_manager_from_config() -> QuotaManager | None:
    """Create a QuotaManager from framework configuration.

    Returns:
        QuotaManager instance if quota management is enabled, None otherwise.
    """
    from fireflyframework_genai.config import get_config

    cfg = get_config()

    if not cfg.quota_enabled:
        return None

    return QuotaManager(
        daily_budget_usd=cfg.quota_budget_daily_usd,
        rate_limits=cfg.quota_rate_limits,
        enable_adaptive_backoff=cfg.quota_adaptive_backoff,
    )


# Module-level default instance
default_quota_manager: QuotaManager | None = create_quota_manager_from_config()
