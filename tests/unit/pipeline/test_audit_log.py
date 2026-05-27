# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Phase-3c audit-log tests — File / Postgres / Logging / OTel backends + pipeline wiring."""

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
    PostgresAuditLog,
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
# PostgresAuditLog
# =============================================================================


@pytest.fixture(autouse=True)
def _stub_optional_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub _psycopg and OTel symbols so backends can be constructed with mocks."""
    if audit_module._psycopg is None:
        monkeypatch.setattr(audit_module, "_psycopg", MagicMock(name="psycopg_stub"))
    if audit_module._otel_get_logger is None:
        monkeypatch.setattr(audit_module, "_otel_get_logger", MagicMock(name="otel_logger_factory"))
        monkeypatch.setattr(audit_module, "_OtelLogRecord", MagicMock(name="LogRecord"))
        sev = MagicMock(name="SeverityNumber")
        sev.ERROR = MagicMock(name="ERROR")
        sev.ERROR.name = "ERROR"
        sev.INFO = MagicMock(name="INFO")
        sev.INFO.name = "INFO"
        monkeypatch.setattr(audit_module, "_OtelSeverityNumber", sev)


def test_postgres_audit_missing_dep_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_module, "_psycopg", None)
    with pytest.raises(ImportError, match=r"\[postgres\]"):
        PostgresAuditLog(dsn="postgresql://x")


def _pg_conn_mock() -> tuple[MagicMock, dict]:
    """MagicMock connection backed by an in-memory dict keyed by (pipeline,run,seq)."""
    store: dict[tuple[str, str, int], dict[str, Any]] = {}
    ddl_calls: list[str] = []
    conn = MagicMock(name="psycopg.Connection")

    def make_cursor() -> MagicMock:
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=None)
        cur._last_one = None
        cur._last_all = []

        def fake_execute(sql: str, params: tuple | None = None) -> None:
            s = sql.strip().lower()
            if s.startswith("create table"):
                ddl_calls.append(sql)
                return
            if s.startswith("insert into"):
                assert params is not None
                key = (params[0], params[1], params[2])
                store[key] = {
                    "pipeline_name": params[0],
                    "run_id": params[1],
                    "sequence": params[2],
                    "visit": params[3],
                    "node_id": params[4],
                    "started_at": params[5],
                    "completed_at": params[6],
                    "latency_ms": params[7],
                    "status": params[8],
                    "inputs_snapshot": json.loads(params[9]) if isinstance(params[9], str) else params[9],
                    "outputs_snapshot": json.loads(params[10]) if isinstance(params[10], str) else params[10],
                    "error_message": params[11],
                    "pause_reason": params[12],
                }
                return
            if s.startswith("select"):
                assert params is not None
                rows = [v for k, v in store.items() if k[0] == params[0] and k[1] == params[1]]
                rows.sort(key=lambda r: r["sequence"])
                cur._last_all = [
                    (
                        r["pipeline_name"],
                        r["run_id"],
                        r["sequence"],
                        r["visit"],
                        r["node_id"],
                        r["started_at"],
                        r["completed_at"],
                        r["latency_ms"],
                        r["status"],
                        r["inputs_snapshot"],
                        r["outputs_snapshot"],
                        r["error_message"],
                        r["pause_reason"],
                    )
                    for r in rows
                ]
                return
            raise AssertionError(f"unexpected SQL: {sql}")

        cur.execute.side_effect = fake_execute
        cur.fetchone.side_effect = lambda: cur._last_one
        cur.fetchall.side_effect = lambda: cur._last_all
        return cur

    conn.cursor.side_effect = make_cursor
    conn._ddl_calls = ddl_calls
    return conn, store


def test_postgres_audit_ddl_once_then_inserts() -> None:
    conn, store = _pg_conn_mock()
    log = PostgresAuditLog(connection=conn)
    for seq in (1, 2, 3):
        log.record(_entry(sequence=seq, node_id=f"n{seq}"))
    assert len(conn._ddl_calls) == 1
    assert len(store) == 3


def test_postgres_audit_list_entries_orders_by_sequence() -> None:
    conn, _ = _pg_conn_mock()
    log = PostgresAuditLog(connection=conn)
    for seq in (3, 1, 2):
        log.record(_entry(sequence=seq, node_id=f"n{seq}"))
    entries = log.list_entries("p", "r")
    assert [e.sequence for e in entries] == [1, 2, 3]


def test_postgres_audit_rejects_bad_table_name() -> None:
    with pytest.raises(ValueError, match="Invalid table_name"):
        PostgresAuditLog(connection=MagicMock(), table_name="bad; DROP TABLE")


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
