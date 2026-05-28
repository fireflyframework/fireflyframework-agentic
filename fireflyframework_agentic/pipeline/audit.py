# Copyright 2026 Firefly Software Foundation
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

"""Append-only audit logs for state-pipeline node visits.

Distinct from :mod:`fireflyframework_agentic.pipeline.checkpoint` — the
checkpointer stores the *latest* state for crash recovery; the audit log
stores *every* node visit for compliance, debugging, and replay.

Four backends ship:

* :class:`FileAuditLog` — one JSONL file per ``(pipeline_name, run_id)``.
  Best for dev / single-host audit trails.
* :class:`PostgresAuditLog` — single ``firefly_audit`` table; reuses the
  ``psycopg`` connection from the ``postgres`` optional extra (same dep
  added in Phase 3a for ``PostgresCheckpointer``).
* :class:`LoggingAuditLog` — stdlib ``logging``; pairs with whatever log
  aggregation pipeline (Splunk-HEC, Loki, Datadog, OTel-LoggingHandler-bridge)
  the host application already runs. No new optional dep.
* :class:`OtelAuditLog` — direct OTel logs API; attaches trace correlation
  (``trace_id``/``span_id``) automatically. Best for OTel-native stacks
  (Application Insights, Datadog APM, OTel-Collector).

File and Postgres also implement :class:`QueryableAuditLog` (``list_entries``);
Logging and OTel are write-only — query your observability stack instead.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from fireflyframework_agentic.pipeline._psycopg_backend import PsycopgBackend

try:
    from opentelemetry._logs import LogRecord as _OtelLogRecord  # type: ignore[import-not-found]
    from opentelemetry._logs import SeverityNumber as _OtelSeverityNumber  # type: ignore[import-not-found]
    from opentelemetry._logs import get_logger as _otel_get_logger  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    _otel_get_logger = None  # type: ignore[assignment]
    _OtelLogRecord = None  # type: ignore[assignment,misc]
    _OtelSeverityNumber = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


AuditStatus = Literal["success", "error", "paused"]


class AuditEntry(BaseModel):
    """A single audit record — one per node visit (success, error, or pause)."""

    pipeline_name: str
    run_id: str
    node_id: str
    sequence: int
    visit: int
    started_at: datetime
    completed_at: datetime
    latency_ms: float
    status: AuditStatus
    inputs_snapshot: dict[str, Any]
    outputs_snapshot: dict[str, Any]
    error_message: str | None = None
    pause_reason: str | None = None


@runtime_checkable
class AuditLog(Protocol):
    """Write-only audit log. Every backend implements this method.

    Implementations must be safe to call from async code (called inside the
    state pipeline's executor) but the method itself is sync.
    """

    def record(self, entry: AuditEntry) -> None: ...


@runtime_checkable
class QueryableAuditLog(AuditLog, Protocol):
    """Audit log that also supports reading back recorded entries.

    File and Postgres backends implement this. Logging and OTel backends do
    not — query your observability stack (Splunk / Datadog / Loki / etc.)
    instead.
    """

    def list_entries(self, pipeline_name: str, run_id: str) -> list[AuditEntry]: ...


class FileAuditLog:
    """Filesystem-backed audit log. Layout::

        <root>/<pipeline_name>/<run_id>.jsonl

    Each line is a JSON-serialized :class:`AuditEntry`. Appends are atomic
    at the line level (single ``write`` call per entry); concurrent writers
    to the same run_id may interleave at line boundaries but never within a
    single entry.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, pipeline_name: str, run_id: str) -> Path:
        return self._root / pipeline_name / f"{run_id}.jsonl"

    def record(self, entry: AuditEntry) -> None:
        path = self._path(entry.pipeline_name, entry.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def list_entries(self, pipeline_name: str, run_id: str) -> list[AuditEntry]:
        path = self._path(pipeline_name, run_id)
        if not path.exists():
            return []
        entries: list[AuditEntry] = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entries.append(AuditEntry.model_validate(json.loads(line)))
        return entries


class PostgresAuditLog(PsycopgBackend):
    """Postgres-backed audit log. Single table created on first ``record`` call.

    Reuses ``psycopg`` from the ``postgres`` optional extra. ``dsn`` or a
    pre-built ``connection`` is required, mirroring :class:`PostgresCheckpointer`'s
    API for consistency.
    """

    _DDL = """
        CREATE TABLE IF NOT EXISTS {table} (
            pipeline_name    TEXT  NOT NULL,
            run_id           TEXT  NOT NULL,
            sequence         INT   NOT NULL,
            visit            INT   NOT NULL,
            node_id          TEXT  NOT NULL,
            started_at       TIMESTAMPTZ NOT NULL,
            completed_at     TIMESTAMPTZ NOT NULL,
            latency_ms       DOUBLE PRECISION NOT NULL,
            status           TEXT  NOT NULL,
            inputs_snapshot  JSONB NOT NULL,
            outputs_snapshot JSONB NOT NULL,
            error_message    TEXT,
            pause_reason     TEXT,
            PRIMARY KEY (pipeline_name, run_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS {table}_run_idx
            ON {table} (pipeline_name, run_id);
    """

    def __init__(
        self,
        *,
        dsn: str | None = None,
        connection: Any = None,
        table_name: str = "firefly_audit",
    ) -> None:
        super().__init__(kind="PostgresAuditLog", dsn=dsn, connection=connection, table_name=table_name)

    def record(self, entry: AuditEntry) -> None:
        self._ensure_table()
        sql = (
            f"INSERT INTO {self._table} "
            "(pipeline_name, run_id, sequence, visit, node_id, started_at, completed_at, "
            "latency_ms, status, inputs_snapshot, outputs_snapshot, error_message, pause_reason) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (pipeline_name, run_id, sequence) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    entry.pipeline_name,
                    entry.run_id,
                    entry.sequence,
                    entry.visit,
                    entry.node_id,
                    entry.started_at,
                    entry.completed_at,
                    entry.latency_ms,
                    entry.status,
                    json.dumps(entry.inputs_snapshot),
                    json.dumps(entry.outputs_snapshot),
                    entry.error_message,
                    entry.pause_reason,
                ),
            )

    def list_entries(self, pipeline_name: str, run_id: str) -> list[AuditEntry]:
        self._ensure_table()
        sql = (
            f"SELECT pipeline_name, run_id, sequence, visit, node_id, started_at, completed_at, "
            f"latency_ms, status, inputs_snapshot, outputs_snapshot, error_message, pause_reason "
            f"FROM {self._table} WHERE pipeline_name = %s AND run_id = %s ORDER BY sequence"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (pipeline_name, run_id))
            rows = cur.fetchall()
        entries: list[AuditEntry] = []
        for row in rows:
            entries.append(
                AuditEntry(
                    pipeline_name=row[0],
                    run_id=row[1],
                    sequence=row[2],
                    visit=row[3],
                    node_id=row[4],
                    started_at=row[5],
                    completed_at=row[6],
                    latency_ms=row[7],
                    status=row[8],
                    inputs_snapshot=json.loads(row[9]) if isinstance(row[9], str) else row[9],
                    outputs_snapshot=json.loads(row[10]) if isinstance(row[10], str) else row[10],
                    error_message=row[11],
                    pause_reason=row[12],
                )
            )
        return entries


