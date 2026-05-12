# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Pluggable output sinks for :class:`UsageRecord`."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from fireflyframework_agentic.observability.events import default_events
from fireflyframework_agentic.observability.metrics import default_metrics
from fireflyframework_agentic.observability.usage import UsageRecord

logger = logging.getLogger(__name__)


@runtime_checkable
class CostSink(Protocol):
    """Receives one :class:`UsageRecord` per LLM call."""

    def emit(self, record: UsageRecord) -> None: ...

    def flush(self) -> None: ...  # default no-op; override if buffering.

    def close(self) -> None: ...  # default no-op; override to drain.


def _emit_safely(sink: CostSink, record: UsageRecord) -> None:
    """Call ``sink.emit(record)``, swallowing all exceptions.

    Increments the ``cost_sink_errors`` counter when emission fails.
    """
    try:
        sink.emit(record)
    except Exception:  # noqa: BLE001
        sink_name = type(sink).__name__
        logger.warning("Sink %s.emit() raised; record dropped", sink_name, exc_info=True)
        try:
            default_metrics.record_error(operation="cost_sink_errors")
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit cost_sink_errors metric", exc_info=True)


class OTelMetricsSink:
    """Forward token, cost, and latency observations to ``default_metrics``.

    Mirrors the legacy ``UsageTracker._emit_metrics`` behavior exactly.
    """

    def emit(self, record: UsageRecord) -> None:
        if record.total_tokens > 0:
            default_metrics.record_tokens(
                record.total_tokens, agent=record.agent, model=record.model
            )
        if record.input_tokens > 0:
            default_metrics.record_prompt_tokens(
                record.input_tokens, agent=record.agent, model=record.model
            )
        if record.output_tokens > 0:
            default_metrics.record_completion_tokens(
                record.output_tokens, agent=record.agent, model=record.model
            )
        if record.cost_usd > 0:
            default_metrics.record_cost(
                record.cost_usd, agent=record.agent, model=record.model
            )
        if record.latency_ms > 0:
            default_metrics.record_latency(
                record.latency_ms, operation="agent.run", agent=record.agent
            )

    def flush(self) -> None: ...
    def close(self) -> None: ...


class EventBusSink:
    """Forward each record as an ``agent_completed`` event."""

    def emit(self, record: UsageRecord) -> None:
        default_events.agent_completed(
            record.agent,
            tokens=record.total_tokens,
            latency_ms=record.latency_ms,
            model=record.model,
            cost_usd=record.cost_usd,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
        )

    def flush(self) -> None: ...
    def close(self) -> None: ...
