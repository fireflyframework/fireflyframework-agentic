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

"""Provider prompt caching middleware for cost and latency optimization.

Prompt caching allows providers to cache portions of prompts (system prompts,
long contexts, few-shot examples) and reuse them across requests, providing:

- **90-95% cost reduction** on cached tokens (e.g., Anthropic charges ~10% for cache reads,
  OpenAI ~50% for cached input, Google ~25% for cached content)
- **Reduced latency** by avoiding reprocessing of cached content
- **Better throughput** by reducing server-side processing

Supported Providers (all wired through pydantic-ai's model_settings):
    - **Anthropic Claude** (direct + Bedrock-hosted): explicit
      ``cache_control`` breakpoints on the last system prompt / last user
      message / last tool definition. 5-minute or 1-hour TTL.
    - **OpenAI** (direct + Azure-hosted): automatic caching for prompts
      >= 1024 tokens. The middleware ALSO sets ``prompt_cache_key`` so
      consecutive requests from the same agent route to the same cache
      backend, materially improving the automatic-cache hit rate under
      load. Override via ``openai_cache_key=`` (string or callable).
    - **Google Gemini**: pre-created ``CachedContent`` resources are
      passed through to pydantic-ai via ``google_cached_content``.
      Caller owns the resource lifecycle (create, refresh, delete);
      this middleware just wires whatever id the caller supplies.

Example::

    from fireflyframework_agentic.agents.prompt_cache import PromptCacheMiddleware

    agent = FireflyAgent(
        "document-qa",
        model="anthropic:claude-3-5-sonnet-20241022",
        system_prompt="You are a helpful assistant...",  # Will be cached
        middleware=[
            PromptCacheMiddleware(
                cache_system_prompt=True,
                cache_min_tokens=1024,
                # Optional cross-provider knobs:
                #   openai_cache_key="my-stable-key",
                #   google_cached_content="cachedContents/abc123",
            ),
        ],
    )

    # First request: pays full cost for system prompt
    result1 = await agent.run("Question 1")

    # Subsequent requests: pay reduced cost for cached prefix
    result2 = await agent.run("Question 2")
    result3 = await agent.run("Question 3")
"""

from __future__ import annotations

