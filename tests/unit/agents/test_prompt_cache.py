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

"""Unit tests for prompt caching middleware."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from fireflyframework_agentic.agents.prompt_cache import CacheStatistics, PromptCacheMiddleware


@pytest.mark.asyncio
class TestPromptCacheMiddleware:
    """Test suite for prompt caching middleware."""

    async def test_middleware_initialization(self):
        """Test PromptCacheMiddleware initialization with defaults."""
        middleware = PromptCacheMiddleware()

        assert middleware._cache_system_prompt is True
        assert middleware._cache_ttl_seconds == 300
        assert middleware._enabled is True

    async def test_middleware_custom_parameters(self):
        """Test PromptCacheMiddleware with custom parameters."""
        middleware = PromptCacheMiddleware(
            cache_system_prompt=False,
            cache_ttl_seconds=3600,
            enabled=False,
        )

        assert middleware._cache_system_prompt is False
        assert middleware._cache_ttl_seconds == 3600
        assert middleware._enabled is False

    async def test_invalid_ttl_raises(self):
        """Anthropic only supports 5m / 1h -- other TTLs raise."""
        with pytest.raises(ValueError, match="cache_ttl_seconds"):
            PromptCacheMiddleware(cache_ttl_seconds=600)
        with pytest.raises(ValueError, match="cache_ttl_seconds"):
            PromptCacheMiddleware(cache_ttl_seconds=0)

    async def test_before_hook_with_disabled_middleware(self):
        """Test that disabled middleware does nothing."""
        middleware = PromptCacheMiddleware(enabled=False)

        context = Mock()
        context.model = "anthropic:claude-3-5-sonnet-20241022"

        # Should not raise or modify context
        await middleware.before_run(context)

    async def test_before_hook_anthropic_caching_multi_turn(self):
        """Anthropic caching writes the right model_settings into kwargs.

        Multi-turn run: a non-empty ``message_history`` is present, so
        ``anthropic_cache_messages`` is wired.
        """
        middleware = PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_last_message=True,
        )

        context = Mock()
        context.model = "anthropic:claude-3-5-sonnet-20241022"
        context.kwargs = {"message_history": [{"role": "user", "content": "prior turn"}]}

        await middleware.before_run(context)

        # Should inject pydantic-ai's anthropic_cache_* settings
        settings = context.kwargs["model_settings"]
        assert settings["anthropic_cache_instructions"] == "5m"
        assert settings["anthropic_cache_messages"] == "5m"
        assert "anthropic_cache_tool_definitions" not in settings

    async def test_before_hook_anthropic_one_shot_skips_cache_messages(self):
        """One-shot run (no message_history) -> anthropic_cache_messages is NOT set.

        Caching the last user message on a one-shot would write a 1.25x
        cache entry that no subsequent request can ever read (the user
        message is unique to that call). The middleware skips it.
        """
        middleware = PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_last_message=True,
        )

        context = Mock()
        context.model = "anthropic:claude-3-5-sonnet-20241022"
        context.kwargs = {}  # no message_history

        await middleware.before_run(context)

        settings = context.kwargs["model_settings"]
        assert settings["anthropic_cache_instructions"] == "5m"
        assert "anthropic_cache_messages" not in settings

    async def test_before_hook_anthropic_empty_history_skips_cache_messages(self):
        """An empty message_history list is also treated as one-shot."""
        middleware = PromptCacheMiddleware(cache_last_message=True)

        context = Mock()
        context.model = "anthropic:claude-3-5-sonnet-20241022"
        context.kwargs = {"message_history": []}

        await middleware.before_run(context)

        settings = context.kwargs.get("model_settings", {}) or {}
        assert "anthropic_cache_messages" not in settings

    async def test_before_hook_openai_auto_derives_cache_key_from_agent_and_model(self):
        """OpenAI default routing key combines agent name and model id.

        The model id is included so two model variants of the same
        agent (e.g. an A/B between ``gpt-4o`` and ``gpt-4.1``) do not
        share a routing key and collide on the cache backend.
        """
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = "openai:gpt-4o"
        context.agent_name = "flydesk-extractor"
        context.kwargs = {}

        await middleware.before_run(context)

        # Provider prefix stripped; one key per (agent, model) pair.
        assert context.kwargs["model_settings"]["openai_prompt_cache_key"] == "ffa-flydesk-extractor-gpt-4o"

    async def test_before_hook_openai_auto_key_strips_azure_prefix(self):
        """Azure and direct OpenAI variants of the same model share a key."""
        middleware = PromptCacheMiddleware()

        ctx_a = Mock()
        ctx_a.model = "openai:gpt-4o"
        ctx_a.agent_name = "judge"
        ctx_a.kwargs = {}

        ctx_b = Mock()
        ctx_b.model = "azure:gpt-4o"
        ctx_b.agent_name = "judge"
        ctx_b.kwargs = {}

        await middleware.before_run(ctx_a)
        await middleware.before_run(ctx_b)

        assert (
            ctx_a.kwargs["model_settings"]["openai_prompt_cache_key"]
            == ctx_b.kwargs["model_settings"]["openai_prompt_cache_key"]
            == "ffa-judge-gpt-4o"
        )

    async def test_before_hook_openai_no_agent_name_emits_no_key(self):
        """Without an agent name and no explicit override, no key is set."""
        middleware = PromptCacheMiddleware()

        context = Mock(spec=["model", "kwargs"])  # no agent_name attribute
        context.model = "openai:gpt-4o"
        context.kwargs = {}

        await middleware.before_run(context)

        # No openai_prompt_cache_key written; model_settings stays empty.
        settings = context.kwargs.get("model_settings", {}) or {}
        assert "openai_prompt_cache_key" not in settings

    async def test_before_hook_openai_explicit_string_key_overrides_default(self):
        """An explicit string key takes precedence over the agent-name default."""
        middleware = PromptCacheMiddleware(openai_cache_key="tenant-42")

        context = Mock()
        context.model = "openai:gpt-4o"
        context.agent_name = "should-be-ignored"
        context.kwargs = {}

        await middleware.before_run(context)

        assert context.kwargs["model_settings"]["openai_prompt_cache_key"] == "tenant-42"

    async def test_before_hook_openai_callable_key_evaluated_per_call(self):
        """Callable keys are evaluated per call, with the context as argument."""
        captured: list[Any] = []

        def keyfn(ctx: Any) -> str:
            captured.append(ctx)
            return f"per-call-{ctx.model.split(':')[-1]}"

        middleware = PromptCacheMiddleware(openai_cache_key=keyfn)

        context = Mock()
        context.model = "openai:gpt-4o-mini"
        context.kwargs = {}

        await middleware.before_run(context)

        assert captured == [context]
        assert context.kwargs["model_settings"]["openai_prompt_cache_key"] == "per-call-gpt-4o-mini"

    async def test_before_hook_openai_empty_string_opts_out(self):
        """``openai_cache_key=''`` opts out of cache routing entirely."""
        middleware = PromptCacheMiddleware(openai_cache_key="")

        context = Mock()
        context.model = "openai:gpt-4o"
        context.agent_name = "would-be-derived"
        context.kwargs = {}

        await middleware.before_run(context)

        settings = context.kwargs.get("model_settings", {}) or {}
        assert "openai_prompt_cache_key" not in settings

    async def test_before_hook_openai_callable_returning_none_falls_through_to_default(self):
        """A callable that returns ``None`` falls through to the auto-derived default.

        This mirrors the no-callable-configured behavior: ``None`` means
        "I have no preference, use the default", not "opt out". Use
        ``openai_cache_key=""`` to opt out.
        """
        middleware = PromptCacheMiddleware(openai_cache_key=lambda _ctx: None)

        context = Mock()
        context.model = "openai:gpt-4o"
        context.agent_name = "fallback-test"
        context.kwargs = {}

        await middleware.before_run(context)

        assert context.kwargs["model_settings"]["openai_prompt_cache_key"] == "ffa-fallback-test-gpt-4o"

    async def test_before_hook_openai_callable_returning_none_no_agent_name_is_noop(self):
        """Fall-through requires an agent_name; without one, nothing is set."""
        middleware = PromptCacheMiddleware(openai_cache_key=lambda _ctx: None)

        context = Mock(spec=["model", "kwargs"])  # no agent_name
        context.model = "openai:gpt-4o"
        context.kwargs = {}

        await middleware.before_run(context)
        settings = context.kwargs.get("model_settings", {}) or {}
        assert "openai_prompt_cache_key" not in settings

    async def test_before_hook_openai_callable_raising_falls_through_to_default(self):
        """A raising callable is swallowed and falls through to the default."""

        def boom(_ctx: Any) -> str:
            raise RuntimeError("resolver failed")

        middleware = PromptCacheMiddleware(openai_cache_key=boom)

        context = Mock()
        context.model = "openai:gpt-4o"
        context.agent_name = "boom-fallback"
        context.kwargs = {}

        # Must not raise; default kicks in.
        await middleware.before_run(context)
        assert context.kwargs["model_settings"]["openai_prompt_cache_key"] == "ffa-boom-fallback-gpt-4o"

    async def test_before_hook_openai_preserves_caller_supplied_key(self):
        """A caller-set ``openai_prompt_cache_key`` wins over the auto-derived one."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = "openai:gpt-4o"
        context.agent_name = "default-key"
        context.kwargs = {"model_settings": {"openai_prompt_cache_key": "caller-wins"}}

        await middleware.before_run(context)

        assert context.kwargs["model_settings"]["openai_prompt_cache_key"] == "caller-wins"

    async def test_before_hook_gemini_passes_through_cached_content_string(self):
        """A configured CachedContent resource id is wired into model_settings."""
        middleware = PromptCacheMiddleware(
            google_cached_content="cachedContents/abc123",
        )

        context = Mock()
        context.model = "google:gemini-1.5-pro"
        context.kwargs = {}

        await middleware.before_run(context)

        assert context.kwargs["model_settings"]["google_cached_content"] == ("cachedContents/abc123")

    async def test_before_hook_gemini_passes_through_callable_cached_content(self):
        """Callable resource resolvers are evaluated per request."""

        middleware = PromptCacheMiddleware(
            google_cached_content=lambda ctx: f"cachedContents/{ctx.agent_name}",
        )

        context = Mock()
        context.model = "google:gemini-2.0-flash"
        context.agent_name = "judge"
        context.kwargs = {}

        await middleware.before_run(context)

        assert context.kwargs["model_settings"]["google_cached_content"] == ("cachedContents/judge")

    async def test_before_hook_gemini_without_cached_content_is_noop(self):
        """No CachedContent configured -> middleware does not touch model_settings."""
        middleware = PromptCacheMiddleware()  # no google_cached_content

        context = Mock(spec=["model", "kwargs"])
        context.model = "google:gemini-1.5-pro"
        context.kwargs = {}

        await middleware.before_run(context)

        assert context.kwargs.get("model_settings", {}) == {}

    async def test_before_hook_gemini_callable_returning_none_is_safe(self):
        middleware = PromptCacheMiddleware(google_cached_content=lambda _ctx: None)

        context = Mock(spec=["model", "kwargs"])
        context.model = "google:gemini-1.5-pro"
        context.kwargs = {}

        await middleware.before_run(context)
        assert context.kwargs.get("model_settings", {}) == {}

    async def test_before_hook_gemini_callable_raising_is_swallowed(self):
        def boom(_ctx: Any) -> str:
            raise RuntimeError("resolver failed")

        middleware = PromptCacheMiddleware(google_cached_content=boom)
        context = Mock(spec=["model", "kwargs"])
        context.model = "google:gemini-1.5-pro"
        context.kwargs = {}

        await middleware.before_run(context)
        assert context.kwargs.get("model_settings", {}) == {}

    async def test_before_hook_bedrock_anthropic_skips_caching_visibly(self):
        """Claude via Bedrock must NOT silently apply Anthropic cache settings.

        Those settings are honoured only by the direct AnthropicModel; on
        BedrockConverseModel they are a no-op, so the middleware skips (with a
        warning) rather than writing dead settings.
        """
        middleware = PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_last_message=False,
        )

        context = Mock()
        context.model = "bedrock:anthropic.claude-3-5-sonnet-latest"
        context.kwargs = {}

        await middleware.before_run(context)

        # No Anthropic cache settings were applied (the no-op path is skipped).
        assert "model_settings" not in context.kwargs

    async def test_before_hook_azure_openai_routes_to_openai_caching(self):
        """Azure-hosted GPT should route to OpenAI caching."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = "azure:gpt-4o"

        # Should not raise (OpenAI caching is automatic)
        await middleware.before_run(context)

    async def test_before_hook_unsupported_provider(self):
        """Test behavior with unsupported provider."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = "unknown:model"

        # Should not raise, just log debug message
        await middleware.before_run(context)

    async def test_before_hook_no_model(self):
        """Test behavior when model is not set."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        context.model = ""

        # Should not raise
        await middleware.before_run(context)

    async def test_after_hook_with_cache_usage(self):
        """Test after hook records cache usage metrics."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        result = Mock()

        # Mock usage with cache metrics. ``spec=`` is required so that
        # missing attributes raise AttributeError (matching pydantic-ai's
        # real ``Usage`` shape) instead of auto-spawning child Mocks.
        usage = Mock(spec=["cache_write_tokens", "cache_read_tokens"])
        usage.cache_write_tokens = 5000
        usage.cache_read_tokens = 0
        result.usage = Mock(return_value=usage)

        returned_result = await middleware.after_run(context, result)

        # Should return unchanged result
        assert returned_result == result

    async def test_after_hook_with_cache_hits(self):
        """Test after hook with cache hit metrics."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        result = Mock()

        # Mock usage with cache read (see comment in sibling test re ``spec=``).
        usage = Mock(spec=["cache_write_tokens", "cache_read_tokens"])
        usage.cache_write_tokens = 0
        usage.cache_read_tokens = 5000
        result.usage = Mock(return_value=usage)

        returned_result = await middleware.after_run(context, result)

        assert returned_result == result

    async def test_after_hook_reads_legacy_cache_creation_tokens(self):
        """The middleware also accepts the legacy ``cache_creation_tokens`` field.

        Mirrors the same fallback chain used in ``FireflyAgent._record_usage``
        so a future pydantic-ai rename does not silently zero out the
        middleware's logged metrics.
        """
        middleware = PromptCacheMiddleware()

        context = Mock()
        result = Mock()
        usage = Mock(spec=["cache_creation_tokens", "cache_read_tokens"])
        usage.cache_creation_tokens = 4096
        usage.cache_read_tokens = 2048
        result.usage = Mock(return_value=usage)

        returned_result = await middleware.after_run(context, result)

        assert returned_result == result

    async def test_after_hook_no_usage(self):
        """Test after hook when result has no usage."""
        middleware = PromptCacheMiddleware()

        context = Mock()
        result = Mock(spec=[])  # No usage method

        # Should not raise
        returned_result = await middleware.after_run(context, result)
        assert returned_result == result

    async def test_after_hook_disabled(self):
        """Test that disabled middleware skips after hook."""
        middleware = PromptCacheMiddleware(enabled=False)

        context = Mock()
        result = Mock()

        returned_result = await middleware.after_run(context, result)

        # Should return result unchanged
        assert returned_result == result

    async def test_all_cache_targets_disabled_is_a_noop(self):
        """When system/messages/tools are all off, kwargs stay untouched."""
        middleware = PromptCacheMiddleware(
            cache_system_prompt=False,
            cache_last_message=False,
            cache_tool_definitions=False,
        )

        context = Mock()
        context.model = "anthropic:claude-3-5-sonnet-20241022"
        context.kwargs = {}

        await middleware.before_run(context)

        assert context.kwargs == {}

    async def test_existing_model_settings_preserved(self):
        """Cache settings must not overwrite caller-provided model_settings."""
        middleware = PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_last_message=True,
        )

        context = Mock()
        context.model = "anthropic:claude-sonnet-4-6"
        context.kwargs = {
            "message_history": [{"role": "user", "content": "prior"}],  # enables cache_messages
            "model_settings": {
                "anthropic_cache_instructions": "1h",  # caller already set 1h
                "temperature": 0.2,
            },
        }

        await middleware.before_run(context)

        settings = context.kwargs["model_settings"]
        # Caller's 1h preserved, middleware does NOT overwrite to 5m default.
        assert settings["anthropic_cache_instructions"] == "1h"
        assert settings["temperature"] == 0.2
        # New setting added.
        assert settings["anthropic_cache_messages"] == "5m"

    async def test_ttl_one_hour_maps_to_1h_literal(self):
        middleware = PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_ttl_seconds=3600,
        )

        context = Mock()
        context.model = "anthropic:claude-opus-4-7"
        context.kwargs = {}

        await middleware.before_run(context)

        assert context.kwargs["model_settings"]["anthropic_cache_instructions"] == "1h"


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
