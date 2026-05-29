# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Audit-log tests — File / Logging / OTel backends + pipeline wiring.

PostgresAuditLog used to live in the framework and was tested here with mocks;
it moved to ``examples/software_factory/audit/postgres.py`` as a plug-and-play
template.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

import fireflyframework_agentic.pipeline.audit as audit_module
from fireflyframework_agentic.pipeline import (
    AuditEntry,
    FileAuditLog,
    LoggingAuditLog,
    OtelAuditLog,
    Pause,
    PipelineBuilder,
)


def _entry(**overrides: Any) -> AuditEntry:
    defaults = {
        "pipeline_name": "p",
        "run_id": "r",
        "node_id": "n",
        "sequence": 1,
        "visit": 1,
        "started_at": datetime(2026, 5, 27, tzinfo=UTC),
        "completed_at": datetime(2026, 5, 27, 0, 0, 1, tzinfo=UTC),
        "latency_ms": 100.0,
        "status": "success",
        "inputs_snapshot": {"x": 1},
        "outputs_snapshot": {"y": 2},
    }
    defaults.update(overrides)
    return AuditEntry(**defaults)  # type: ignore[arg-type]


# =============================================================================
# FileAuditLog
# =============================================================================


def test_file_audit_log_writes_jsonl_per_run(tmp_path: Path) -> None:
    log = FileAuditLog(tmp_path)
    log.record(_entry(sequence=1, node_id="a"))
    log.record(_entry(sequence=2, node_id="b"))

    path = tmp_path / "p" / "r.jsonl"
    assert path.exists()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["node_id"] == "a"
    assert json.loads(lines[1])["node_id"] == "b"


def test_file_audit_log_list_entries_round_trips(tmp_path: Path) -> None:
    log = FileAuditLog(tmp_path)
    for seq, node in [(1, "a"), (2, "b"), (3, "c")]:
        log.record(_entry(sequence=seq, node_id=node))
    entries = log.list_entries("p", "r")
    assert [e.node_id for e in entries] == ["a", "b", "c"]


def test_file_audit_log_unknown_run_returns_empty(tmp_path: Path) -> None:
    assert FileAuditLog(tmp_path).list_entries("p", "missing") == []


# =============================================================================
# Optional-dep stubs for OTel
# =============================================================================


@pytest.fixture(autouse=True)
def _stub_optional_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub OTel symbols so OtelAuditLog can be constructed with mocks."""
    if audit_module._otel_get_logger is None:
        monkeypatch.setattr(audit_module, "_otel_get_logger", MagicMock(name="otel_logger_factory"))
        monkeypatch.setattr(audit_module, "_OtelLogRecord", MagicMock(name="LogRecord"))
        sev = MagicMock(name="SeverityNumber")
        sev.ERROR = MagicMock(name="ERROR")
        sev.ERROR.name = "ERROR"
        sev.INFO = MagicMock(name="INFO")
        sev.INFO.name = "INFO"
        monkeypatch.setattr(audit_module, "_OtelSeverityNumber", sev)


# =============================================================================
# LoggingAuditLog
# =============================================================================


def test_logging_audit_emits_record_with_firefly_audit_extra(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = LoggingAuditLog(logger_name="firefly.test_audit")
    with caplog.at_level(logging.INFO, logger="firefly.test_audit"):
        log.record(_entry(node_id="z", status="success"))
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert "firefly_audit" in rec.__dict__
    assert rec.__dict__["firefly_audit"]["node_id"] == "z"
    assert rec.__dict__["firefly_audit"]["status"] == "success"


# =============================================================================
# OtelAuditLog
# =============================================================================


def test_otel_audit_missing_dep_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_module, "_otel_get_logger", None)
    with pytest.raises(ImportError, match="opentelemetry-sdk"):
        OtelAuditLog()


def test_otel_audit_emits_log_record_via_otel_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = MagicMock(name="otel_logger")
    factory = MagicMock(name="get_logger", return_value=mock_logger)
    monkeypatch.setattr(audit_module, "_otel_get_logger", factory)

    log = OtelAuditLog()
    log.record(_entry(node_id="a", status="success"))

    factory.assert_called_once()
    assert mock_logger.emit.called, "OtelAuditLog should call logger.emit() with a LogRecord"


# =============================================================================
# Pipeline wiring — audit fires for every node visit
# =============================================================================


class S(BaseModel):
    log: str = ""


@pytest.mark.asyncio
async def test_pipeline_writes_one_audit_entry_per_node_visit(tmp_path: Path) -> None:
    async def a(state: S) -> dict:
        return {"log": "a"}

    async def b(state: S) -> dict:
        return {"log": "b"}

    audit = FileAuditLog(tmp_path)
    pipeline = PipelineBuilder("audit-test", state=S, audit_log=audit).add_node(a).add_node(b).chain(a, b).build()
    result = await pipeline.invoke(S())
    entries = audit.list_entries("audit-test", result.run_id)
    assert [e.node_id for e in entries] == ["a", "b"]
    assert all(e.status == "success" for e in entries)


@pytest.mark.asyncio
async def test_pipeline_audit_captures_error_status(tmp_path: Path) -> None:
    async def boom(state: S) -> dict:
        raise RuntimeError("nope")

    audit = FileAuditLog(tmp_path)
    pipeline = PipelineBuilder("audit-err", state=S, audit_log=audit).add_node(boom).build()
    result = await pipeline.invoke(S())
    entries = audit.list_entries("audit-err", result.run_id)
    assert len(entries) == 1
    assert entries[0].status == "error"
    assert "nope" in (entries[0].error_message or "")


@pytest.mark.asyncio
async def test_pipeline_audit_captures_paused_status(tmp_path: Path) -> None:
    async def gate(state: S) -> Pause:
        return Pause(reason="approval please")

    audit = FileAuditLog(tmp_path / "audit")
    from fireflyframework_agentic.pipeline import FileCheckpointer

    pipeline = (
        PipelineBuilder(
            "audit-pause",
            state=S,
            audit_log=audit,
            checkpointer=FileCheckpointer(tmp_path / "ckpt"),
        )
        .add_node(gate)
        .build()
    )
    result = await pipeline.invoke(S())
    entries = audit.list_entries("audit-pause", result.run_id)
    assert len(entries) == 1
    assert entries[0].status == "paused"
    assert entries[0].pause_reason == "approval please"


@pytest.mark.asyncio
async def test_audit_write_failure_does_not_abort_pipeline(tmp_path: Path) -> None:
    """A broken audit log shouldn't kill business logic."""

    class CrashyAudit:
        def record(self, entry: AuditEntry) -> None:
            raise RuntimeError("audit storage offline")

    async def step(state: S) -> dict:
        return {"log": "ran"}

    pipeline = (
        PipelineBuilder("crashy", state=S, audit_log=CrashyAudit())  # type: ignore[arg-type]
        .add_node(step)
        .build()
    )
    result = await pipeline.invoke(S())
    assert result.success is True
    assert result.state.log == "ran"
