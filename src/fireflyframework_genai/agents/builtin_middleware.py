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

"""Built-in agent middleware implementations.

The framework ships three ready-to-use middleware classes:

* :class:`LoggingMiddleware` -- structured logging for every agent run
  (auto-wired by default).
* :class:`PromptGuardMiddleware` -- prompt-injection detection/sanitisation.
* :class:`CostGuardMiddleware` -- budget enforcement before an LLM call.

Usage::

    from fireflyframework_genai.agents.builtin_middleware import (
        LoggingMiddleware,
        PromptGuardMiddleware,
        CostGuardMiddleware,
    )

    agent = FireflyAgent(
        "safe-agent",
        model="openai:gpt-4o",
        middleware=[PromptGuardMiddleware(), CostGuardMiddleware(budget_usd=5.0)],
    )
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fireflyframework_genai.agents.middleware import MiddlewareContext

logger = logging.getLogger(__name__)


# -- Errors ------------------------------------------------------------------


class PromptGuardError(RuntimeError):
    """Raised when :class:`PromptGuardMiddleware` detects unsafe input."""


class OutputGuardError(RuntimeError):
    """Raised when :class:`OutputGuardMiddleware` detects unsafe output."""


class BudgetExceededError(RuntimeError):
    """Raised when :class:`CostGuardMiddleware` detects budget overrun."""


# -- LoggingMiddleware -------------------------------------------------------


class LoggingMiddleware:
    """Structured logging for every agent run.

    Auto-wired by default into every :class:`FireflyAgent`.  Emits an
    **entry** log line in ``before_run`` and a **completion** log line in
    ``after_run`` with elapsed time, token count, and estimated cost.

    The middleware uses the standard Python logger under the
    ``fireflyframework_genai`` hierarchy so that
    :func:`~fireflyframework_genai.logging.configure_logging` controls
    its output (including the ``colored`` and ``json`` format styles).

    Parameters:
        level: Logging level for the entry/completion lines.
        preview_length: Maximum characters of the prompt to include.
        include_usage: Whether to extract token/cost data from the result.
    """

    def __init__(
        self,
        *,
        level: int = logging.INFO,
        preview_length: int = 80,
        include_usage: bool = True,
    ) -> None:
        self._level = level
        self._preview_length = preview_length
        self._include_usage = include_usage

    # -- hooks ---------------------------------------------------------------

    async def before_run(self, context: MiddlewareContext) -> None:
        """Log the start of an agent run."""
        context.metadata["_log_t0"] = time.monotonic()
        preview = str(context.prompt)[: self._preview_length] if context.prompt is not None else "<none>"
        method = context.method or "run"
        logger.log(
            self._level,
            "\u25b8 %s.%s(prompt=%s...)",
            context.agent_name,
            method,
            preview,
        )

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Log completion with timing, tokens and cost."""
        t0 = context.metadata.get("_log_t0")
        elapsed_ms = (time.monotonic() - t0) * 1000 if t0 is not None else 0.0
        method = context.method or "run"

        suffix = self._usage_suffix(result) if self._include_usage else ""
        reasoning = self._reasoning_suffix(result)

        logger.log(
            self._level,
            "\u2713 %s.%s completed in %.1fms%s%s",
            context.agent_name,
            method,
            elapsed_ms,
            suffix,
            reasoning,
        )
        return result

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _usage_suffix(result: Any) -> str:
        """Extract token/cost info from the result, if available."""
        usage = result.usage() if callable(getattr(result, "usage", None)) else None
        if usage is None:
            return ""
        tokens = getattr(usage, "total_tokens", 0) or 0
        if tokens == 0:
            return ""
        parts = [f" [tokens={tokens}"]
        # Cost may have been recorded on the result by the framework.
        cost = getattr(result, "_firefly_cost_usd", None)
        if cost is not None and cost > 0:
            parts.append(f", cost=${cost:.4f}")
        parts.append("]")
        return "".join(parts)

    @staticmethod
    def _reasoning_suffix(result: Any) -> str:
        """Append reasoning info if the result is a ReasoningResult."""
        steps = getattr(result, "steps_taken", None)
        if steps is None:
            return ""
        pattern = getattr(getattr(result, "trace", None), "pattern_name", None) or ""
        if pattern:
            return f" (pattern={pattern}, steps={steps})"
        return f" (steps={steps})"