import logging
from collections.abc import Callable
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
        **Anthropic (direct + Bedrock):**
        - Caches content with ``cache_control`` breakpoints on the last
          system prompt, last user message, and (optionally) last tool
          definition.
        - 5-minute or 1-hour TTL (``"5m"`` / ``"1h"``).
        - ~90% cost reduction on cached tokens; cache hits extend TTL.
        - Provider enforces a minimum-size threshold (currently 1024
          input tokens for Sonnet / Opus / Haiku).

        **OpenAI (direct + Azure):**
        - Automatic caching for any prefix >= 1024 tokens; no
          ``cache_control`` block needed.
        - The middleware sets ``prompt_cache_key`` so concurrent
          requests from the same agent route to the same cache backend
          -- materially improving hit rate under load. The default key
          is ``ffa-{agent_name}``; override via ``openai_cache_key=``
          (string or callable). Pass ``""`` to opt out.
        - Cached input tokens are billed at ~50% of normal pricing.

        **Google Gemini:**
        - Caching is via the ``CachedContent`` resource API. Callers
          create a ``CachedContent`` resource (system instruction +
          tools + content blocks) and pass its name to this middleware
          via ``google_cached_content=`` (string or callable). The
          middleware forwards it to pydantic-ai as
          ``model_settings.google_cached_content`` and Google bills the
          cached portion at ~25% of normal pricing.
        - Resource lifecycle (create, refresh, delete) is the caller's
          responsibility -- the middleware never creates or evicts
          ``CachedContent`` resources.

        **Other providers (Mistral, Cohere, DeepSeek, ...):**
        - No explicit caching primitive currently exposed by
          ``pydantic-ai`` for these providers; the middleware is a
          no-op (a debug log line is emitted).

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
        cache_last_message: bool = True,
        cache_tool_definitions: bool = False,
        cache_min_tokens: int = 1024,
        cache_ttl_seconds: int = 300,
        enabled: bool = True,
        openai_cache_key: str | Callable[[Any], str | None] | None = None,
        google_cached_content: str | Callable[[Any], str | None] | None = None,
    ) -> None:
        """
        Args:
            cache_system_prompt: Cache the system prompt block (Anthropic).
                Reduces per-call cost when the system prompt is large and
                reused across calls (extractor, judge, classifier, ...).
            cache_last_message: Cache the last user message block
                (Anthropic). Useful when the same large content (e.g. a
                document) is sent across multiple agent calls within the
                cache TTL window.
            cache_tool_definitions: Cache the tool definitions block
                (Anthropic). Off by default — only valuable when the
                agent has many tools.
            cache_min_tokens: Documented minimum for caching to be
                cost-effective; informational only at the moment, the
                provider enforces its own minimum.
            cache_ttl_seconds: 300 -> 5m, 3600 -> 1h. Mapped to
                Anthropic's `"5m"`/`"1h"` settings; any other value
                rounds to `"5m"`.
            enabled: Master switch.
            openai_cache_key: Routing hint for OpenAI's automatic prompt
                cache. When set (string or callable returning a string),
                emitted as ``openai_prompt_cache_key`` in pydantic-ai's
                ``model_settings`` so consecutive requests from the same
                agent share the same cache backend. Default behaviour:
                derive a stable key from the agent name when available.
                Pass ``""`` to fully opt out of routing hints.
            google_cached_content: Pre-created Google Gemini
                ``CachedContent`` resource id (e.g.
                ``"cachedContents/abc"``). When set, emitted as
                ``google_cached_content`` in pydantic-ai's
                ``model_settings``. The middleware does NOT create or
                manage the resource lifecycle -- callers must create the
                cached content via the GenAI SDK and pass its name here.
                Accepts a callable returning the id for late-binding.
        """
        self._cache_system_prompt = cache_system_prompt
        self._cache_last_message = cache_last_message
        self._cache_tool_definitions = cache_tool_definitions
        self._cache_min_tokens = cache_min_tokens
        self._cache_ttl_seconds = cache_ttl_seconds
        self._enabled = enabled
        self._openai_cache_key = openai_cache_key
        self._google_cached_content = google_cached_content

    async def before_run(self, context: Any) -> None:
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

        from fireflyframework_agentic.model_utils import detect_model_family

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

    async def after_run(self, context: Any, result: Any) -> Any:
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

        Translates the middleware's options into pydantic-ai's
        ``model_settings`` so the Anthropic provider injects
        ``cache_control`` breakpoints on the right blocks:

        * ``anthropic_cache_instructions`` -- caches the (last) system
          prompt block.
        * ``anthropic_cache_messages`` -- caches the last user-message
          content block, useful when the same document or context is
          replayed across calls.
        * ``anthropic_cache_tool_definitions`` -- caches the last tool
          definition.

        TTL: 300s -> ``"5m"``, 3600s -> ``"1h"``. Anything else falls
        back to ``"5m"``.

        Args:
            context: Middleware context. We append into its
                ``kwargs["model_settings"]`` so pydantic-ai's Anthropic
                provider sees the settings on the next ``Agent.run``.
                If the caller already provided ``model_settings`` we
                merge into it without overwriting existing keys.
        """
        if not any(
            (
                self._cache_system_prompt,
                self._cache_last_message,
                self._cache_tool_definitions,
            )
        ):
            return

        ttl: Any = "1h" if self._cache_ttl_seconds >= 3600 else "5m"

        if not hasattr(context, "kwargs") or context.kwargs is None:
            context.kwargs = {}
        settings = context.kwargs.get("model_settings")
        if not isinstance(settings, dict):
            settings = {}
            context.kwargs["model_settings"] = settings

        if self._cache_system_prompt:
            settings.setdefault("anthropic_cache_instructions", ttl)
        if self._cache_last_message:
            settings.setdefault("anthropic_cache_messages", ttl)
        if self._cache_tool_definitions:
            settings.setdefault("anthropic_cache_tool_definitions", ttl)

        logger.debug(
            "PromptCacheMiddleware: Anthropic cache configured (system=%s, last_msg=%s, tools=%s, ttl=%s)",
            self._cache_system_prompt,
            self._cache_last_message,
            self._cache_tool_definitions,
            ttl,
        )

    async def _configure_openai_caching(self, context: Any) -> None:
        """Configure OpenAI prompt-cache routing.

        OpenAI auto-caches prefixes >= ~1024 tokens on every supported
        model -- no explicit ``cache_control`` block is needed for the
        actual caching. What we *can* control is **cache routing**: the
        ``prompt_cache_key`` parameter (now exposed by pydantic-ai as
        ``openai_prompt_cache_key`` on ``OpenAIChatModelSettings``)
        tells OpenAI's load balancer to route requests with the same
        key to the same backend, materially improving the cache hit
        rate under concurrent traffic.

        Resolution order for the key:

        1. Explicit constructor argument (``openai_cache_key=``) --
           string or callable. Empty / falsy result means "do not set
           a key", which is a valid opt-out.
        2. Default: ``ffa-{agent_name}`` derived from
           ``context.agent_name`` when available.
        3. None -- middleware emits nothing and OpenAI's auto-cache
           still applies, just without sticky routing.

        Caller-provided ``openai_prompt_cache_key`` in
        ``model_settings`` always wins (``setdefault``).
        """
        key = self._resolve_openai_cache_key(context)
        if key is None:
            logger.debug("PromptCacheMiddleware: OpenAI automatic caching active (no routing key resolved)")
            return

        settings = self._ensure_model_settings(context)
        settings.setdefault("openai_prompt_cache_key", key)
        logger.debug(
            "PromptCacheMiddleware: OpenAI cache configured (prompt_cache_key=%r)",
            key,
        )

    async def _configure_gemini_caching(self, context: Any) -> None:
        """Configure Google Gemini context caching.

        Gemini's caching primitive is the ``CachedContent`` resource:
        the caller creates one via the GenAI SDK (passing tools,
        system instruction, and / or content blocks), and references
        its resource name on subsequent ``generate_content`` calls via
        ``GenerateContentConfig.cached_content``. Pydantic-ai exposes
        that knob as ``google_cached_content`` in
        ``GoogleModelSettings``.

        This middleware does NOT create / delete / refresh
        ``CachedContent`` resources -- their lifecycle (TTL, billing,
        eviction) is the caller's responsibility. What it does:

        * Reads the constructor's ``google_cached_content`` argument
          (string or callable). The callable signature is
          ``(context) -> str | None`` so callers can resolve the
          right resource per request (e.g. tenant-keyed caches).
        * If a non-empty id resolves, set
          ``model_settings.google_cached_content`` so pydantic-ai
          forwards it to the Google client.
        * Otherwise the middleware is a no-op for Gemini -- Google
          auto-caches large contexts implicitly with a flat 25%
          discount on the cached portion (see
          https://ai.google.dev/gemini-api/docs/caching).
        """
        resource_id = self._resolve_google_cached_content(context)
        if not resource_id:
            logger.debug(
                "PromptCacheMiddleware: Gemini implicit caching active (no explicit CachedContent resource configured)"
            )
            return

        settings = self._ensure_model_settings(context)
        settings.setdefault("google_cached_content", resource_id)
        logger.debug(
            "PromptCacheMiddleware: Gemini cache configured (google_cached_content=%r)",
            resource_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_model_settings(context: Any) -> dict[str, Any]:
        """Return the ``kwargs['model_settings']`` dict, creating it if
        missing. Mirrors the pattern in :meth:`_configure_anthropic_caching`.
        """
        if not hasattr(context, "kwargs") or context.kwargs is None:
            context.kwargs = {}
        settings = context.kwargs.get("model_settings")
        if not isinstance(settings, dict):
            settings = {}
            context.kwargs["model_settings"] = settings
        return settings

    def _resolve_openai_cache_key(self, context: Any) -> str | None:
        """Pick the OpenAI ``prompt_cache_key`` for this request.

        See :meth:`_configure_openai_caching` for the priority order.
        """
        configured = self._openai_cache_key
        if callable(configured):
            try:
                resolved = configured(context)
            except Exception as exc:  # noqa: BLE001 -- never fail extraction on a key resolver
                logger.warning(
                    "PromptCacheMiddleware: openai_cache_key callable raised %s; falling back to auto-derived key",
                    exc,
                )
                resolved = None
            if isinstance(resolved, str) and resolved:
                return resolved
            return None
        if isinstance(configured, str):
            return configured or None  # explicit empty string -> opt out
        # Default: derive a stable key from the agent name when present.
        agent_name = getattr(context, "agent_name", None)
        if isinstance(agent_name, str) and agent_name:
            return f"ffa-{agent_name}"
        return None

    def _resolve_google_cached_content(self, context: Any) -> str | None:
        """Pick the Gemini ``CachedContent`` resource id for this request."""
        configured = self._google_cached_content
        if configured is None:
            return None
        if callable(configured):
            try:
                resolved = configured(context)
            except Exception as exc:  # noqa: BLE001 -- degraded but not fatal
                logger.warning(
                    "PromptCacheMiddleware: google_cached_content callable "
                    "raised %s; skipping Gemini cache wiring for this request",
                    exc,
                )
                return None
            if isinstance(resolved, str) and resolved:
                return resolved
            return None
        if isinstance(configured, str) and configured:
            return configured
        return None


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
