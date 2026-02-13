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

"""FireflyAgent -- the primary agent abstraction in the Firefly GenAI framework.

:class:`FireflyAgent` wraps :class:`pydantic_ai.Agent` and enriches it with
framework-level concerns: metadata (name, version, tags), automatic
registration in the :class:`~fireflyframework_genai.agents.registry.AgentRegistry`,
lifecycle hooks, and sensible defaults drawn from
:class:`~fireflyframework_genai.config.FireflyGenAIConfig`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic, cast

from pydantic_ai import Agent
from pydantic_ai import Tool as PydanticTool
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from fireflyframework_genai.config import get_config
from fireflyframework_genai.types import AgentDepsT, Metadata, OutputT, UserContent

if TYPE_CHECKING:
    from fireflyframework_genai.agents.context import AgentContext
    from fireflyframework_genai.agents.middleware import AgentMiddleware, MiddlewareChain
    from fireflyframework_genai.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


def _run_sync_coro(coro: Any) -> Any:
    """Run an async coroutine from synchronous code without using the deprecated
    ``asyncio.get_event_loop()`` pattern.  Creates a fresh event loop on a
    background thread when a loop is already running, otherwise uses
    ``asyncio.run``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to use asyncio.run
        return asyncio.run(coro)

    # A loop is running (e.g. Jupyter, nested async).  Run in a new thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class FireflyAgent(Generic[AgentDepsT, OutputT]):
    """A managed agent that wraps a Pydantic AI :class:`Agent`.

    ``FireflyAgent`` preserves the full Pydantic AI API while adding:

    * **Metadata** -- name, version, description, tags, and arbitrary metadata
      for discovery and documentation.
    * **Convention defaults** -- the default model and retry count are pulled
      from :func:`~fireflyframework_genai.config.get_config` when not
      explicitly provided.
    * **Decorator proxies** -- :meth:`tool`, :meth:`tool_plain`, and
      :meth:`instructions` delegate to the underlying agent so that the
      familiar Pydantic AI decorator pattern works unchanged.

    Parameters:
        name: A unique, human-readable identifier for this agent.
        model: A Pydantic AI model string (e.g. ``"openai:gpt-4o"``) or a
            pre-configured :class:`pydantic_ai.models.Model` instance for
            programmatic credential management.  Defaults to the value in
            :class:`FireflyGenAIConfig`.
        instructions: Static instruction text or sequence of texts.
        output_type: The Pydantic model (or scalar type) for structured output.
        deps_type: The dependency type expected at run time.
        tools: Sequence of tool functions or :class:`pydantic_ai.Tool` objects.
        description: Free-form description shown in documentation and the REST
            exposure layer.
        version: Semantic version string for this agent definition.
        tags: Iterable of tags used for capability-based discovery.
        metadata: Arbitrary key-value pairs attached to the agent.
        retries: Override the default retry count.
        model_settings: Pydantic AI model settings dict.
        memory: Optional :class:`MemoryManager` for conversation history
            and working memory.  When set, ``run()`` automatically passes
            ``message_history`` from conversation memory and stores new
            messages back after each invocation.
        auto_register: When *True* (the default), the agent is automatically
            added to the global :class:`AgentRegistry`.
    """

    def __init__(
        self,
        name: str,
        *,
        model: str | Model | None = None,
        instructions: str | Sequence[str] = (),
        output_type: type[OutputT] = str,  # type: ignore[assignment]
        deps_type: type[AgentDepsT] = type(None),  # type: ignore[assignment]
        tools: Sequence[Any] = (),
        description: str = "",
        version: str = "0.1.0",
        tags: Sequence[str] = (),
        metadata: Metadata | None = None,
        retries: int | None = None,
        model_settings: ModelSettings | dict[str, Any] | None = None,
        memory: MemoryManager | None = None,
        middleware: list[AgentMiddleware] | None = None,
        default_middleware: bool = True,
        auto_register: bool = True,
    ) -> None:
        cfg = get_config()

        self._name = name
        self._version = version
        self._description = description
        self._tags = list(tags)
        self._metadata: Metadata = metadata or {}

        # Fall back to framework-wide defaults when the caller omits model or retries.
        # ``model`` may be a string, a pydantic_ai Model instance, or None.
        resolved_model = model or cfg.default_model
        resolved_retries = retries if retries is not None else cfg.max_retries

        # Keep the original model identifier for cost tracking.
        self._model_identifier: str = (
            resolved_model
            if isinstance(resolved_model, str)
            else getattr(resolved_model, "model_name", str(resolved_model))
        )

        self._memory = memory

        from fireflyframework_genai.agents.middleware import MiddlewareChain

        self._middleware = MiddlewareChain(self._build_middleware(middleware, default_middleware=default_middleware))

        resolved_settings: ModelSettings | None = (
            cast("ModelSettings", model_settings) if isinstance(model_settings, dict) else model_settings
        )

        self._agent: Agent[AgentDepsT, OutputT] = Agent(
            resolved_model,
            instructions=instructions,
            output_type=output_type,
            deps_type=deps_type,
            tools=self._resolve_tools(tools),
            retries=resolved_retries,
            model_settings=resolved_settings,
            name=name,
        )

        if auto_register:
            from fireflyframework_genai.agents.registry import agent_registry

            agent_registry.register(self)
            logger.debug("Auto-registered agent '%s' v%s", name, version)

    # -- Properties ----------------------------------------------------------

    @property
    def agent(self) -> Agent[AgentDepsT, OutputT]:
        """The underlying Pydantic AI agent instance."""
        return self._agent

    @property
    def name(self) -> str:
        """Unique human-readable name."""
        return self._name

    @property
    def version(self) -> str:
        """Semantic version of this agent definition."""
        return self._version

    @property
    def description(self) -> str:
        """Free-form description for documentation."""
        return self._description

    @property
    def tags(self) -> list[str]:
        """Tags for capability-based discovery."""
        return self._tags

    @property
    def metadata(self) -> Metadata:
        """Arbitrary key-value metadata."""
        return self._metadata

    @property
    def memory(self) -> MemoryManager | None:
        """The memory manager attached to this agent, if any."""
        return self._memory

    @memory.setter
    def memory(self, value: MemoryManager | None) -> None:
        self._memory = value

    @property
    def middleware(self) -> MiddlewareChain:
        """The middleware chain for this agent."""
        return self._middleware

    # -- Run methods (delegate to inner agent) -------------------------------

    async def run(
        self,
        prompt: str | Sequence[UserContent] | None = None,
        *,
        deps: AgentDepsT = None,  # type: ignore[assignment]
        conversation_id: str | None = None,
        timeout: float | None = None,
        context: AgentContext | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run the agent asynchronously.

        *prompt* can be a plain string, a sequence of multimodal
        :class:`~fireflyframework_genai.types.UserContent` parts (text,
        images, documents, audio, video, binary data), or ``None``.

        When a :class:`MemoryManager` is attached and *conversation_id*
        is provided, the agent automatically loads conversation history
        as ``message_history`` and stores new messages after the run.

        Delegates to ``pydantic_ai.Agent.run``.
        """
        from fireflyframework_genai.agents.context import AgentContext as _AgentContext
        from fireflyframework_genai.agents.middleware import MiddlewareContext

        if context is None:
            context = _AgentContext()

        mw_ctx = MiddlewareContext(
            agent_name=self._name,
            prompt=prompt,
            method="run",
            deps=deps,
            kwargs=kwargs,
            context=context,
        )
        await self._middleware.run_before(mw_ctx)

        # Middleware short-circuit (e.g. cache hit)
        if "_cache_result" in mw_ctx.metadata:
            result = mw_ctx.metadata["_cache_result"]
            result = await self._middleware.run_after(mw_ctx, result)
            return result

        t0 = time.monotonic()
        self._inject_memory(conversation_id, kwargs)

        result = await self._run_with_rate_limit_retry(
            mw_ctx.prompt, deps=deps, timeout=timeout, **kwargs
        )

        elapsed_ms = (time.monotonic() - t0) * 1000
        self._persist_memory(conversation_id, prompt, result)
        self._record_usage(result, elapsed_ms, correlation_id=context.correlation_id)

        result = await self._middleware.run_after(mw_ctx, result)
        return result

    def run_sync(
        self,
        prompt: str | Sequence[UserContent] | None = None,
        *,
        deps: AgentDepsT = None,  # type: ignore[assignment]
        conversation_id: str | None = None,
        timeout: float | None = None,
        context: AgentContext | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run the agent synchronously.  Delegates to ``pydantic_ai.Agent.run_sync``."""
        from fireflyframework_genai.agents.context import AgentContext as _AgentContext
        from fireflyframework_genai.agents.middleware import MiddlewareContext

        if context is None:
            context = _AgentContext()

        mw_ctx = MiddlewareContext(
            agent_name=self._name,
            prompt=prompt,
            method="run_sync",
            deps=deps,
            kwargs=kwargs,
            context=context,
        )
        if len(self._middleware) > 0:
            _run_sync_coro(self._middleware.run_before(mw_ctx))

        # Middleware short-circuit (e.g. cache hit)
        if "_cache_result" in mw_ctx.metadata:
            result = mw_ctx.metadata["_cache_result"]
            if len(self._middleware) > 0:
                result = _run_sync_coro(self._middleware.run_after(mw_ctx, result))
            return result

        t0 = time.monotonic()
        self._inject_memory(conversation_id, kwargs)
        result = _run_sync_coro(
            self._run_with_rate_limit_retry(
                mw_ctx.prompt, deps=deps, timeout=timeout, **kwargs
            )
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        self._persist_memory(conversation_id, prompt, result)
        self._record_usage(result, elapsed_ms, correlation_id=context.correlation_id)

        if len(self._middleware) > 0:
            result = _run_sync_coro(self._middleware.run_after(mw_ctx, result))
        return result

    async def run_stream(
        self,
        prompt: str | Sequence[UserContent] | None = None,
        *,
        deps: AgentDepsT = None,  # type: ignore[assignment]
        conversation_id: str | None = None,
        timeout: float | None = None,
        context: AgentContext | None = None,
        streaming_mode: str = "buffered",
        **kwargs: Any,
    ) -> Any:
        """Run the agent with streaming.  Delegates to ``pydantic_ai.Agent.run_stream``.

        The returned context manager is wrapped so that usage is recorded
        when the stream completes (i.e. on ``__aexit__``).

        Args:
            streaming_mode: Streaming mode:
                - "buffered" (default): Stream in chunks/messages (backward compatible)
                - "incremental": True token-by-token streaming with minimal latency
        """
        from fireflyframework_genai.agents.context import AgentContext as _AgentContext
        from fireflyframework_genai.agents.middleware import MiddlewareContext

        if streaming_mode not in ("buffered", "incremental"):
            raise ValueError(f"Invalid streaming_mode: {streaming_mode!r}. Expected 'buffered' or 'incremental'.")

        if context is None:
            context = _AgentContext()

        mw_ctx = MiddlewareContext(
            agent_name=self._name,
            prompt=prompt,
            method="run_stream",
            deps=deps,
            kwargs=kwargs,
            context=context,
        )
        await self._middleware.run_before(mw_ctx)

        # Middleware short-circuit (e.g. cache hit)
        if "_cache_result" in mw_ctx.metadata:
            result = mw_ctx.metadata["_cache_result"]
            await self._middleware.run_after(mw_ctx, result)
            return result

        self._inject_memory(conversation_id, kwargs)
        stream_ctx = self._agent.run_stream(mw_ctx.prompt, deps=deps, **kwargs)

        if streaming_mode == "incremental":
            return _IncrementalStreamContext(
                stream_ctx,
                self,
                time.monotonic(),
                mw_ctx,
                correlation_id=context.correlation_id,
                timeout=timeout,
            )
        else:
            return _UsageTrackingStreamContext(
                stream_ctx,
                self,
                time.monotonic(),
                mw_ctx,
                correlation_id=context.correlation_id,
                timeout=timeout,
            )

    # -- Memory integration ------------------------------------------------

    def _inject_memory(self, conversation_id: str | None, kwargs: dict[str, Any]) -> None:
        """If memory is attached, inject message_history into kwargs."""
        if self._memory is None or conversation_id is None:
            return
        if "message_history" not in kwargs:
            kwargs["message_history"] = self._memory.get_message_history(conversation_id)
            logger.debug("Agent '%s': injected memory for conversation '%s'", self._name, conversation_id)

    def _persist_memory(
        self,
        conversation_id: str | None,
        prompt: Any,
        result: Any,
    ) -> None:
        """After a run, store new messages in conversation memory."""
        if self._memory is None or conversation_id is None:
            return
        if not hasattr(result, "new_messages"):
            return
        new_msgs = result.new_messages()
        prompt_text = prompt if isinstance(prompt, str) else str(prompt)
        output_text = str(result.output) if hasattr(result, "output") else ""
        self._memory.add_turn(conversation_id, prompt_text, output_text, new_msgs)
        logger.debug("Agent '%s': persisted turn to conversation '%s'", self._name, conversation_id)

    # -- Usage tracking ------------------------------------------------------

    def _record_usage(
        self,
        result: Any,
        elapsed_ms: float,
        *,
        correlation_id: str = "",
    ) -> None:
        """Extract token usage from a Pydantic AI result and feed the tracker."""
        cfg = get_config()
        if not cfg.cost_tracking_enabled:
            return
        try:
            usage = result.usage() if callable(getattr(result, "usage", None)) else None
            if usage is None:
                return

            from fireflyframework_genai.observability.cost import get_cost_calculator
            from fireflyframework_genai.observability.usage import UsageRecord, default_usage_tracker

            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens)
            request_count = getattr(usage, "request_count", 0) or 0
            cache_creation = getattr(usage, "cache_creation_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_tokens", 0) or 0

            model_name = self._model_identifier
            calculator = get_cost_calculator(cfg.cost_calculator)
            cost = calculator.estimate(model_name, input_tokens, output_tokens)

            record = UsageRecord(
                agent=self._name,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cache_creation_tokens=cache_creation,
                cache_read_tokens=cache_read,
                request_count=request_count,
                cost_usd=cost,
                latency_ms=elapsed_ms,
                correlation_id=correlation_id,
            )
            default_usage_tracker.record(record)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to record usage for agent '%s'", self._name, exc_info=True)

    # -- Reasoning integration ------------------------------------------------

    async def run_with_reasoning(
        self,
        pattern: Any,
        prompt: str | Sequence[UserContent] | None = None,
        *,
        conversation_id: str | None = None,
        context: AgentContext | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run the agent using a reasoning pattern.

        Convenience method that wires ``self`` as the agent, passes
        the attached :class:`MemoryManager` (if any), and optionally
        injects conversation history.

        Parameters:
            pattern: A :class:`ReasoningPattern` or any object with an
                async ``execute(agent, input, **kwargs)`` method.
            prompt: The input prompt.
            conversation_id: When set and memory is attached, conversation
                history is injected and the reasoning output is stored as
                a new turn after completion.
            context: Optional :class:`AgentContext` for correlation and
                tracing.  A fresh context is created when *None*.
            **kwargs: Forwarded to ``pattern.execute()``.

        Returns:
            A :class:`ReasoningResult` produced by the pattern.
        """
        from fireflyframework_genai.agents.context import AgentContext as _AgentContext
        from fireflyframework_genai.agents.middleware import MiddlewareContext
        from fireflyframework_genai.reasoning.trace import ReasoningResult

        if context is None:
            context = _AgentContext()

        mw_ctx = MiddlewareContext(
            agent_name=self._name,
            prompt=prompt,
            method="run_with_reasoning",
            deps=None,
            kwargs=kwargs,
            context=context,
        )
        await self._middleware.run_before(mw_ctx)

        # Pass memory to the pattern if we have one
        if self._memory is not None and "memory" not in kwargs:
            kwargs["memory"] = self._memory

        result: ReasoningResult = await pattern.execute(self, mw_ctx.prompt, **kwargs)

        # Persist the reasoning output as a conversation turn
        if self._memory is not None and conversation_id is not None:
            prompt_text = prompt if isinstance(prompt, str) else str(prompt)
            output_text = str(result.output)[:1000] if result.output else ""
            self._memory.add_turn(
                conversation_id,
                prompt_text,
                output_text,
                [],
            )

        result = await self._middleware.run_after(mw_ctx, result)
        return result

    # -- Decorator proxies ---------------------------------------------------

    def tool(self, func: Any = None, **kwargs: Any) -> Any:
        """Register a tool with the underlying agent.  See ``Agent.tool``."""
        return self._agent.tool(func, **kwargs) if func is not None else self._agent.tool(**kwargs)

    def tool_plain(self, func: Any = None, **kwargs: Any) -> Any:
        """Register a plain tool.  See ``Agent.tool_plain``."""
        return self._agent.tool_plain(func, **kwargs) if func is not None else self._agent.tool_plain(**kwargs)

    def instructions(self, func: Any) -> Any:
        """Register a dynamic instructions function.  See ``Agent.instructions``."""
        return self._agent.instructions(func)

    # -- Rate limit detection --------------------------------------------------

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        """Detect rate limit errors from any LLM provider.

        Checks for:
        - Framework :class:`RateLimitError`
        - HTTP 429 status code (Anthropic, OpenAI SDKs)
        - String patterns as a fallback
        """
        from fireflyframework_genai.exceptions import RateLimitError

        if isinstance(exc, RateLimitError):
            return True
        if hasattr(exc, "status_code") and exc.status_code == 429:
            return True
        msg = str(exc).lower()
        return ("rate" in msg and "limit" in msg) or "429" in str(exc)

    # -- Rate limit retry -----------------------------------------------------

    async def _run_with_rate_limit_retry(
        self,
        prompt: str | Sequence[UserContent] | None,
        *,
        deps: AgentDepsT = None,  # type: ignore[assignment]
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute ``self._agent.run()`` with automatic 429 retry using AdaptiveBackoff.

        Reads retry parameters from :func:`get_config` and uses the
        :class:`~fireflyframework_genai.observability.quota.AdaptiveBackoff`
        instance on the default :class:`QuotaManager` when quota is enabled,
        or creates a standalone backoff otherwise.
        """
        import re

        from fireflyframework_genai.observability.quota import (
            AdaptiveBackoff,
            default_quota_manager,
        )

        cfg = get_config()
        max_retries = cfg.rate_limit_max_retries
        max_delay = cfg.rate_limit_max_delay

        # Reuse the QuotaManager's backoff if available, else standalone
        if default_quota_manager is not None and default_quota_manager._backoff is not None:
            backoff = default_quota_manager._backoff
        else:
            backoff = AdaptiveBackoff(
                base_delay=cfg.rate_limit_base_delay,
                max_delay=max_delay,
            )

        key = self._model_identifier

        for attempt in range(max_retries + 1):
            try:
                coro = self._agent.run(prompt, deps=deps, **kwargs)
                if timeout is not None:
                    result = await asyncio.wait_for(coro, timeout=timeout)
                else:
                    result = await coro
                # Success — reset backoff counter
                backoff.reset(key)
                return result
            except Exception as exc:
                if not self._is_rate_limit_error(exc) or attempt >= max_retries:
                    raise

                backoff.record_failure(key)
                delay = backoff.get_delay(key)

                # Try to parse a suggested delay from the error body
                retry_match = re.search(
                    r"retry.*?(\d+\.?\d*)\s*s", str(exc).lower()
                )
                if retry_match:
                    delay = min(float(retry_match.group(1)), max_delay)

                logger.warning(
                    "Rate limit hit on '%s' (attempt %d/%d), retrying in %.1fs…",
                    key,
                    attempt + 1,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        # Should not be reached; final attempt raises in the loop
        raise RuntimeError("Unexpected state in _run_with_rate_limit_retry")

    # -- Default middleware resolution ----------------------------------------

    @staticmethod
    def _build_middleware(
        user_middleware: list[Any] | None,
        *,
        default_middleware: bool = True,
    ) -> list[Any]:
        """Merge user-supplied middleware with auto-wired defaults.

        When *default_middleware* is True, prepends a
        :class:`LoggingMiddleware` and (when observability is enabled) an
        :class:`ObservabilityMiddleware` to the chain unless the user
        already supplied one.
        """
        from fireflyframework_genai.agents.builtin_middleware import (
            LoggingMiddleware,
            ObservabilityMiddleware,
        )

        chain: list[Any] = []
        user_mw = list(user_middleware or [])

        if default_middleware:
            has_logging = any(isinstance(m, LoggingMiddleware) for m in user_mw)
            if not has_logging:
                chain.append(LoggingMiddleware())

            cfg = get_config()
            if cfg.observability_enabled:
                has_obs = any(isinstance(m, ObservabilityMiddleware) for m in user_mw)
                if not has_obs:
                    chain.append(ObservabilityMiddleware())

        chain.extend(user_mw)
        return chain

    # -- Tool resolution ------------------------------------------------------

    @staticmethod
    def _resolve_tools(tools: Sequence[Any]) -> list[Any]:
        """Convert framework tool types into Pydantic AI tool objects.

        * :class:`~fireflyframework_genai.tools.base.BaseTool` instances are
          wrapped in :class:`pydantic_ai.Tool` so their ``execute`` method is
          called by the underlying agent.
        * :class:`~fireflyframework_genai.tools.toolkit.ToolKit` instances are
          expanded via :meth:`~ToolKit.as_pydantic_tools`.
        * Everything else (plain functions, ``pydantic_ai.Tool`` objects) is
          passed through unchanged.
        """
        from fireflyframework_genai.tools.base import BaseTool
        from fireflyframework_genai.tools.toolkit import ToolKit

        resolved: list[Any] = []
        for item in tools:
            if isinstance(item, ToolKit):
                resolved.extend(item.as_pydantic_tools())
            elif isinstance(item, BaseTool):
                resolved.append(
                    PydanticTool(
                        item.pydantic_handler(),
                        name=item.name,
                        description=item.description,
                    )
                )
            else:
                resolved.append(item)
        return resolved

    # -- Dunder --------------------------------------------------------------

    def __repr__(self) -> str:
        return f"FireflyAgent(name={self._name!r}, version={self._version!r}, model={self._agent.model!r})"


class _UsageTrackingStreamContext:
    """Async context manager wrapper that records usage when the stream finishes."""

    def __init__(
        self,
        stream_ctx: Any,
        agent: FireflyAgent[Any, Any],
        t0: float,
        mw_ctx: Any = None,
        *,
        correlation_id: str = "",
        timeout: float | None = None,
    ) -> None:
        self._stream_ctx = stream_ctx
        self._agent = agent
        self._t0 = t0
        self._mw_ctx = mw_ctx
        self._correlation_id = correlation_id
        self._timeout = timeout
        self._stream: Any = None

    async def __aenter__(self) -> Any:
        enter_coro = self._stream_ctx.__aenter__()
        if self._timeout is not None:
            self._stream = await asyncio.wait_for(enter_coro, timeout=self._timeout)
        else:
            self._stream = await enter_coro
        return self._stream

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        result = await self._stream_ctx.__aexit__(exc_type, exc_val, exc_tb)
        elapsed_ms = (time.monotonic() - self._t0) * 1000
        # After the stream closes, usage() is available on the stream handle.
        if self._stream is not None:
            self._agent._record_usage(
                self._stream,
                elapsed_ms,
                correlation_id=self._correlation_id,
            )
        # Run after-hooks on the stream handle so middleware can inspect usage.
        if self._mw_ctx is not None:
            await self._agent._middleware.run_after(self._mw_ctx, self._stream)
        return result


class _IncrementalStreamContext:
    """Async context manager for true token-by-token streaming.

    Provides minimal latency streaming by yielding tokens as soon as they
    arrive from the model, without buffering. This is ideal for interactive
    applications where users want to see responses immediately.

    The returned stream wrapper provides:
    - stream_tokens(): Yields individual tokens with minimal latency
    - stream_text(): Falls back to buffered text streaming
    - All other stream methods from the underlying Pydantic AI stream
    """

    def __init__(
        self,
        stream_ctx: Any,
        agent: FireflyAgent[Any, Any],
        t0: float,
        mw_ctx: Any = None,
        *,
        correlation_id: str = "",
        timeout: float | None = None,
    ) -> None:
        self._stream_ctx = stream_ctx
        self._agent = agent
        self._t0 = t0
        self._mw_ctx = mw_ctx
        self._correlation_id = correlation_id
        self._timeout = timeout
        self._stream: Any = None

    async def __aenter__(self) -> Any:
        enter_coro = self._stream_ctx.__aenter__()
        if self._timeout is not None:
            self._stream = await asyncio.wait_for(enter_coro, timeout=self._timeout)
        else:
            self._stream = await enter_coro

        # Wrap the stream to add incremental token streaming
        return _IncrementalStreamWrapper(self._stream)

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        result = await self._stream_ctx.__aexit__(exc_type, exc_val, exc_tb)
        elapsed_ms = (time.monotonic() - self._t0) * 1000
        # After the stream closes, usage() is available on the stream handle.
        if self._stream is not None:
            self._agent._record_usage(
                self._stream,
                elapsed_ms,
                correlation_id=self._correlation_id,
            )
        # Run after-hooks on the stream handle so middleware can inspect usage.
        if self._mw_ctx is not None:
            await self._agent._middleware.run_after(self._mw_ctx, self._stream)
        return result


class _IncrementalStreamWrapper:
    """Wrapper that adds true token-by-token streaming to a Pydantic AI stream.

    This wrapper intercepts the underlying stream and provides a stream_tokens()
    method that yields individual tokens as they arrive, providing minimal latency
    for interactive applications.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._buffer: list[str] = []
        self._prev_text = ""

    async def stream_tokens(self, *, debounce_ms: float = 0.0) -> Any:
        """Stream individual tokens as they arrive.

        This method provides true token-by-token streaming by tracking the
        difference between successive text chunks from the model.

        Args:
            debounce_ms: Optional debounce delay in milliseconds to batch
                rapid tokens together. Default 0 = no debouncing.

        Yields:
            str: Individual tokens as they arrive from the model.

        Example:
            async with await agent.run_stream(
                "Write a story", streaming_mode="incremental"
            ) as stream:
                async for token in stream.stream_tokens():
                    print(token, end="", flush=True)
        """
        self._prev_text = ""

        async for chunk in self._stream.stream_text(delta=True):
            # The delta=True gives us incremental text
            if chunk:
                if debounce_ms > 0:
                    # Batch rapid tokens with debouncing
                    self._buffer.append(chunk)
                    await asyncio.sleep(debounce_ms / 1000.0)

                    if self._buffer:
                        # Yield batched tokens
                        batched = "".join(self._buffer)
                        self._buffer.clear()
                        yield batched
                else:
                    # Yield immediately without debouncing
                    yield chunk

        # Flush any remaining buffered tokens
        if self._buffer:
            yield "".join(self._buffer)

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to the underlying stream."""
        return getattr(self._stream, name)
