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

"""Unit tests for quota management and rate limiting."""

from __future__ import annotations

import time

import pytest

from fireflyframework_agentic.exceptions import BudgetExceededError, RateLimitError
from fireflyframework_agentic.observability.quota import AdaptiveBackoff, QuotaManager, RateLimiter


class TestRateLimiter:
    """Test suite for RateLimiter."""

    def test_basic_rate_limit(self):
        """Test basic rate limiting functionality."""
        limiter = RateLimiter(max_requests=3, window_seconds=1.0)

        # First 3 requests should be allowed
        assert limiter.is_allowed("test_key")
        limiter.record("test_key")

        assert limiter.is_allowed("test_key")
        limiter.record("test_key")

        assert limiter.is_allowed("test_key")
        limiter.record("test_key")

        # 4th request should be denied
        assert not limiter.is_allowed("test_key")

    def test_sliding_window(self):
        """Test that rate limit resets after window expires."""
        limiter = RateLimiter(max_requests=2, window_seconds=0.2)

        # Use up the limit
        assert limiter.is_allowed("test_key")
        limiter.record("test_key")
        assert limiter.is_allowed("test_key")
        limiter.record("test_key")

        # Should be denied
        assert not limiter.is_allowed("test_key")

        # Wait for window to expire
        time.sleep(0.3)

        # Should be allowed again
        assert limiter.is_allowed("test_key")

    def test_independent_keys(self):
        """Test that different keys have independent rate limits."""
        limiter = RateLimiter(max_requests=1, window_seconds=1.0)

        # Use up key1's limit
        assert limiter.is_allowed("key1")
        limiter.record("key1")
        assert not limiter.is_allowed("key1")

        # key2 should still be available
        assert limiter.is_allowed("key2")
        limiter.record("key2")

    def test_get_remaining(self):
        """Test getting remaining request count."""
        limiter = RateLimiter(max_requests=5, window_seconds=1.0)

        assert limiter.get_remaining("test_key") == 5

        limiter.record("test_key")
        assert limiter.get_remaining("test_key") == 4

        limiter.record("test_key")
        assert limiter.get_remaining("test_key") == 3

    def test_reset(self):
        """Test resetting rate limit counters."""
        limiter = RateLimiter(max_requests=1, window_seconds=1.0)

        # Use up the limit
        limiter.record("test_key")
        assert not limiter.is_allowed("test_key")

        # Reset
        limiter.reset("test_key")
        assert limiter.is_allowed("test_key")

    def test_reset_all(self):
        """Test resetting all rate limit counters."""
        limiter = RateLimiter(max_requests=1, window_seconds=1.0)

        # Use up limits for multiple keys
        limiter.record("key1")
        limiter.record("key2")

        # Reset all
        limiter.reset()

        assert limiter.is_allowed("key1")
        assert limiter.is_allowed("key2")


class TestAdaptiveBackoff:
    """Test suite for AdaptiveBackoff."""

    def test_initial_delay(self):
        """Test that initial delay is the base delay."""
        backoff = AdaptiveBackoff(base_delay=1.0, jitter=False)

        backoff.record_failure("test_key")
        delay = backoff.get_delay("test_key")

        assert delay == 1.0

    def test_exponential_increase(self):
        """Test that delay increases exponentially."""
        backoff = AdaptiveBackoff(base_delay=1.0, multiplier=2.0, jitter=False)

        # Record multiple failures
        backoff.record_failure("test_key")  # delay = 1.0
        assert backoff.get_delay("test_key") == 1.0

        backoff.record_failure("test_key")  # delay = 2.0
        assert backoff.get_delay("test_key") == 2.0

        backoff.record_failure("test_key")  # delay = 4.0
        assert backoff.get_delay("test_key") == 4.0

    def test_max_delay_cap(self):
        """Test that delay is capped at max_delay."""
        backoff = AdaptiveBackoff(base_delay=1.0, max_delay=5.0, multiplier=2.0, jitter=False)

        # Record many failures
        for _ in range(10):
            backoff.record_failure("test_key")

        delay = backoff.get_delay("test_key")
        assert delay <= 5.0

    def test_jitter(self):
        """Test that jitter adds randomness to delay."""
        backoff = AdaptiveBackoff(base_delay=1.0, jitter=True)

        backoff.record_failure("test_key")

        # With jitter, delays should vary
        delays = [backoff.get_delay("test_key") for _ in range(10)]
        assert len(set(delays)) > 1  # Should have different values

        # All delays should be in reasonable range (1.0 to 1.5)
        for delay in delays:
            assert 1.0 <= delay <= 1.5

    def test_reset(self):
        """Test that reset clears failure count."""
        backoff = AdaptiveBackoff(base_delay=1.0, multiplier=2.0, jitter=False)

        # Record failures
        backoff.record_failure("test_key")
        backoff.record_failure("test_key")
        assert backoff.get_failure_count("test_key") == 2

        # Reset
        backoff.reset("test_key")
        assert backoff.get_failure_count("test_key") == 0

        # Next failure should start from base delay
        backoff.record_failure("test_key")
        assert backoff.get_delay("test_key") == 1.0

    def test_independent_keys(self):
        """Test that different keys have independent backoff."""
        backoff = AdaptiveBackoff(base_delay=1.0, multiplier=2.0, jitter=False)

        # Record failures for key1
        backoff.record_failure("key1")
        backoff.record_failure("key1")
        assert backoff.get_delay("key1") == 2.0

        # key2 should start from base delay
        backoff.record_failure("key2")
        assert backoff.get_delay("key2") == 1.0


