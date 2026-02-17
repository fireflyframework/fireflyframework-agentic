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

"""Unit tests for prompt caching middleware."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from fireflyframework_genai.agents.prompt_cache import CacheStatistics, PromptCacheMiddleware


@pytest.mark.asyncio
class TestPromptCacheMiddleware:
    """Test suite for prompt caching middleware."""

    async def test_middleware_initialization(self):
        """Test PromptCacheMiddleware initialization with defaults."""
        middleware = PromptCacheMiddleware()

        assert middleware._cache_system_prompt is True
        assert middleware._cache_min_tokens == 1024
        assert middleware._cache_ttl_seconds == 300
        assert middleware._enabled is True

    async def test_middleware_custom_parameters(self):
        """Test PromptCacheMiddleware with custom parameters."""
        middleware = PromptCacheMiddleware(
            cache_system_prompt=False,
            cache_min_tokens=2048,
            cache_ttl_seconds=600,
            enabled=False,
        )

        assert middleware._cache_system_prompt is False
        assert middleware._cache_min_tokens == 2048
        assert middleware._cache_ttl_seconds == 600
        assert middleware._enabled is False

    async def test_before_hook_with_disabled_middleware(self):
        """Test that disabled middleware does nothing."""
        middleware = PromptCacheMiddleware(enabled=False)

        context = Mock()
        context.model = "anthropic:claude-3-5-sonnet-20241022"

        # Should not raise or modify context
        await middleware.before(context)

    async def test_before_hook_anthropic_caching(self):
        """Test Anthropic-specific caching configuration."""
        middleware = PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_min_tokens=2048,
        )

        context = Mock()
        context.model = "anthropic:claude-3-5-sonnet-20241022"
        context.metadata = {}

        await middleware.before(context)

        # Should configure caching metadata
        assert context.metadata["_prompt_cache_enabled"] is True
        assert context.metadata["_cache_min_tokens"] == 2048

    async def test_before_hook_openai_caching(self):
        """Test OpenAI-specific caching configuration."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = "openai:gpt-4o"

        # Should not raise (OpenAI caching is automatic)
        await middleware.before(context)

    async def test_before_hook_gemini_caching(self):
        """Test Gemini-specific caching configuration."""
        middleware = PromptCacheMiddleware(cache_ttl_seconds=600)

        context = Mock()
        context.model = "gemini:gemini-1.5-pro"
        context.metadata = {}

        await middleware.before(context)

        # Should configure Gemini caching
        assert context.metadata["_gemini_cache_enabled"] is True
        assert context.metadata["_cache_ttl_seconds"] == 600

    async def test_before_hook_bedrock_anthropic_routes_to_anthropic_caching(self):
        """Bedrock-hosted Claude should route to Anthropic caching."""
        middleware = PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_min_tokens=2048,
        )

        context = Mock()
        context.model = "bedrock:anthropic.claude-3-5-sonnet-latest"
        context.metadata = {}

        await middleware.before(context)

        assert context.metadata["_prompt_cache_enabled"] is True
        assert context.metadata["_cache_min_tokens"] == 2048

    async def test_before_hook_azure_openai_routes_to_openai_caching(self):
        """Azure-hosted GPT should route to OpenAI caching."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = "azure:gpt-4o"

        # Should not raise (OpenAI caching is automatic)
        await middleware.before(context)

    async def test_before_hook_unsupported_provider(self):
        """Test behavior with unsupported provider."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = "unknown:model"

        # Should not raise, just log debug message
        await middleware.before(context)

    async def test_before_hook_no_model(self):
        """Test behavior when model is not set."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = ""

        # Should not raise
        await middleware.before(context)

    async def test_after_hook_with_cache_usage(self):
        """Test after hook records cache usage metrics."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        result = Mock()

        # Mock usage with cache metrics
        usage = Mock()
        usage.cache_creation_tokens = 5000
        usage.cache_read_tokens = 0
        result.usage = Mock(return_value=usage)

        returned_result = await middleware.after(context, result)

        # Should return unchanged result
        assert returned_result == result

    async def test_after_hook_with_cache_hits(self):
        """Test after hook with cache hit metrics."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        result = Mock()

        # Mock usage with cache read
        usage = Mock()
        usage.cache_creation_tokens = 0
        usage.cache_read_tokens = 5000
        result.usage = Mock(return_value=usage)

        returned_result = await middleware.after(context, result)

        assert returned_result == result

    async def test_after_hook_no_usage(self):
        """Test after hook when result has no usage."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        result = Mock(spec=[])  # No usage method

        # Should not raise
        returned_result = await middleware.after(context, result)
        assert returned_result == result

    async def test_after_hook_disabled(self):
        """Test that disabled middleware skips after hook."""
        middleware = PromptCacheMiddleware(enabled=False)

        context = Mock()
        result = Mock()

        returned_result = await middleware.after(context, result)

        # Should return result unchanged
        assert returned_result == result

    async def test_cache_system_prompt_disabled(self):
        """Test middleware with system prompt caching disabled."""
        middleware = PromptCacheMiddleware(cache_system_prompt=False)

        context = Mock()
        context.model = "anthropic:claude-3-5-sonnet-20241022"

        # Should not configure caching
        await middleware.before(context)