# -- PromptGuardMiddleware ---------------------------------------------------


class PromptGuardMiddleware:
    """Scans prompts for injection patterns before the agent runs.

    By default, unsafe prompts cause a :class:`PromptGuardError`.  When
    *sanitise* is ``True``, the prompt is sanitised (suspicious fragments
    replaced with ``[REDACTED]``) and execution continues.

    Parameters:
        guard: A :class:`~fireflyframework_genai.security.prompt_guard.PromptGuard`
            instance.  Defaults to the module-level ``default_prompt_guard``.
        sanitise: When *True*, sanitise the prompt instead of rejecting.
    """

    def __init__(
        self,
        *,
        guard: Any | None = None,
        sanitise: bool = False,
    ) -> None:
        if guard is not None:
            self._guard = guard
        else:
            from fireflyframework_genai.security.prompt_guard import PromptGuard

            self._guard = PromptGuard(sanitise=sanitise)
        self._sanitise = sanitise

    async def before_run(self, context: MiddlewareContext) -> None:
        """Scan the prompt; reject or sanitise if unsafe."""
        text = str(context.prompt) if context.prompt is not None else ""
        if not text:
            return

        scan_result = self._guard.scan(text)
        if scan_result.safe:
            return

        if self._sanitise and scan_result.sanitised_input is not None:
            logger.warning(
                "PromptGuardMiddleware: sanitised prompt for agent '%s' (%d pattern(s) matched)",
                context.agent_name,
                len(scan_result.matched_patterns),
            )
            context.prompt = scan_result.sanitised_input
        else:
            raise PromptGuardError(f"Prompt blocked for agent '{context.agent_name}': {scan_result.reason}")

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Pass-through (no post-processing needed)."""
        return result


# -- CostGuardMiddleware -----------------------------------------------------


class CostGuardMiddleware:
    """Enforces a cumulative cost budget before each agent run.

    Checks the global :class:`UsageTracker` and raises
    :class:`BudgetExceededError` if cumulative spending has already
    reached *budget_usd*.

    Parameters:
        budget_usd: Maximum cumulative spend in USD.
        tracker: A :class:`UsageTracker` instance.  Defaults to the
            module-level ``default_usage_tracker``.
        warn_only: When *True*, log a warning instead of raising on
            budget overrun.  Useful for soft enforcement / monitoring.
        per_call_limit_usd: Optional per-call spending cap.  When set,
            ``after_run`` checks whether a single call exceeded this
            limit and logs a warning (or raises if *warn_only* is
            ``False``).
    """

    def __init__(
        self,
        budget_usd: float,
        *,
        tracker: Any | None = None,
        warn_only: bool = False,
        per_call_limit_usd: float | None = None,
    ) -> None:
        self._budget = budget_usd
        self._tracker = tracker
        self._warn_only = warn_only
        self._per_call_limit = per_call_limit_usd

    def _get_tracker(self) -> Any:
        if self._tracker is not None:
            return self._tracker
        from fireflyframework_genai.observability.usage import default_usage_tracker

        return default_usage_tracker

    async def before_run(self, context: MiddlewareContext) -> None:
        """Block (or warn) if cumulative cost exceeds the budget."""
        tracker = self._get_tracker()
        current = tracker.cumulative_cost_usd
        # Snapshot cost before the call for per-call tracking
        context.metadata["_cost_before"] = current
        if current >= self._budget:
            msg = f"Budget exceeded for agent '{context.agent_name}': ${current:.4f} >= ${self._budget:.4f}"
            if self._warn_only:
                logger.warning("CostGuardMiddleware (warn-only): %s", msg)
            else:
                raise BudgetExceededError(msg)

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Check per-call cost limit after the run completes."""
        if self._per_call_limit is None:
            return result

        cost_before = context.metadata.get("_cost_before", 0.0)
        cost_after = self._get_tracker().cumulative_cost_usd
        call_cost = cost_after - cost_before

        if call_cost > self._per_call_limit:
            msg = (
                f"Per-call cost limit exceeded for agent '{context.agent_name}': "
                f"${call_cost:.4f} > ${self._per_call_limit:.4f}"
            )
            if self._warn_only:
                logger.warning("CostGuardMiddleware (warn-only): %s", msg)
            else:
                raise BudgetExceededError(msg)

        return result


