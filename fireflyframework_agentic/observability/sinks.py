# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Pluggable output sinks for :class:`UsageRecord`."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fireflyframework_agentic.observability.events import default_events
from fireflyframework_agentic.observability.metrics import default_metrics

if TYPE_CHECKING:
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
            default_metrics.record_tokens(record.total_tokens, agent=record.agent, model=record.model)
        if record.input_tokens > 0:
            default_metrics.record_prompt_tokens(record.input_tokens, agent=record.agent, model=record.model)
        if record.output_tokens > 0:
            default_metrics.record_completion_tokens(record.output_tokens, agent=record.agent, model=record.model)
        if record.cost_usd > 0:
            default_metrics.record_cost(record.cost_usd, agent=record.agent, model=record.model)
        if record.latency_ms > 0:
            default_metrics.record_latency(record.latency_ms, operation="agent.run", agent=record.agent)

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


class LoggingSink:
    """Log each record at INFO via the module logger."""

    def __init__(self, level: int = logging.INFO) -> None:
        self._level = level

    def emit(self, record: UsageRecord) -> None:
        logger.log(self._level, "cost_record %s", record.model_dump_json())

    def flush(self) -> None: ...
    def close(self) -> None: ...


class JSONLFileSink:
    """Append-only JSONL writer with optional size-based rotation.

    Parameters:
        path: Output file path. Created on first emit if missing.
        rotate_bytes: When set, rotate the file to ``path.N`` once it exceeds
            this size. Rotation is checked on each emit (O(1) ``stat``).
    """

    def __init__(self, path: Path | str, *, rotate_bytes: int | None = None) -> None:
        self._path = Path(path)
        self._rotate_bytes = rotate_bytes
        self._lock = threading.Lock()

    def emit(self, record: UsageRecord) -> None:
        line = record.model_dump_json() + "\n"
        with self._lock:
            self._maybe_rotate(len(line))
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def _maybe_rotate(self, incoming_bytes: int) -> None:
        if self._rotate_bytes is None or not self._path.exists():
            return
        if self._path.stat().st_size + incoming_bytes <= self._rotate_bytes:
            return
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        rotated = self._path.with_suffix(self._path.suffix + f".{stamp}")
        self._path.rename(rotated)

    def flush(self) -> None: ...
    def close(self) -> None: ...