class TestCacheStatistics:
    """Test suite for cache statistics tracking."""

    def test_cache_statistics_initialization(self):
        """Test CacheStatistics initialization."""
        stats = CacheStatistics()

        assert stats._total_cache_creation_tokens == 0
        assert stats._total_cache_read_tokens == 0
        assert stats._request_count == 0
        assert stats._cache_hit_count == 0

    def test_record_usage_creation(self):
        """Test recording cache creation."""
        stats = CacheStatistics()

        stats.record_usage(cache_creation_tokens=5000, cache_read_tokens=0)

        assert stats._total_cache_creation_tokens == 5000
        assert stats._total_cache_read_tokens == 0
        assert stats._request_count == 1
        assert stats._cache_hit_count == 0

    def test_record_usage_hit(self):
        """Test recording cache hit."""
        stats = CacheStatistics()

        stats.record_usage(cache_creation_tokens=0, cache_read_tokens=5000)

        assert stats._total_cache_creation_tokens == 0
        assert stats._total_cache_read_tokens == 5000
        assert stats._request_count == 1
        assert stats._cache_hit_count == 1

    def test_cache_hit_rate_calculation(self):
        """Test cache hit rate calculation."""
        stats = CacheStatistics()

        # First request: cache miss (creation)
        stats.record_usage(cache_creation_tokens=5000, cache_read_tokens=0)

        # Next 3 requests: cache hits
        stats.record_usage(cache_creation_tokens=0, cache_read_tokens=5000)
        stats.record_usage(cache_creation_tokens=0, cache_read_tokens=5000)
        stats.record_usage(cache_creation_tokens=0, cache_read_tokens=5000)

        # Hit rate should be 3/4 = 75%
        assert stats.cache_hit_rate() == 0.75

    def test_cache_hit_rate_no_requests(self):
        """Test cache hit rate with no requests."""
        stats = CacheStatistics()

        assert stats.cache_hit_rate() == 0.0

    def test_estimated_savings_calculation(self):
        """Test estimated savings calculation."""
        stats = CacheStatistics()

        # First request: create 10,000 token cache
        stats.record_usage(cache_creation_tokens=10000, cache_read_tokens=0)

        # Next 9 requests: read from cache
        for _ in range(9):
            stats.record_usage(cache_creation_tokens=0, cache_read_tokens=10000)

        # Calculate savings
        savings = stats.estimated_savings_usd()

        # Without cache: 100,000 tokens * $0.003/1000 = $0.30
        # With cache: 10,000 creation + (90,000 * 0.1) = 19,000 effective tokens = $0.057
        # Savings: $0.30 - $0.057 = $0.243
        assert savings > 0.2  # Should save significant amount

    def test_estimated_savings_no_cache_usage(self):
        """Test estimated savings with no cache usage."""
        stats = CacheStatistics()

        stats.record_usage(cache_creation_tokens=5000, cache_read_tokens=0)

        # No cache reads means no savings
        savings = stats.estimated_savings_usd()
        assert savings == 0.0

    def test_summary(self):
        """Test cache statistics summary."""
        stats = CacheStatistics()

        stats.record_usage(cache_creation_tokens=5000, cache_read_tokens=0)
        stats.record_usage(cache_creation_tokens=0, cache_read_tokens=5000)
        stats.record_usage(cache_creation_tokens=0, cache_read_tokens=5000)

        summary = stats.summary()

        assert summary["total_requests"] == 3
        assert summary["cache_hits"] == 2
        assert summary["cache_hit_rate"] == 2 / 3
        assert summary["total_cache_creation_tokens"] == 5000
        assert summary["total_cache_read_tokens"] == 10000
        assert summary["estimated_savings_usd"] > 0

    def test_multiple_cache_creations(self):
        """Test handling multiple cache creation events."""
        stats = CacheStatistics()

        # Two separate cache creations (different contexts)
        stats.record_usage(cache_creation_tokens=5000, cache_read_tokens=0)
        stats.record_usage(cache_creation_tokens=3000, cache_read_tokens=0)

        assert stats._total_cache_creation_tokens == 8000
        assert stats._cache_hit_count == 0

    def test_mixed_usage_pattern(self):
        """Test realistic mixed usage pattern."""
        stats = CacheStatistics()

        # Create cache
        stats.record_usage(cache_creation_tokens=10000, cache_read_tokens=0)

        # Hit cache 5 times
        for _ in range(5):
            stats.record_usage(cache_creation_tokens=0, cache_read_tokens=10000)

        # Create new cache for different context
        stats.record_usage(cache_creation_tokens=8000, cache_read_tokens=0)

        # Hit second cache 3 times
        for _ in range(3):
            stats.record_usage(cache_creation_tokens=0, cache_read_tokens=8000)

        summary = stats.summary()

        assert summary["total_requests"] == 10
        assert summary["cache_hits"] == 8
        assert summary["cache_hit_rate"] == 0.8
        assert summary["total_cache_creation_tokens"] == 18000
        assert summary["total_cache_read_tokens"] == 74000
