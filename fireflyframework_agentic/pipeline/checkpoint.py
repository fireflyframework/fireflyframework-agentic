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

"""Pipeline state checkpointing for failure recovery and resumable runs.

A :class:`Checkpointer` persists state after each successful node, keyed by
``(pipeline_name, run_id, node_id)``. On resume the engine loads the latest
checkpoint and skips nodes that already completed in that run.

Three backends ship:

* :class:`FileCheckpointer` — filesystem JSON. Best for dev / single-host.
* :class:`RedisCheckpointer` — Redis with TTL. Best for multi-worker,
  sub-day-scale runs. Requires ``pip install fireflyframework-agentic[redis]``.
* :class:`PostgresCheckpointer` — Postgres with a single ``firefly_checkpoints``
  table. Best for long-lived runs / compliance. Requires
  ``pip install fireflyframework-agentic[postgres]``.

Any backend conforms to the :class:`Checkpointer` Protocol and is interchangeable.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

try:
    import redis as _redis  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    _redis = None  # type: ignore[assignment]

try:
    import psycopg as _psycopg  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    _psycopg = None  # type: ignore[assignment]


class CheckpointRecord(BaseModel):
    """One saved checkpoint."""

    pipeline_name: str
    run_id: str
    node_id: str
    sequence: int
    state: dict[str, Any]
    completed_nodes: list[str]


@runtime_checkable
class Checkpointer(Protocol):
    """Persists pipeline state after each successful node.

    Implementations must be safe to call from async code (the engine awaits
    save() inside its task loop) but the methods themselves may be sync.
    """

    def save(self, record: CheckpointRecord) -> None:
        """Persist a checkpoint. Overwrites if (pipeline, run_id, node_id) exists."""
        ...

    def load_latest(self, pipeline_name: str, run_id: str) -> CheckpointRecord | None:
        """Return the most recent checkpoint for ``run_id`` or ``None`` if no run exists."""
        ...

    def list_runs(self, pipeline_name: str) -> list[str]:
        """Return all known run IDs for ``pipeline_name``."""
        ...


class FileCheckpointer:
    """Filesystem-backed checkpointer. Layout::

        <root>/<pipeline_name>/<run_id>/<sequence>_<node_id>.json

    The ``sequence`` prefix gives a natural sort order for ``load_latest``.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, record: CheckpointRecord) -> None:
        run_dir = self._root / record.pipeline_name / record.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{record.sequence:06d}_{record.node_id}.json"
        path.write_text(record.model_dump_json(indent=2))

    def load_latest(self, pipeline_name: str, run_id: str) -> CheckpointRecord | None:
        run_dir = self._root / pipeline_name / run_id
        if not run_dir.exists():
            return None
        files = sorted(run_dir.glob("*.json"))
        if not files:
            return None
        latest = files[-1]
        return CheckpointRecord.model_validate(json.loads(latest.read_text()))

    def list_runs(self, pipeline_name: str) -> list[str]:
        pipeline_dir = self._root / pipeline_name
        if not pipeline_dir.exists():
            return []
        return sorted(d.name for d in pipeline_dir.iterdir() if d.is_dir())