class LoggingAuditLog:
    """Audit log backed by Python's stdlib ``logging`` module.

    Each entry is emitted as a structured log record with the full
    :class:`AuditEntry` available under ``record.firefly_audit``. Pairs
    naturally with any log-aggregation pipeline the host already configures:

    * OTel collector via ``opentelemetry-sdk._logs.LoggingHandler``
    * Splunk via the official Splunk handler
    * Loki via promtail tailing stdout
    * Datadog via ``ddtrace`` log injection
    * Plain JSON-logging via ``python-json-logger``

    No new dependency. The user wires their log handler exactly once for the
    whole application and audit entries flow there automatically.
    """

    def __init__(self, logger_name: str = "firefly.audit", level: int = logging.INFO) -> None:
        self._logger = logging.getLogger(logger_name)
        self._level = level

    def record(self, entry: AuditEntry) -> None:
        self._logger.log(
            self._level,
            "firefly_audit: pipeline=%s run=%s node=%s status=%s latency_ms=%.1f",
            entry.pipeline_name,
            entry.run_id,
            entry.node_id,
            entry.status,
            entry.latency_ms,
            extra={"firefly_audit": entry.model_dump(mode="json")},
        )


class OtelAuditLog:
    """Audit log backed by the OTel logs API.

    Emits each entry as a structured OTel log record with attributes
    matching :class:`AuditEntry` fields. When an OTel trace is active the
    record is automatically correlated with the current ``trace_id`` and
    ``span_id`` — useful for tying audit history to the spans Phase 3b
    emits.

    Requires ``opentelemetry-sdk`` to be installed and a ``LoggerProvider``
    configured by the host application (the framework does not install a
    provider).
    """

    def __init__(self, logger_name: str = "fireflyframework_agentic.audit") -> None:
        if _otel_get_logger is None:
            raise ImportError(
                "OtelAuditLog requires the 'opentelemetry-sdk' package "
                "(with the logs API). Install: pip install opentelemetry-sdk"
            )
        self._otel_logger = _otel_get_logger(logger_name)

    def record(self, entry: AuditEntry) -> None:
        # The constructor's guard on _otel_get_logger guarantees the OTel
        # logs imports succeeded, so the LogRecord and SeverityNumber are
        # not None here.
        assert _OtelLogRecord is not None and _OtelSeverityNumber is not None
        attrs: dict[str, Any] = {
            "firefly.pipeline": entry.pipeline_name,
            "firefly.run_id": entry.run_id,
            "firefly.node": entry.node_id,
            "firefly.sequence": entry.sequence,
            "firefly.visit": entry.visit,
            "firefly.latency_ms": entry.latency_ms,
            "firefly.status": entry.status,
        }
        if entry.error_message:
            attrs["firefly.error"] = entry.error_message
        if entry.pause_reason:
            attrs["firefly.pause_reason"] = entry.pause_reason

        body = f"[{entry.pipeline_name}] {entry.node_id} {entry.status} ({entry.latency_ms:.0f}ms)"
        severity = _OtelSeverityNumber.ERROR if entry.status == "error" else _OtelSeverityNumber.INFO
        log_record = _OtelLogRecord(
            timestamp=int(entry.completed_at.timestamp() * 1_000_000_000),
            severity_number=severity,
            severity_text=severity.name,
            body=body,
            attributes=attrs,
        )
        self._otel_logger.emit(log_record)
