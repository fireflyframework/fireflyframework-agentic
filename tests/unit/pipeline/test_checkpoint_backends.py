# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for the three Checkpointer backends (File, Redis, Postgres).

Mocks only — no real Redis or Postgres needed. Real-service verification is
out-of-band against actual servers.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from pydantic import BaseModel

import fireflyframework_agentic.pipeline.checkpoint as checkpoint_module
from fireflyframework_agentic.pipeline import (
    CheckpointRecord,
    FileCheckpointer,
    PipelineBuilder,
    PostgresCheckpointer,
    RedisCheckpointer,
    StatePipeline,
)


@pytest.fixture(autouse=True)
def _stub_optional_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``_redis`` / ``_psycopg`` truthy so we can construct backends with mock clients.

    Tests that explicitly want the missing-dep code path (the two
    ``..._missing_dep_raises`` tests) override this by setting the symbol back
    to None via their own monkeypatch — the per-test patch wins.
    """
    if checkpoint_module._redis is None:
        monkeypatch.setattr(checkpoint_module, "_redis", MagicMock(name="redis_stub"))
    if checkpoint_module._psycopg is None:
        monkeypatch.setattr(checkpoint_module, "_psycopg", MagicMock(name="psycopg_stub"))


# =============================================================================
# RedisCheckpointer
# =============================================================================


def _redis_client_mock() -> MagicMock:
    """Build a MagicMock that tracks the calls a RedisCheckpointer issues, with
    just enough state (an in-memory dict) to make round-trip save→load work.
    """
    store: dict[str, str] = {}
    runs_index: dict[str, dict[str, float]] = {}

    client = MagicMock(name="redis.Redis")

    def fake_set(key: str, value: str, ex: int | None = None) -> bool:
        store[key] = value
        return True

    def fake_get(key: str) -> str | None:
        return store.get(key)

    def fake_keys(pattern: str) -> list[str]:
        # Trivial glob: only handles "<prefix>*" patterns (which is what we use).
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in store if k.startswith(prefix)]
        return [k for k in store if k == pattern]

    def fake_zadd(key: str, mapping: dict[str, float]) -> int:
        runs_index.setdefault(key, {}).update(mapping)
        return len(mapping)

    def fake_zrange(key: str, start: int, end: int) -> list[str]:
        members = runs_index.get(key, {})
        ordered = sorted(members, key=lambda m: members[m])
        return ordered[start : (end + 1 if end != -1 else None)]

    client.set.side_effect = fake_set
    client.get.side_effect = fake_get
    client.keys.side_effect = fake_keys
    client.zadd.side_effect = fake_zadd
    client.zrange.side_effect = fake_zrange
    return client


def test_redis_checkpointer_missing_dep_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkpoint_module, "_redis", None)
    with pytest.raises(ImportError, match=r"\[redis\]"):
        RedisCheckpointer(url="redis://x")


def test_redis_checkpointer_rejects_both_url_and_client() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        RedisCheckpointer(url="redis://x", client=MagicMock())


def test_redis_checkpointer_rejects_neither_url_nor_client() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        RedisCheckpointer()


def test_redis_save_issues_set_and_zadd() -> None:
    client = _redis_client_mock()
    ckpt = RedisCheckpointer(client=client, ttl_seconds=42)
    record = CheckpointRecord(
        pipeline_name="p",
        run_id="r",
        sequence=1,
        node_id="n",
        state={"x": 1},
        completed_nodes=["n"],
    )
    ckpt.save(record)

    set_call = client.set.call_args
    assert set_call.args[0] == "firefly:ckpt:p:r:000001_n"
    assert json.loads(set_call.args[1])["node_id"] == "n"
    assert set_call.kwargs["ex"] == 42

    zadd_call = client.zadd.call_args
    assert zadd_call.args[0] == "firefly:ckpt:p:runs"
    assert "r" in zadd_call.args[1]


def test_redis_load_latest_picks_highest_sequence_key() -> None:
    client = _redis_client_mock()
    ckpt = RedisCheckpointer(client=client)
    for seq in (1, 5, 3):
        ckpt.save(
            CheckpointRecord(
                pipeline_name="p",
                run_id="r",
                sequence=seq,
                node_id=f"node{seq}",
                state={"seq": seq},
                completed_nodes=[],
            )
        )
    latest = ckpt.load_latest("p", "r")
    assert latest is not None
    assert latest.sequence == 5
    assert latest.node_id == "node5"


def test_redis_load_latest_returns_none_when_run_unknown() -> None:
    client = _redis_client_mock()
    ckpt = RedisCheckpointer(client=client)
    assert ckpt.load_latest("p", "missing") is None


def test_redis_list_runs_returns_zrange_result() -> None:
    client = _redis_client_mock()
    ckpt = RedisCheckpointer(client=client)
    for run_id in ("r1", "r2", "r3"):
        ckpt.save(
            CheckpointRecord(
                pipeline_name="p",
                run_id=run_id,
                sequence=1,
                node_id="n",
                state={},
                completed_nodes=[],
            )
        )
    runs = ckpt.list_runs("p")
    assert set(runs) == {"r1", "r2", "r3"}


# =============================================================================
# PostgresCheckpointer
# =============================================================================


def _postgres_connection_mock() -> tuple[MagicMock, dict[tuple, dict[str, Any]]]:
    """MagicMock Connection backed by an in-memory dict shaped like the
    firefly_checkpoints table. Returns ``(conn, store)`` so tests can poke the store.
    """
    store: dict[tuple[str, str, int], dict[str, Any]] = {}
    ddl_calls: list[str] = []

    conn = MagicMock(name="psycopg.Connection")

    def make_cursor() -> MagicMock:
        cur = MagicMock(name="psycopg.Cursor")
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=None)
        cur._last_fetchone = None
        cur._last_fetchall = []

        def fake_execute(sql: str, params: tuple | None = None) -> None:
            sql_lower = sql.strip().lower()
            if sql_lower.startswith("create table"):
                ddl_calls.append(sql)
                return
            if sql_lower.startswith("insert into"):
                assert params is not None
                key = (params[0], params[1], params[2])
                store[key] = {
                    "pipeline_name": params[0],
                    "run_id": params[1],
                    "sequence": params[2],
                    "node_id": params[3],
                    "state": json.loads(params[4]) if isinstance(params[4], str) else params[4],
                    "completed_nodes": (json.loads(params[5]) if isinstance(params[5], str) else params[5]),
                }
                return
            if sql_lower.startswith("select pipeline_name"):
                assert params is not None
                matches = [v for k, v in store.items() if k[0] == params[0] and k[1] == params[1]]
                matches.sort(key=lambda r: r["sequence"], reverse=True)
                cur._last_fetchone = (
                    (
                        matches[0]["pipeline_name"],
                        matches[0]["run_id"],
                        matches[0]["sequence"],
                        matches[0]["node_id"],
                        matches[0]["state"],
                        matches[0]["completed_nodes"],
                    )
                    if matches
                    else None
                )
                return
            if sql_lower.startswith("select distinct run_id"):
                assert params is not None
                runs = sorted({k[1] for k in store if k[0] == params[0]})
                cur._last_fetchall = [(r,) for r in runs]
                return
            raise AssertionError(f"unexpected SQL: {sql}")

        cur.execute.side_effect = fake_execute
        cur.fetchone.side_effect = lambda: cur._last_fetchone
        cur.fetchall.side_effect = lambda: cur._last_fetchall
        return cur

    conn.cursor.side_effect = make_cursor
    conn._ddl_calls = ddl_calls
    return conn, store


def test_postgres_checkpointer_missing_dep_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkpoint_module, "_psycopg", None)
    with pytest.raises(ImportError, match=r"\[postgres\]"):
        PostgresCheckpointer(dsn="postgresql://x")


def test_postgres_checkpointer_rejects_both_dsn_and_connection() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        PostgresCheckpointer(dsn="postgresql://x", connection=MagicMock())


def test_postgres_checkpointer_rejects_bad_table_name() -> None:
    with pytest.raises(ValueError, match="Invalid table_name"):
        PostgresCheckpointer(connection=MagicMock(), table_name="bad; DROP TABLE users")


def test_postgres_ddl_runs_once_across_many_saves() -> None:
    conn, _store = _postgres_connection_mock()
    ckpt = PostgresCheckpointer(connection=conn)
    for seq in range(3):
        ckpt.save(
            CheckpointRecord(
                pipeline_name="p",
                run_id="r",
                sequence=seq,
                node_id=f"n{seq}",
                state={},
                completed_nodes=[],
            )
        )
    assert len(conn._ddl_calls) == 1, "DDL should run exactly once per instance"


def test_postgres_save_then_load_latest_round_trips() -> None:
    conn, _store = _postgres_connection_mock()
    ckpt = PostgresCheckpointer(connection=conn)
    for seq, node_id in [(1, "a"), (5, "e"), (3, "c")]:
        ckpt.save(
            CheckpointRecord(
                pipeline_name="p",
                run_id="r",
                sequence=seq,
                node_id=node_id,
                state={"seq": seq},
                completed_nodes=[node_id],
            )
        )
    latest = ckpt.load_latest("p", "r")
    assert latest is not None
    assert latest.sequence == 5
    assert latest.node_id == "e"


def test_postgres_load_latest_returns_none_when_empty() -> None:
    conn, _store = _postgres_connection_mock()
    ckpt = PostgresCheckpointer(connection=conn)
    assert ckpt.load_latest("p", "missing") is None


def test_postgres_list_runs_returns_distinct_run_ids() -> None:
    conn, _store = _postgres_connection_mock()
    ckpt = PostgresCheckpointer(connection=conn)
    for run_id in ("rA", "rB", "rA"):  # rA twice, rB once
        ckpt.save(
            CheckpointRecord(
                pipeline_name="p",
                run_id=run_id,
                sequence=1,
                node_id="n",
                state={},
                completed_nodes=[],
            )
        )
    assert ckpt.list_runs("p") == ["rA", "rB"]


# =============================================================================
# Protocol conformance — software-factory scenario across all three backends
# =============================================================================


class FactoryState(BaseModel):
    requirements: str
    spec: str | None = None
    code: str | None = None
    deploy_url: str | None = None
    evaluation: str | None = None


def _build_factory(checkpointer: Any) -> StatePipeline:
    """Construct the canonical 4-step agent pipeline that fails on first deploy."""
    state_flag = {"failed_once": False}

    async def architect(state: FactoryState) -> dict:
        return {"spec": f"spec for {state.requirements}"}

    async def python_dev(state: FactoryState) -> dict:
        return {"code": f"# code for {state.spec}"}

    async def deployer(state: FactoryState) -> dict:
        if not state_flag["failed_once"]:
            state_flag["failed_once"] = True
            raise RuntimeError("blip")
        return {"deploy_url": "https://app"}

    async def evaluator(state: FactoryState) -> dict:
        return {"evaluation": f"PASS {state.deploy_url}"}

    pipeline = (
        PipelineBuilder("factory", state=FactoryState, checkpointer=checkpointer)
        .add_node(architect)
        .add_node(python_dev)
        .add_node(deployer)
        .add_node(evaluator)
        .chain(architect, python_dev, deployer, evaluator)
        .build()
    )
    assert isinstance(pipeline, StatePipeline)
    return pipeline


@pytest.fixture
def file_backend(tmp_path):
    return FileCheckpointer(tmp_path / "ckpt")


@pytest.fixture
def redis_backend():
    return RedisCheckpointer(client=_redis_client_mock())


@pytest.fixture
def postgres_backend():
    conn, _store = _postgres_connection_mock()
    return PostgresCheckpointer(connection=conn)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_fixture", ["file_backend", "redis_backend", "postgres_backend"])
async def test_backend_supports_fail_and_resume(backend_fixture, request) -> None:
    """Same scenario across all three backends: deployer fails, resume completes."""
    backend = request.getfixturevalue(backend_fixture)
    pipeline = _build_factory(backend)

    first = await pipeline.invoke(FactoryState(requirements="users service"))
    assert not first.success
    assert first.failed_node == "deployer"
    assert first.completed_nodes == ["architect", "python_dev"]

    second = await pipeline.invoke(run_id=first.run_id)
    assert second.success
    assert second.completed_nodes == ["architect", "python_dev", "deployer", "evaluator"]
    assert second.state.evaluation == "PASS https://app"


# Silence the unused-import warning for the autospec we don't actually use here
# but keep available for follow-up tests.
_ = create_autospec