class RedisCheckpointer:
    """Redis-backed checkpointer.

    Key layout::

        firefly:ckpt:<pipeline>:<run_id>:<seq:06d>_<node_id>   -> JSON record (with TTL)
        firefly:ckpt:<pipeline>:runs                          -> ZSET of run_ids (score = last update ts)

    Parameters:
        url: Redis connection string (e.g. ``redis://host:6379/0``). Mutually
            exclusive with ``client``.
        client: Pre-built ``redis.Redis`` instance. Use this to share a
            connection pool across many pipelines.
        ttl_seconds: TTL applied to each checkpoint key. Default 30 days.
            The runs-index ZSET does not expire (it's tiny).
        key_prefix: Override the default ``firefly:ckpt`` key prefix.

    Raises:
        ImportError: When the ``redis`` extra is not installed.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        client: Any = None,
        ttl_seconds: int = 60 * 60 * 24 * 30,
        key_prefix: str = "firefly:ckpt",
    ) -> None:
        if _redis is None:
            raise ImportError(
                "RedisCheckpointer requires the 'redis' extra. "
                "Install with: pip install fireflyframework-agentic[redis]"
            )
        if (url is None) == (client is None):
            raise ValueError("RedisCheckpointer needs exactly one of `url` or `client`.")
        self._client = client if client is not None else _redis.Redis.from_url(url, decode_responses=True)
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    def _ckpt_key(self, pipeline: str, run_id: str, sequence: int, node_id: str) -> str:
        return f"{self._prefix}:{pipeline}:{run_id}:{sequence:06d}_{node_id}"

    def _runs_index_key(self, pipeline: str) -> str:
        return f"{self._prefix}:{pipeline}:runs"

    def _run_pattern(self, pipeline: str, run_id: str) -> str:
        return f"{self._prefix}:{pipeline}:{run_id}:*"

    def save(self, record: CheckpointRecord) -> None:
        key = self._ckpt_key(record.pipeline_name, record.run_id, record.sequence, record.node_id)
        self._client.set(key, record.model_dump_json(), ex=self._ttl)
        self._client.zadd(self._runs_index_key(record.pipeline_name), {record.run_id: time.time()})

    def load_latest(self, pipeline_name: str, run_id: str) -> CheckpointRecord | None:
        keys = self._client.keys(self._run_pattern(pipeline_name, run_id))
        if not keys:
            return None
        # Keys are zero-padded by sequence; lex-sorted last = numerically-latest.
        latest_key = sorted(keys)[-1]
        payload = self._client.get(latest_key)
        if payload is None:
            return None
        return CheckpointRecord.model_validate(json.loads(payload))

    def list_runs(self, pipeline_name: str) -> list[str]:
        return list(self._client.zrange(self._runs_index_key(pipeline_name), 0, -1))


class PostgresCheckpointer:
    """Postgres-backed checkpointer.

    Uses a single table created on first ``save`` call. The DDL is idempotent
    so multiple processes pointing at the same database are safe.

    Parameters:
        dsn: Postgres connection string. Mutually exclusive with ``connection``.
        connection: Pre-built ``psycopg.Connection``. Use this to share a
            connection across many pipelines.
        table_name: Override the default ``firefly_checkpoints`` table name.

    Raises:
        ImportError: When the ``postgres`` extra is not installed.
    """

    _DDL = """
        CREATE TABLE IF NOT EXISTS {table} (
            pipeline_name   TEXT  NOT NULL,
            run_id          TEXT  NOT NULL,
            sequence        INT   NOT NULL,
            node_id         TEXT  NOT NULL,
            state           JSONB NOT NULL,
            completed_nodes JSONB NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
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
        table_name: str = "firefly_checkpoints",
    ) -> None:
        if _psycopg is None:
            raise ImportError(
                "PostgresCheckpointer requires the 'postgres' extra. "
                "Install with: pip install fireflyframework-agentic[postgres]"
            )
        if (dsn is None) == (connection is None):
            raise ValueError("PostgresCheckpointer needs exactly one of `dsn` or `connection`.")
        # Table name is interpolated into DDL — validate it strictly to avoid SQL injection.
        if not table_name.replace("_", "").isalnum():
            raise ValueError(f"Invalid table_name {table_name!r}: must be alphanumeric/underscore only.")
        self._conn = connection if connection is not None else _psycopg.connect(dsn, autocommit=True)
        self._table = table_name
        self._ddl_applied = False

    def _ensure_table(self) -> None:
        if self._ddl_applied:
            return
        with self._conn.cursor() as cur:
            cur.execute(self._DDL.format(table=self._table))
        self._ddl_applied = True

    def save(self, record: CheckpointRecord) -> None:
        self._ensure_table()
        sql = (
            f"INSERT INTO {self._table} "
            "(pipeline_name, run_id, sequence, node_id, state, completed_nodes) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (pipeline_name, run_id, sequence) DO UPDATE SET "
            "node_id = EXCLUDED.node_id, "
            "state = EXCLUDED.state, "
            "completed_nodes = EXCLUDED.completed_nodes"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    record.pipeline_name,
                    record.run_id,
                    record.sequence,
                    record.node_id,
                    json.dumps(record.state),
                    json.dumps(record.completed_nodes),
                ),
            )

    def load_latest(self, pipeline_name: str, run_id: str) -> CheckpointRecord | None:
        self._ensure_table()
        sql = (
            f"SELECT pipeline_name, run_id, sequence, node_id, state, completed_nodes "
            f"FROM {self._table} "
            f"WHERE pipeline_name = %s AND run_id = %s "
            f"ORDER BY sequence DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (pipeline_name, run_id))
            row = cur.fetchone()
        if row is None:
            return None
        pipeline, rid, seq, node_id, state, completed = row
        # psycopg returns JSONB as parsed Python objects; tolerate raw strings too.
        return CheckpointRecord(
            pipeline_name=pipeline,
            run_id=rid,
            sequence=seq,
            node_id=node_id,
            state=json.loads(state) if isinstance(state, str) else state,
            completed_nodes=json.loads(completed) if isinstance(completed, str) else completed,
        )

    def list_runs(self, pipeline_name: str) -> list[str]:
        self._ensure_table()
        sql = f"SELECT DISTINCT run_id FROM {self._table} WHERE pipeline_name = %s ORDER BY run_id"
        with self._conn.cursor() as cur:
            cur.execute(sql, (pipeline_name,))
            return [r[0] for r in cur.fetchall()]
