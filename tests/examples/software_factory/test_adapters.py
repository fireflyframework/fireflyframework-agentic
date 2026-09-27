# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Adapter contracts at external Redis/DB boundaries; no external service writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from examples.software_factory.audit.postgres import PostgresAuditLog
from examples.software_factory.checkpointers.postgres import PostgresCheckpointer
from examples.software_factory.checkpointers.redis import RedisCheckpointer
from fireflyframework_agentic.pipeline import AuditEntry, CheckpointRecord


def _record(sequence: int = 1) -> CheckpointRecord:
    return CheckpointRecord(
        pipeline_name="factory",
        run_id="run-1",
        sequence=sequence,
        node_id="builder",
        state={"request": "A customer's order", "iteration": 2},
        completed_nodes=["architect", "codegen"],
    )


def test_redis_latest_uses_numeric_sequences_beyond_six_digits() -> None:
    records = [_record(999999), _record(1000000)]
    values = {f"firefly:ckpt:factory:run-1:{r.sequence:06d}_builder".encode(): r.model_dump_json() for r in records}
    client = SimpleNamespace(keys=lambda _: list(values), scan_iter=lambda **_: iter(values), get=values.get)
    assert RedisCheckpointer(client).load_latest("factory", "run-1").sequence == 1000000


def test_redis_run_index_decodes_bytes_and_prunes_expired_checkpoints() -> None:
    record = _record()
    values = {b"firefly:ckpt:factory:run-1:000001_builder": record.model_dump_json().encode()}
    removed = []
    client = SimpleNamespace(
        zrange=lambda *_: [b"run-1", b"expired"],
        scan_iter=lambda match: iter(values if ":run-1:" in match else []),
        get=values.get,
        zrem=lambda key, member: removed.append((key, member)),
    )
    assert RedisCheckpointer(client).list_runs("factory") == ["run-1"]
    assert removed == [("firefly:ckpt:factory:runs", b"expired")]


@pytest.mark.parametrize("ttl", [0, -1])
def test_redis_rejects_invalid_expiry(ttl: int) -> None:
    with pytest.raises(ValueError, match="ttl"):
        RedisCheckpointer(SimpleNamespace(), ttl_seconds=ttl)


def test_postgres_checkpoint_write_read_and_missing_record() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    adapter = PostgresCheckpointer(connection)
    record = _record()
    adapter.save(record)
    sql, parameters = cursor.execute.call_args.args
    assert "ON CONFLICT" in sql
    assert "A customer's order" not in sql
    assert json.loads(parameters[4]) == record.state
    assert json.loads(parameters[5]) == ["architect", "codegen"]
    cursor.fetchone.return_value = parameters
    assert adapter.load_latest("factory", "run-1") == record
    cursor.fetchone.return_value = None
    assert adapter.load_latest("factory", "missing") is None
    cursor.fetchall.return_value = [("run-1",), ("run-2",)]
    assert adapter.list_runs("factory") == ["run-1", "run-2"]


def test_postgres_audit_preserves_complete_visit_details() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    adapter = PostgresAuditLog(connection)
    stamp = datetime(2026, 9, 26, tzinfo=UTC)
    entry = AuditEntry(
        pipeline_name="factory",
        run_id="run-1",
        node_id="builder",
        sequence=4,
        visit=2,
        started_at=stamp,
        completed_at=stamp,
        latency_ms=12.5,
        status="error",
        inputs_snapshot={"iteration": 2},
        outputs_snapshot={},
        error_message="Read-only volume",
        pause_reason=None,
    )
    adapter.record(entry)
    sql, parameters = cursor.execute.call_args.args
    assert "ON CONFLICT" in sql
    assert parameters[11] == "Read-only volume"
    assert json.loads(parameters[9]) == {"iteration": 2}
    cursor.fetchall.return_value = [parameters]
    assert adapter.list_entries("factory", "run-1") == [entry]
    # psycopg returns JSONB as decoded Python values by default.
    decoded = list(parameters)
    decoded[9:11] = [{"iteration": 2}, {}]
    cursor.fetchall.return_value = [decoded]
    assert adapter.list_entries("factory", "run-1") == [entry]
