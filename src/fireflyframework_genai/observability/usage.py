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

"""Usage tracking for LLM API calls.

:class:`UsageTracker` is the central accumulator for token usage, cost,
and latency across all agents, reasoning patterns, and pipeline nodes.
Each call is captured as a :class:`UsageRecord` and automatically emitted
to :class:`~fireflyframework_genai.observability.metrics.FireflyMetrics`
and :class:`~fireflyframework_genai.observability.events.FireflyEvents`.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class UsageRecord(BaseModel):
    """A single LLM usage observation.

    Attributes:
        agent: Name of the agent that made the call.
        model: Model identifier (e.g. ``"openai:gpt-4o"``).
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.
        total_tokens: Combined token count.
        cache_creation_tokens: Tokens written to prompt cache.
        cache_read_tokens: Tokens read from prompt cache.
        request_count: Number of LLM requests in this run.
        cost_usd: Estimated cost in USD.
        latency_ms: Wall-clock time in milliseconds.
        timestamp: When the usage was recorded.
        correlation_id: Optional ID linking records to a pipeline run.
    """

    agent: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    request_count: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = ""


class UsageSummary(BaseModel):
    """Aggregated usage statistics.

    Attributes:
        total_input_tokens: Sum of all input tokens.
        total_output_tokens: Sum of all output tokens.
        total_tokens: Sum of all tokens.
        total_cost_usd: Sum of estimated costs.
        total_requests: Sum of LLM request counts.
        total_latency_ms: Sum of latencies.
        record_count: Number of individual usage records.
        by_agent: Per-agent breakdown of tokens, cost, and requests.
        by_model: Per-model breakdown of tokens, cost, and requests.
    """

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_requests: int = 0
    total_latency_ms: float = 0.0
    record_count: int = 0
    by_agent: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_model: dict[str, dict[str, Any]] = Field(default_factory=dict)


def _aggregate(records: list[UsageRecord]) -> UsageSummary:
    """Build a :class:`UsageSummary` from a list of records."""
    by_agent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "requests": 0}
    )
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "requests": 0}
    )
    total_in = total_out = total_tok = total_req = 0
    total_cost = total_lat = 0.0

    for r in records:
        total_in += r.input_tokens
        total_out += r.output_tokens
        total_tok += r.total_tokens
        total_req += r.request_count
        total_cost += r.cost_usd
        total_lat += r.latency_ms

        if r.agent:
            a = by_agent[r.agent]
            a["input_tokens"] += r.input_tokens
            a["output_tokens"] += r.output_tokens
            a["total_tokens"] += r.total_tokens
            a["cost_usd"] += r.cost_usd
            a["requests"] += r.request_count

        if r.model:
            m = by_model[r.model]
            m["input_tokens"] += r.input_tokens
            m["output_tokens"] += r.output_tokens
            m["total_tokens"] += r.total_tokens
            m["cost_usd"] += r.cost_usd
            m["requests"] += r.request_count

    return UsageSummary(
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_tokens=total_tok,
        total_cost_usd=total_cost,
        total_requests=total_req,
        total_latency_ms=total_lat,
        record_count=len(records),
        by_agent=dict(by_agent),
        by_model=dict(by_model),
    )


class UsageTracker:
    """Thread-safe accumulator for LLM usage records.

    When :meth:`record` is called, the tracker:

    1. Appends the record to the internal list.
    2. Emits token and cost metrics via :class:`FireflyMetrics`.
    3. Emits a structured event via :class:`FireflyEvents`.
    4. Checks budget thresholds and logs warnings.

    Parameters:
        max_records: Maximum number of records to retain in memory.
            When exceeded, the oldest records are evicted (FIFO).
            ``0`` means unlimited (not recommended for long-running services).
    """

    def __init__(self, *, max_records: int = 0) -> None:
        self._records: list[UsageRecord] = []
        self._lock = threading.Lock()
        self._cumulative_cost: float = 0.0
        self._max_records = max_records

    def record(self, usage: UsageRecord) -> None:
        """Append a usage record and emit to observability sinks."""
        with self._lock:
            self._records.append(usage)
            self._cumulative_cost += usage.cost_usd
            # Evict oldest records when limit is exceeded
            if self._max_records > 0 and len(self._records) > self._max_records:
                excess = len(self._records) - self._max_records
                del self._records[:excess]

        # Emit to OTel metrics
        self._emit_metrics(usage)

        # Emit structured event
        self._emit_event(usage)

        # Check budget
        self._check_budget(usage)

    @property
    def records(self) -> list[UsageRecord]:
        """Read-only copy of all recorded usage."""
        with self._lock:
            return list(self._records)

    @property
    def cumulative_cost_usd(self) -> float:
        """Running total cost across all records."""
        with self._lock:
            return self._cumulative_cost

    def get_summary(self) -> UsageSummary:
        """Aggregate summary of all records."""
        with self._lock:
            return _aggregate(list(self._records))

    def get_summary_for_agent(self, agent_name: str) -> UsageSummary:
        """Aggregate summary filtered by agent name."""
        with self._lock:
            filtered = [r for r in self._records if r.agent == agent_name]
        return _aggregate(filtered)

    def get_summary_for_correlation(self, correlation_id: str) -> UsageSummary:
        """Aggregate summary filtered by correlation ID (pipeline run)."""
        with self._lock:
            filtered = [r for r in self._records if r.correlation_id == correlation_id]
        return _aggregate(filtered)

    def reset(self) -> None:
        """Clear all records and reset cumulative cost."""
        with self._lock:
            self._records.clear()
            self._cumulative_cost = 0.0

    @staticmethod
    def _emit_metrics(usage: UsageRecord) -> None:
        """Send usage data to OTel metrics."""
        try:
            from fireflyframework_genai.observability.metrics import default_metrics

            if usage.total_tokens > 0:
                default_metrics.record_tokens(usage.total_tokens, agent=usage.agent, model=usage.model)
            if usage.input_tokens > 0:
                default_metrics.record_prompt_tokens(usage.input_tokens, agent=usage.agent, model=usage.model)
            if usage.output_tokens > 0:
                default_metrics.record_completion_tokens(usage.output_tokens, agent=usage.agent, model=usage.model)
            if usage.cost_usd > 0:
                default_metrics.record_cost(usage.cost_usd, agent=usage.agent, model=usage.model)
            if usage.latency_ms > 0:
                default_metrics.record_latency(usage.latency_ms, operation="agent.run", agent=usage.agent)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit usage metrics", exc_info=True)

    @staticmethod
    def _emit_event(usage: UsageRecord) -> None:
        """Emit a structured event for the usage record."""
        try:
            from fireflyframework_genai.observability.events import default_events

            default_events.agent_completed(
                usage.agent,
                tokens=usage.total_tokens,
                latency_ms=usage.latency_ms,
                model=usage.model,
                cost_usd=usage.cost_usd,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit usage event", exc_info=True)

    def _check_budget(self, usage: UsageRecord) -> None:
        """Log warnings when budget thresholds are exceeded."""
        try:
            from fireflyframework_genai.config import get_config

            cfg = get_config()
            if not cfg.cost_tracking_enabled:
                return

            cumulative = self.cumulative_cost_usd

            if cfg.budget_alert_threshold_usd is not None and cumulative >= cfg.budget_alert_threshold_usd:
                logger.warning(
                    "Budget alert: cumulative cost $%.4f has reached the alert threshold of $%.4f (agent=%s, model=%s)",
                    cumulative,
                    cfg.budget_alert_threshold_usd,
                    usage.agent,
                    usage.model,
                )

            if cfg.budget_limit_usd is not None and cumulative >= cfg.budget_limit_usd:
                logger.warning(
                    "Budget EXCEEDED: cumulative cost $%.4f has exceeded the limit of $%.4f (agent=%s, model=%s)",
                    cumulative,
                    cfg.budget_limit_usd,
                    usage.agent,
                    usage.model,
                )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to check budget", exc_info=True)


def _create_default_tracker() -> UsageTracker:
    """Create the default tracker with config-driven max_records."""
    try:
        from fireflyframework_genai.config import get_config

        return UsageTracker(max_records=get_config().usage_tracker_max_records)
    except Exception:  # noqa: BLE001
        return UsageTracker(max_records=10_000)


# Module-level singleton
default_usage_tracker = _create_default_tracker()