class TestQuotaManager:
    """Test suite for QuotaManager."""

    def test_budget_check(self):
        """Test daily budget checking."""
        quota = QuotaManager(daily_budget_usd=10.0)

        # Should allow requests within budget
        assert quota.check_budget_available(5.0)
        assert quota.check_budget_available(10.0)

        # Should deny requests exceeding budget
        assert not quota.check_budget_available(10.01)

    def test_budget_enforcement(self):
        """Test that budget is enforced on check_quota_before_request."""
        quota = QuotaManager(daily_budget_usd=10.0)

        # First request should succeed
        quota.check_quota_before_request("openai:gpt-4o", estimated_cost=5.0)
        quota.record_request("openai:gpt-4o", cost_usd=5.0)

        # Second request that would exceed budget should raise exception
        with pytest.raises(BudgetExceededError, match="Daily budget.*would be exceeded"):
            quota.check_quota_before_request("openai:gpt-4o", estimated_cost=6.0)

    def test_budget_tracking(self):
        """Test that actual costs are tracked correctly."""
        quota = QuotaManager(daily_budget_usd=10.0)

        # Record some requests
        quota.record_request("openai:gpt-4o", cost_usd=3.0)
        assert quota.get_daily_spend() == 3.0

        quota.record_request("openai:gpt-4o", cost_usd=2.0)
        assert quota.get_daily_spend() == 5.0

        # Remaining budget should be correct
        assert quota.get_budget_remaining() == 5.0

    def test_no_budget_limit(self):
        """Test that None budget allows unlimited spending."""
        quota = QuotaManager(daily_budget_usd=None)

        # Should allow any amount
        assert quota.check_budget_available(1000000.0)
        assert quota.get_budget_remaining() is None

    def test_rate_limit_check(self):
        """Test rate limit checking."""
        quota = QuotaManager(rate_limits={"openai:gpt-4o": 3})

        # First 3 requests should be allowed
        assert quota.check_rate_limit_available("openai:gpt-4o")
        quota.record_request("openai:gpt-4o", cost_usd=0.0)

        assert quota.check_rate_limit_available("openai:gpt-4o")
        quota.record_request("openai:gpt-4o", cost_usd=0.0)

        assert quota.check_rate_limit_available("openai:gpt-4o")
        quota.record_request("openai:gpt-4o", cost_usd=0.0)

        # 4th request should be denied
        assert not quota.check_rate_limit_available("openai:gpt-4o")

    def test_rate_limit_enforcement(self):
        """Test that rate limits are enforced on check_quota_before_request."""
        quota = QuotaManager(rate_limits={"openai:gpt-4o": 1})

        # First request should succeed
        quota.check_quota_before_request("openai:gpt-4o")
        quota.record_request("openai:gpt-4o", cost_usd=0.0)

        # Second request should raise exception
        with pytest.raises(RateLimitError, match="Rate limit exceeded"):
            quota.check_quota_before_request("openai:gpt-4o")

    def test_no_rate_limit_for_unconfigured_model(self):
        """Test that models without rate limits are unrestricted."""
        quota = QuotaManager(rate_limits={"openai:gpt-4o": 1})

        # Model without rate limit should always be allowed
        for _ in range(100):
            assert quota.check_rate_limit_available("anthropic:claude-3-5-sonnet")

    def test_get_rate_limit_remaining(self):
        """Test getting remaining rate limit count."""
        quota = QuotaManager(rate_limits={"openai:gpt-4o": 5})

        assert quota.get_rate_limit_remaining("openai:gpt-4o") == 5

        quota.record_request("openai:gpt-4o", cost_usd=0.0)
        assert quota.get_rate_limit_remaining("openai:gpt-4o") == 4

        # Unconfigured model should return None
        assert quota.get_rate_limit_remaining("other:model") is None

    def test_adaptive_backoff_integration(self):
        """Test that adaptive backoff is applied for 429 errors."""
        quota = QuotaManager(enable_adaptive_backoff=True)

        # Record rate limit error
        quota.record_rate_limit_error("openai:gpt-4o")

        # Should recommend a backoff delay
        delay1 = quota.get_backoff_delay("openai:gpt-4o")
        assert delay1 > 0.0

        # Record another error
        quota.record_rate_limit_error("openai:gpt-4o")

        # Delay should increase
        delay2 = quota.get_backoff_delay("openai:gpt-4o")
        assert delay2 > delay1

    def test_backoff_reset_on_success(self):
        """Test that backoff resets after successful request."""
        quota = QuotaManager(enable_adaptive_backoff=True)

        # Record failures
        quota.record_rate_limit_error("openai:gpt-4o")
        quota.record_rate_limit_error("openai:gpt-4o")
        initial_delay = quota.get_backoff_delay("openai:gpt-4o")

        # Record successful request
        quota.record_request("openai:gpt-4o", cost_usd=0.0, success=True)

        # Record new failure - should start from base delay
        quota.record_rate_limit_error("openai:gpt-4o")
        reset_delay = quota.get_backoff_delay("openai:gpt-4o")
        assert reset_delay < initial_delay

    def test_backoff_disabled(self):
        """Test that backoff can be disabled."""
        quota = QuotaManager(enable_adaptive_backoff=False)

        # Record rate limit error
        quota.record_rate_limit_error("openai:gpt-4o")

        # Should return 0 delay
        assert quota.get_backoff_delay("openai:gpt-4o") == 0.0

    def test_reset_daily_spend(self):
        """Test manual reset of daily spend."""
        quota = QuotaManager(daily_budget_usd=10.0)

        quota.record_request("openai:gpt-4o", cost_usd=5.0)
        assert quota.get_daily_spend() == 5.0

        quota.reset_daily_spend()
        assert quota.get_daily_spend() == 0.0

    def test_reset_rate_limits(self):
        """Test manual reset of rate limits."""
        quota = QuotaManager(rate_limits={"openai:gpt-4o": 1})

        # Use up rate limit
        quota.record_request("openai:gpt-4o", cost_usd=0.0)
        assert not quota.check_rate_limit_available("openai:gpt-4o")

        # Reset specific model
        quota.reset_rate_limits("openai:gpt-4o")
        assert quota.check_rate_limit_available("openai:gpt-4o")

    def test_combined_quota_check(self):
        """Test that check_quota_before_request validates all constraints."""
        quota = QuotaManager(daily_budget_usd=10.0, rate_limits={"openai:gpt-4o": 1})

        # First request should succeed (both budget and rate limit OK)
        quota.check_quota_before_request("openai:gpt-4o", estimated_cost=2.0)
        quota.record_request("openai:gpt-4o", cost_usd=2.0)

        # Second request should fail rate limit
        with pytest.raises(RateLimitError):
            quota.check_quota_before_request("openai:gpt-4o", estimated_cost=2.0)

        # Reset rate limit
        quota.reset_rate_limits()

        # Third request should fail budget
        with pytest.raises(BudgetExceededError):
            quota.check_quota_before_request("openai:gpt-4o", estimated_cost=9.0)
