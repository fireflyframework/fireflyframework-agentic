# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Tests for cost sinks."""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from fireflyframework_agentic.observability.sinks import (
    CostSink,
    EventBusSink,
    JSONLFileSink,
    LoggingSink,
    OTelMetricsSink,
    _emit_safely,
)
from fireflyframework_agentic.observability.usage import UsageRecord


class _GoodSink:
    def __init__(self) -> None:
        self.received: list[UsageRecord] = []

    def emit(self, record: UsageRecord) -> None:
        self.received.append(record)

    def flush(self) -> None: ...

    def close(self) -> None: ...


class _BadSink:
    def emit(self, record: UsageRecord) -> None:
        raise RuntimeError("boom")

    def flush(self) -> None: ...

    def close(self) -> None: ...


def test_emit_safely_passes_record_through() -> None:
    sink = _GoodSink()
    rec = UsageRecord(agent="a", total_tokens=10)
    _emit_safely(sink, rec)
    assert sink.received == [rec]


def test_emit_safely_swallows_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        _emit_safely(_BadSink(), UsageRecord())
    assert any("_BadSink" in r.message or "sink" in r.message.lower() for r in caplog.records)


def test_cost_sink_protocol_is_runtime_checkable() -> None:
    assert isinstance(_GoodSink(), CostSink)


def test_otel_metrics_sink_calls_record_tokens() -> None:
    rec = UsageRecord(agent="a", model="openai:gpt-4o",
                      input_tokens=10, output_tokens=5, total_tokens=15,
                      cost_usd=0.001, latency_ms=200.0)
    with patch("fireflyframework_agentic.observability.sinks.default_metrics") as m:
        OTelMetricsSink().emit(rec)
        m.record_tokens.assert_called_with(15, agent="a", model="openai:gpt-4o")
        m.record_prompt_tokens.assert_called_with(10, agent="a", model="openai:gpt-4o")
        m.record_completion_tokens.assert_called_with(5, agent="a", model="openai:gpt-4o")
        m.record_cost.assert_called_with(0.001, agent="a", model="openai:gpt-4o")
        m.record_latency.assert_called_with(200.0, operation="agent.run", agent="a")


def test_event_bus_sink_calls_agent_completed() -> None:
    rec = UsageRecord(agent="a", model="x", total_tokens=10,
                      input_tokens=6, output_tokens=4, latency_ms=50.0, cost_usd=0.01)
    with patch("fireflyframework_agentic.observability.sinks.default_events") as e:
        EventBusSink().emit(rec)
        e.agent_completed.assert_called_once_with(
            "a", tokens=10, latency_ms=50.0, model="x",
            cost_usd=0.01, input_tokens=6, output_tokens=4,
        )


def test_logging_sink_emits_at_info(caplog: pytest.LogCaptureFixture) -> None:
    rec = UsageRecord(agent="a", total_tokens=5, cost_usd=0.001)
    with caplog.at_level(logging.INFO, logger="fireflyframework_agentic.observability.sinks"):
        LoggingSink().emit(rec)
    assert any('"agent":"a"' in r.message or "'agent': 'a'" in r.message
               or "a" in r.message for r in caplog.records)


def test_jsonl_file_sink_writes_one_line_per_record(tmp_path: Path) -> None:
    path = tmp_path / "cost.jsonl"
    sink = JSONLFileSink(path)
    sink.emit(UsageRecord(agent="a1", cost_usd=0.1))
    sink.emit(UsageRecord(agent="a2", cost_usd=0.2))
    sink.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["agent"] == "a1"
    assert json.loads(lines[1])["agent"] == "a2"


def test_jsonl_file_sink_rotation(tmp_path: Path) -> None:
    path = tmp_path / "cost.jsonl"
    sink = JSONLFileSink(path, rotate_bytes=64)  # tiny size to force rotation
    for i in range(20):
        sink.emit(UsageRecord(agent=f"a{i}"))
    sink.close()
    rotated = list(tmp_path.glob("cost.jsonl*"))
    assert len(rotated) > 1
