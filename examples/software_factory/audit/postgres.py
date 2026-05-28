# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Plug-and-play Postgres audit log for fireflyframework-agentic.

This is **example code**, not framework code. Implements the framework's
:class:`QueryableAuditLog` Protocol (write + read-back) against a
caller-supplied ``psycopg.Connection``.

Distinct from the checkpointer — the checkpointer stores the latest state
for crash recovery; the audit log stores every node visit for compliance
and replay.
"""

from __future__ import annotations

import json
from typing import Any

from fireflyframework_agentic.pipeline import AuditEntry


class PostgresAuditLog:
    """Append-only audit log backed by a single ``firefly_audit`` table.

    Implements the :class:`fireflyframework_agentic.pipeline.QueryableAuditLog`
    Protocol — :meth:`record` writes one entry; :meth:`list_entries` reads
    every entry for a given run in sequence order.
    """

    def __init__(self, connection: Any) -> None:
        self._conn = connection
        with connection.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS firefly_audit (
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
                CREATE INDEX IF NOT EXISTS firefly_audit_run_idx
                    ON firefly_audit (pipeline_name, run_id);
                """
            )

    def record(self, entry: AuditEntry) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO firefly_audit "
                "(pipeline_name, run_id, sequence, visit, node_id, started_at, completed_at, "
                " latency_ms, status, inputs_snapshot, outputs_snapshot, error_message, pause_reason) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (pipeline_name, run_id, sequence) DO NOTHING",
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
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT pipeline_name, run_id, sequence, visit, node_id, started_at, "
                "       completed_at, latency_ms, status, inputs_snapshot, outputs_snapshot, "
                "       error_message, pause_reason "
                "FROM firefly_audit WHERE pipeline_name = %s AND run_id = %s "
                "ORDER BY sequence",
                (pipeline_name, run_id),
            )
            rows = cur.fetchall()
        return [
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
            for row in rows
        ]