# -- ObservabilityMiddleware -------------------------------------------------


class ObservabilityMiddleware:
    """Emits OpenTelemetry spans, metrics, and structured events for agent runs.

    Auto-wired by default when ``config.observability_enabled`` is ``True``.
    Creates a span covering the entire agent run, records latency and token
    metrics, and emits ``agent.started`` / ``agent.completed`` events.
    """

    async def before_run(self, context: MiddlewareContext) -> None:
        """Open an OTel span and emit the agent-started event."""
        from opentelemetry import trace as _trace

        tracer = _trace.get_tracer("fireflyframework_genai")
        span = tracer.start_span(
            f"agent.{context.agent_name}",
            attributes={
                "firefly.agent.name": context.agent_name,
                "firefly.agent.method": context.method or "run",
            },
        )
        context.metadata["_otel_span"] = span
        context.metadata["_obs_t0"] = time.monotonic()

        from fireflyframework_genai.observability.events import default_events

        default_events.agent_started(context.agent_name)

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Record OTel metrics and close the span.

        Note: the ``agent.completed`` **event** is intentionally NOT emitted
        here.  ``UsageTracker._emit_event()`` already emits the same event
        with strictly more detail (model name, cost, per-token breakdown).
        Emitting it in both places caused every agent call to log duplicate
        ``agent.completed`` entries.
        """
        t0 = context.metadata.get("_obs_t0")
        elapsed_ms = (time.monotonic() - t0) * 1000 if t0 is not None else 0.0

        tokens = 0
        usage = result.usage() if callable(getattr(result, "usage", None)) else None
        if usage is not None:
            tokens = getattr(usage, "total_tokens", 0) or 0

        from fireflyframework_genai.observability.metrics import default_metrics

        default_metrics.record_latency(
            elapsed_ms,
            operation="agent.run",
            agent=context.agent_name,
        )
        if tokens > 0:
            default_metrics.record_tokens(tokens, agent=context.agent_name)

        span = context.metadata.pop("_otel_span", None)
        if span is not None:
            span.end()

        return result


# -- ExplainabilityMiddleware ------------------------------------------------


class ExplainabilityMiddleware:
    """Records decision traces for explainability and audit.

    Captures :class:`DecisionRecord` entries via the
    :class:`~fireflyframework_genai.explainability.trace_recorder.TraceRecorder`.

    Unlike :class:`ObservabilityMiddleware`, this middleware is **not**
    auto-wired.  Enable it explicitly via the agent's ``middleware`` list.

    Parameters:
        recorder: A :class:`TraceRecorder`.  Defaults to the module-level
            ``default_trace_recorder``.
    """

    def __init__(self, *, recorder: Any | None = None) -> None:
        self._recorder = recorder

    def _get_recorder(self) -> Any:
        if self._recorder is not None:
            return self._recorder
        from fireflyframework_genai.explainability.trace_recorder import (
            default_trace_recorder,
        )

        return default_trace_recorder

    async def before_run(self, context: MiddlewareContext) -> None:
        """Record a decision at the start of the run."""
        self._get_recorder().record(
            "llm_call",
            agent=context.agent_name,
            input_summary=str(context.prompt)[:200] if context.prompt else "",
        )

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Record a decision with output information."""
        output_text = ""
        if hasattr(result, "output"):
            output_text = str(result.output)[:200]
        self._get_recorder().record(
            "llm_call",
            agent=context.agent_name,
            output_summary=output_text,
            detail={"method": context.method},
        )
        return result


# -- CacheMiddleware ---------------------------------------------------------


