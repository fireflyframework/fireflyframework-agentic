# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Pluggable output sinks for :class:`UsageRecord`."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

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
