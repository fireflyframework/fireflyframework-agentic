# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Pluggable output sinks for :class:`UsageRecord`."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Protocol, runtime_checkable

import httpx

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


def _default_post(url: str, json: list[dict], headers: dict, timeout: float) -> Any:
    """Default POST function. Replaced in tests via WebhookSink(_post=...)."""
    return httpx.post(url, json=json, headers=headers, timeout=timeout)


class WebhookSink:
    """Batch records and POST them to an HTTP endpoint.

    Parameters:
        url: Endpoint URL.
        batch_size: Records per POST. Drained sooner on ``flush_interval_s``.
        flush_interval_s: Background flush cadence in seconds.
        headers: Extra HTTP headers (Authorization, etc.).
        max_retries: How many times to retry a 5xx response before dropping.
        timeout_s: Per-request HTTP timeout.
        _post: Internal hook for tests.
    """

    def __init__(
        self,
        url: str,
        *,
        batch_size: int = 50,
        flush_interval_s: float = 5.0,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        timeout_s: float = 10.0,
        _post: Callable[[str, list[dict], dict, float], Any] | None = None,
    ) -> None:
        self._url = url
        self._batch_size = batch_size
        self._interval = flush_interval_s
        self._headers = headers or {}
        self._max_retries = max_retries
        self._timeout = timeout_s
        self._post = _post or _default_post
        self._queue: Queue[UsageRecord] = Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="WebhookSink", daemon=True)
        self._thread.start()

    def emit(self, record: UsageRecord) -> None:
        self._queue.put(record)

    def _run(self) -> None:
        buf: list[UsageRecord] = []
        last_flush = time.monotonic()
        while not self._stop.is_set():
            try:
                rec = self._queue.get(timeout=0.1)
                buf.append(rec)
            except Empty:
                pass
            now = time.monotonic()
            if len(buf) >= self._batch_size or (buf and now - last_flush >= self._interval):
                self._send(buf)
                buf = []
                last_flush = now
        # Drain remaining on stop.
        while True:
            try:
                buf.append(self._queue.get_nowait())
            except Empty:
                break
        if buf:
            self._send(buf)

    def _send(self, batch: list[UsageRecord]) -> None:
        payload = [r.model_dump(mode="json") for r in batch]
        delay = 0.1
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._post(self._url, payload, self._headers, self._timeout)
                status = int(getattr(resp, "status_code", 0))
                if 200 <= status < 300:
                    return
                if 500 <= status < 600 and attempt < self._max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.warning("WebhookSink: dropping batch (status %d)", status)
                self._record_sink_error()
                return
            except Exception:  # noqa: BLE001
                if attempt < self._max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.warning("WebhookSink: dropping batch after exhausted retries",
                               exc_info=True)
                self._record_sink_error()
                return

    @staticmethod
    def _record_sink_error() -> None:
        try:
            default_metrics.record_error(operation="cost_sink_errors")
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit cost_sink_errors metric", exc_info=True)

    def flush(self) -> None:
        """Block until the queue is empty (best-effort)."""
        while not self._queue.empty():
            time.sleep(0.01)

    def close(self) -> None:
        """Stop background thread and drain remaining records."""
        self._stop.set()
        self._thread.join(timeout=self._interval + 2.0)