class CacheMiddleware:
    """Caches agent results via a :class:`ResultCache`.

    On ``before_run``, checks the cache.  If a hit is found the cached
    result is stored in ``context.metadata["_cache_result"]`` so that the
    agent run can be skipped.  On ``after_run``, stores the result on miss.

    Parameters:
        cache: A :class:`~fireflyframework_genai.agents.cache.ResultCache`.
    """

    def __init__(self, *, cache: Any) -> None:
        self._cache = cache

    async def before_run(self, context: MiddlewareContext) -> None:
        """Check the cache; on hit, store result in metadata."""
        prompt_str = str(context.prompt) if context.prompt is not None else ""
        cached = self._cache.get(context.agent_name, prompt_str)
        if cached is not None:
            context.metadata["_cache_result"] = cached
            logger.debug("CacheMiddleware: hit for agent '%s'", context.agent_name)

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Store the result in the cache on miss."""
        if "_cache_result" not in context.metadata:
            prompt_str = str(context.prompt) if context.prompt is not None else ""
            self._cache.put(context.agent_name, prompt_str, result)
        return result


# -- ValidationMiddleware ----------------------------------------------------


class OutputGuardMiddleware:
    """Scans LLM output for PII, secrets, harmful content, and custom patterns.

    When the guard detects unsafe content, the middleware either raises
    :class:`OutputGuardError` (default) or sanitises the output by replacing
    matched fragments with ``[REDACTED]``.

    Parameters:
        guard: An :class:`~fireflyframework_genai.security.output_guard.OutputGuard`
            instance.  Defaults to the module-level ``default_output_guard``.
        sanitise: When *True*, sanitise the output instead of rejecting.
        block_categories: Only block on these categories (e.g. ``["secrets", "pii"]``).
            When empty (default), all categories trigger blocking.
    """

    def __init__(
        self,
        *,
        guard: Any | None = None,
        sanitise: bool = False,
        block_categories: list[str] | None = None,
    ) -> None:
        if guard is not None:
            self._guard = guard
        else:
            from fireflyframework_genai.security.output_guard import OutputGuard

            self._guard = OutputGuard(sanitise=sanitise)
        self._sanitise = sanitise
        self._block_categories = block_categories

    async def before_run(self, context: MiddlewareContext) -> None:
        """No pre-processing needed."""

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Scan the output; reject or sanitise if unsafe."""
        output_text = ""
        if hasattr(result, "output"):
            output_text = str(result.output)
        elif isinstance(result, str):
            output_text = result
        else:
            output_text = str(result)

        if not output_text:
            return result

        scan_result = self._guard.scan(output_text)
        if scan_result.safe:
            return result

        # If block_categories is set, only block on matching categories
        if self._block_categories:
            blocking = [c for c in scan_result.matched_categories if c in self._block_categories]
            if not blocking:
                return result

        if self._sanitise and scan_result.sanitised_output is not None:
            logger.warning(
                "OutputGuardMiddleware: sanitised output for agent '%s' (%d pattern(s) matched in %s)",
                context.agent_name,
                len(scan_result.matched_patterns),
                scan_result.matched_categories,
            )
            # Replace the output in the result if possible (e.g. NamedTuple results)
            if hasattr(result, "output") and hasattr(result, "_replace"):
                return result._replace(output=scan_result.sanitised_output)  # type: ignore[union-attr]
            return scan_result.sanitised_output

        raise OutputGuardError(f"Output blocked for agent '{context.agent_name}': {scan_result.reason}")


class ValidationMiddleware:
    """Validates agent output using an :class:`OutputReviewer`.

    After the agent runs, the output is parsed and validated without
    re-running the agent.  If validation fails, an
    :class:`~fireflyframework_genai.exceptions.OutputReviewError` is raised.

    Parameters:
        reviewer: An :class:`OutputReviewer` whose parsing and validation
            logic is applied to the result.
    """

    def __init__(self, *, reviewer: Any) -> None:
        self._reviewer = reviewer

    async def before_run(self, context: MiddlewareContext) -> None:
        """No pre-processing needed."""

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Validate the output; raise on failure."""
        raw = result.output if hasattr(result, "output") else result

        parsed, parse_errors = self._reviewer._parse_output(raw)
        if parse_errors:
            from fireflyframework_genai.exceptions import OutputReviewError

            raise OutputReviewError(f"Output validation failed: {parse_errors}")

        validated = parsed if parsed is not None else raw
        report = self._reviewer._validate_output(validated)
        if report is not None and not report.valid:
            rule_errors = [r.message for r in report.errors if r.message]
            from fireflyframework_genai.exceptions import OutputReviewError

            raise OutputReviewError(f"Validation rules failed: {rule_errors}")

        return result
