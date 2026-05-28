# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Plug-and-play Postgres :class:`Checkpointer` for fireflyframework-agentic.

This is **example code**, not framework code. Copy this file into your
project and adapt as needed:

* Pass your own ``psycopg.Connection``. This template does not own the pool.
* Adapt the table name if ``firefly_checkpoints`` clashes with anything.
* Add retry / instrumentation in a wrapper if your stack needs it — the
  framework engine already catches and logs checkpoint failures, so the
  pipeline keeps running on transient errors regardless.
"""

from __future__ import annotations

import json
from typing import Any

from fireflyframework_agentic.pipeline import CheckpointRecord


class PostgresCheckpointer:
    """Stores checkpoints in a single ``firefly_checkpoints`` table.

    Implements the :class:`fireflyframework_agentic.pipeline.Checkpointer`
    Protocol — three sync methods over a caller-supplied connection.
    """

    def __init__(self, connection: Any) -> None:
        self._conn = connection
        with connection.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS firefly_checkpoints (
                    pipeline_name   TEXT  NOT NULL,
                    run_id          TEXT  NOT NULL,
                    sequence        INT   NOT NULL,
                    node_id         TEXT  NOT NULL,
                    state           JSONB NOT NULL,
                    completed_nodes JSONB NOT NULL,
                    paused          BOOLEAN NOT NULL DEFAULT FALSE,
                    pause_reason    TEXT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (pipeline_name, run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS firefly_checkpoints_run_idx
                    ON firefly_checkpoints (pipeline_name, run_id);
                """
            )

    def save(self, record: CheckpointRecord) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO firefly_checkpoints "
                "(pipeline_name, run_id, sequence, node_id, state, completed_nodes, paused, pause_reason) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (pipeline_name, run_id, sequence) DO UPDATE SET "
                "node_id=EXCLUDED.node_id, state=EXCLUDED.state, "
                "completed_nodes=EXCLUDED.completed_nodes, "
                "paused=EXCLUDED.paused, pause_reason=EXCLUDED.pause_reason",
                (
                    record.pipeline_name,
                    record.run_id,
                    record.sequence,
                    record.node_id,
                    json.dumps(record.state),
                    json.dumps(record.completed_nodes),
                    record.paused,
                    record.pause_reason,
                ),
            )

    def load_latest(self, pipeline_name: str, run_id: str) -> CheckpointRecord | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT pipeline_name, run_id, sequence, node_id, state, completed_nodes, "
                "       paused, pause_reason "
                "FROM firefly_checkpoints "
                "WHERE pipeline_name = %s AND run_id = %s "
                "ORDER BY sequence DESC LIMIT 1",
                (pipeline_name, run_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return CheckpointRecord(
            pipeline_name=row[0],
            run_id=row[1],
            sequence=row[2],
            node_id=row[3],
            state=json.loads(row[4]) if isinstance(row[4], str) else row[4],
            completed_nodes=json.loads(row[5]) if isinstance(row[5], str) else row[5],
            paused=row[6],
            pause_reason=row[7],
        )

    def list_runs(self, pipeline_name: str) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT run_id FROM firefly_checkpoints WHERE pipeline_name = %s ORDER BY run_id",
                (pipeline_name,),
            )
            return [r[0] for r in cur.fetchall()]
