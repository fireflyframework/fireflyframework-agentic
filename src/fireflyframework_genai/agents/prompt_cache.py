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

"""Provider prompt caching middleware for cost and latency optimization.

Prompt caching allows providers to cache portions of prompts (system prompts,
long contexts, few-shot examples) and reuse them across requests, providing:

- **90-95% cost reduction** on cached tokens (e.g., Anthropic charges ~10% for cache reads)
- **Reduced latency** by avoiding reprocessing of cached content
- **Better throughput** by reducing server-side processing

Supported Providers:
    - Anthropic Claude (prompt caching API)
    - OpenAI (prompt caching via cached context in future)
    - Gemini (context caching API)

Example::

    from fireflyframework_genai.agents.prompt_cache import PromptCacheMiddleware

    agent = FireflyAgent(
        "document-qa",
        model="anthropic:claude-3-5-sonnet-20241022",
        system_prompt="You are a helpful assistant...",  # Will be cached
        middleware=[
            PromptCacheMiddleware(
                cache_system_prompt=True,
                cache_min_tokens=1024,
            ),
        ],
    )

    # First request: pays full cost for system prompt
    result1 = await agent.run("Question 1")

    # Subsequent requests: pay ~10% cost for cached system prompt
    result2 = await agent.run("Question 2")
    result3 = await agent.run("Question 3")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PromptCacheMiddleware:
    """Middleware that enables provider prompt caching for cost optimization.

    This middleware configures agents to use provider-specific prompt caching
    features when available. Cached content is reused across requests,
    significantly reducing costs and latency for repeated use of the same
    context (system prompts, documents, examples).

    Parameters:
        cache_system_prompt: Whether to cache the system prompt (default: True).
        cache_min_tokens: Minimum tokens required to enable caching (default: 1024).
            Providers typically require a minimum length for caching to be cost-effective.
        cache_ttl_seconds: Cache TTL in seconds (default: 300 = 5 minutes).
            Note: Actual TTL depends on provider (e.g., Anthropic: 5min, extended with use).
        enabled: Whether caching is enabled (default: True).

    Provider-Specific Behavior:
        **Anthropic:**
        - Caches content with `cache_control` breakpoints
        - 5-minute TTL, extended on cache hits
        - ~90% cost reduction on cached tokens
        - Requires minimum 1024 tokens for caching

        **OpenAI:**
        - Future support via cached context API
        - TBD on cost structure

        **Gemini:**
        - Context caching API
        - Longer TTL options available

    Example::

        # Cache long system prompts for cost savings
        middleware = PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_min_tokens=2048,
        )

        agent = FireflyAgent(
            "legal-assistant",
            model="anthropic:claude-3-5-sonnet-20241022",
            system_prompt=long_legal_context,  # Will be cached
            middleware=[middleware],
        )

    Cost Savings Example:
        - System prompt: 10,000 tokens
        - Full cost: $0.003 per request (input tokens)
        - Cached cost: $0.0003 per request (90% savings)
        - After 100 requests: $0.30 → $0.03 (saved $0.27)

    Note:
        Prompt caching is most effective when:
        - System prompts are >1024 tokens
        - Multiple requests use the same context
        - Requests happen within cache TTL window
    """

    def __init__(
        self,
        *,
        cache_system_prompt: bool = True,
        cache_min_tokens: int = 1024,
        cache_ttl_seconds: int = 300,
        enabled: bool = True,
    ) -> None:
        self._cache_system_prompt = cache_system_prompt
        self._cache_min_tokens = cache_min_tokens
        self._cache_ttl_seconds = cache_ttl_seconds
        self._enabled = enabled

    async def before(self, context: Any) -> None:
        """Configure prompt caching before agent execution.

        This method modifies the agent run parameters to enable provider-specific
        prompt caching when supported.

        Args:
            context: Middleware context with agent_name, prompt, method, kwargs.
        """
        if not self._enabled:
            return

        # Extract model identifier from agent
        model = getattr(context, "model", "")
        if not model:
            return

        from fireflyframework_genai.model_utils import detect_model_family

        family = detect_model_family(model)
        if family == "anthropic":
            await self._configure_anthropic_caching(context)
        elif family == "openai":
            await self._configure_openai_caching(context)
        elif family == "google":
            await self._configure_gemini_caching(context)
        else:
            logger.debug(
                "PromptCacheMiddleware: Model '%s' (family=%s) does not support prompt caching",
                model,
                family,
            )

    async def after(self, context: Any, result: Any) -> Any:
        """Record cache usage metrics after agent execution.

        Args:
            context: Middleware context.
            result: Agent result with usage information.

        Returns:
            Unchanged result.
        """
        if not self._enabled:
            return result

        # Extract cache usage metrics if available
        if hasattr(result, "usage") and callable(result.usage):
            usage = result.usage()
            cache_creation = getattr(usage, "cache_creation_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_tokens", 0) or 0

            if cache_creation > 0 or cache_read > 0:
                logger.info(
                    "PromptCacheMiddleware: cache_creation=%d, cache_read=%d",
                    cache_creation,
                    cache_read,
                )

                # Calculate savings (approximation: 90% cost reduction on cached tokens)
                if cache_read > 0:
                    # Rough savings estimate based on typical pricing
                    estimated_savings_pct = 90
                    logger.info(
                        "PromptCacheMiddleware: Estimated savings: ~%d%% on %d cached tokens",
                        estimated_savings_pct,
                        cache_read,
                    )

        return result

    async def _configure_anthropic_caching(self, context: Any) -> None:
        """Configure Anthropic-specific prompt caching.

        Anthropic uses `cache_control` breakpoints to mark cacheable content.
        System prompts are automatically cached when they meet minimum token requirements.

        Args:
            context: Middleware context.
        """
        if not self._cache_system_prompt:
            return

        # Store caching configuration in metadata for Pydantic AI agent
        # The actual caching is handled by the Anthropic provider
        if not hasattr(context, "metadata"):
            context.metadata = {}

        context.metadata["_prompt_cache_enabled"] = True
        context.metadata["_cache_min_tokens"] = self._cache_min_tokens

        logger.debug(
            "PromptCacheMiddleware: Enabled Anthropic prompt caching (min_tokens=%d, ttl=%ds)",
            self._cache_min_tokens,
            self._cache_ttl_seconds,
        )

    async def _configure_openai_caching(self, context: Any) -> None:
        """Configure OpenAI-specific prompt caching.

        OpenAI's prompt caching is currently in beta and uses automatic
        cache detection. Future versions may support explicit cache control.

        Args:
            context: Middleware context.
        """
        # OpenAI caching is automatic in supported models
        # No explicit configuration needed currently
        logger.debug("PromptCacheMiddleware: OpenAI automatic caching enabled")

    async def _configure_gemini_caching(self, context: Any) -> None:
        """Configure Gemini-specific context caching.

        Gemini uses the context caching API to cache long contexts
        and reuse them across requests.

        Args:
            context: Middleware context.
        """
        if not hasattr(context, "metadata"):
            context.metadata = {}

        context.metadata["_gemini_cache_enabled"] = True
        context.metadata["_cache_ttl_seconds"] = self._cache_ttl_seconds

        logger.debug(
            "PromptCacheMiddleware: Enabled Gemini context caching (ttl=%ds)",
            self._cache_ttl_seconds,
        )


class CacheStatistics:
    """Track prompt caching statistics across requests.

    This utility class helps monitor cache effectiveness and cost savings.

    Example::

        stats = CacheStatistics()

        # After each request
        stats.record_usage(
            cache_creation_tokens=5000,
            cache_read_tokens=0,
        )

        # Later request with cache hit
        stats.record_usage(
            cache_creation_tokens=0,
            cache_read_tokens=5000,
        )

        # View statistics
        print(f"Cache hit rate: {stats.cache_hit_rate():.1%}")
        print(f"Total savings: ${stats.estimated_savings_usd():.2f}")
    """

    def __init__(self) -> None:
        self._total_cache_creation_tokens = 0
        self._total_cache_read_tokens = 0
        self._request_count = 0
        self._cache_hit_count = 0

    def record_usage(
        self,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> None:
        """Record cache usage from a request.

        Args:
            cache_creation_tokens: Tokens written to cache (first request).
            cache_read_tokens: Tokens read from cache (subsequent requests).
        """
        self._total_cache_creation_tokens += cache_creation_tokens
        self._total_cache_read_tokens += cache_read_tokens
        self._request_count += 1

        if cache_read_tokens > 0:
            self._cache_hit_count += 1

    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate.

        Returns:
            Percentage of requests that hit the cache (0.0 to 1.0).
        """
        if self._request_count == 0:
            return 0.0
        return self._cache_hit_count / self._request_count

    def estimated_savings_usd(
        self,
        input_token_cost: float = 0.003 / 1000,  # $3 per 1M tokens
        cache_read_discount: float = 0.9,  # 90% discount
    ) -> float:
        """Estimate cost savings from caching.

        Args:
            input_token_cost: Cost per input token (default: Sonnet pricing).
            cache_read_discount: Discount percentage for cached reads (default: 90%).

        Returns:
            Estimated savings in USD.
        """
        # Cost if no caching was used
        full_cost = (self._total_cache_creation_tokens + self._total_cache_read_tokens) * input_token_cost

        # Actual cost with caching
        cache_creation_cost = self._total_cache_creation_tokens * input_token_cost
        cache_read_cost = self._total_cache_read_tokens * input_token_cost * (1 - cache_read_discount)
        actual_cost = cache_creation_cost + cache_read_cost

        return full_cost - actual_cost

    def summary(self) -> dict[str, Any]:
        """Get cache statistics summary.

        Returns:
            Dictionary with cache metrics.
        """
        return {
            "total_requests": self._request_count,
            "cache_hits": self._cache_hit_count,
            "cache_hit_rate": self.cache_hit_rate(),
            "total_cache_creation_tokens": self._total_cache_creation_tokens,
            "total_cache_read_tokens": self._total_cache_read_tokens,
            "estimated_savings_usd": self.estimated_savings_usd(),
        }
