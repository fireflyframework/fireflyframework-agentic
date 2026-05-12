# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Tests for cost sinks."""

import logging

import pytest

from fireflyframework_agentic.observability.sinks import CostSink, _emit_safely
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
