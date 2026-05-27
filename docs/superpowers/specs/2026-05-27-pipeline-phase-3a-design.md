# Phase 3a — Durable Checkpointer Backends (Redis + Postgres)

Issue [#147](https://github.com/fireflyframework/fireflyframework-agentic/issues/147), phase 3a. Stacked on top of Phase 1+2 (`issue-147-pipeline-evolution`).

## Problem

`StatePipeline` checkpointing today has one backend: `FileCheckpointer`, which writes JSON files to a local filesystem. That blocks the use cases customers actually run agentic pipelines for:

- **Multi-worker fail-over.** A pipeline that crashes on worker A cannot be resumed on worker B because the checkpoint files are on A's disk.
- **Containerized deploys.** Ephemeral container filesystems lose checkpoint state on restart.
- **Horizontal scaling.** No shared state means runs are pinned to a single host.
- **Long-lived runs.** Filesystem checkpoints accumulate without TTL; cleanup is manual.

Phase 3a ships two durable backends — Redis and Postgres — pluggable through the existing `Checkpointer` Protocol. No API changes to `StatePipeline`; no breaking changes for existing `FileCheckpointer` users.

## Goal

`PipelineBuilder("agent", state=..., checkpointer=...)` accepts a `RedisCheckpointer` or `PostgresCheckpointer` interchangeably with the existing `FileCheckpointer`. The software-factory scenario (architect → python_dev → deployer fails → resume on a different worker → evaluator) works end-to-end against any of the three.

## Non-goals

- Backend-pluggable observability / OTel spans (phase 3b).
- HITL pause primitive and audit log (phase 3c).
- Real-Redis / real-Postgres tests in this PR — verified out-of-band by the user.
- Schema migration tooling for the JSONB `state` column — the application owns state-schema evolution.
- Connection-pool tuning knobs beyond "pass me a client."
- Auth / RBAC on resume APIs.
- Streaming partial state.

## Architecture

Single file: `fireflyframework_agentic/pipeline/checkpoint.py`. Existing contents (`Checkpointer` Protocol, `CheckpointRecord`, `FileCheckpointer`) are preserved. Two new classes added to the same module:

```
pipeline/checkpoint.py
├── Checkpointer (Protocol, existing)
├── CheckpointRecord (existing)
├── FileCheckpointer (existing)
├── RedisCheckpointer (new)
└── PostgresCheckpointer (new)
```

### Guarded optional imports

Top-of-file guarded imports mirror the established pattern in `engine.py` for OTel:

```python
try:
    import redis as _redis
except ImportError:
    _redis = None

try:
    import psycopg as _psycopg
except ImportError:
    _psycopg = None
```

Each backend's `__init__` raises a clear install-instruction error if its dependency is absent. No inline imports — project rule respected.

### Connection lifecycle

Both backends accept either a connection string OR a pre-built sync client so callers can share a connection pool across many pipelines:

```python
RedisCheckpointer(url="redis://localhost:6379/0", ttl_seconds=86400 * 30)
RedisCheckpointer(client=existing_redis_client)

PostgresCheckpointer(dsn="postgresql://user:pw@host/db")
PostgresCheckpointer(connection=existing_psycopg_connection)
```

The `Checkpointer` Protocol's methods are sync (called synchronously inside `StatePipeline._save_checkpoint`). Both backends use the sync clients (`redis-py`, `psycopg[binary]`) directly — no `asyncio.run` indirection.

## Storage schemas

### Redis

One key per checkpoint, plus a sorted-set index per pipeline for `list_runs`:

| Key | Type | Value |
|---|---|---|
| `firefly:ckpt:{pipeline}:{run_id}:{seq:06d}_{node_id}` | string | JSON-serialized `CheckpointRecord` |
| `firefly:ckpt:{pipeline}:runs` | sorted set | members = `run_id`s, scores = last-update unix timestamps |

- TTL on the per-checkpoint keys is configurable, default 30 days.
- `save` issues `SET key value EX ttl` then `ZADD index ts run_id` (idempotent — score updated each call).
- `load_latest` issues `KEYS firefly:ckpt:{pipeline}:{run_id}:*`, picks the lexicographically last key (the zero-padded `seq` makes lex order match numeric order), then `GET` it.
- `list_runs` issues `ZRANGE index 0 -1` and returns all run IDs ordered by last-update.

`KEYS` is acceptable here because the cardinality per run is bounded by node count × visit count (small for agentic workflows). A `SCAN`-based variant is trivial to add if scale demands it; not in scope for 3a.

### Postgres

Single table, created idempotently on first connect:

```sql
CREATE TABLE IF NOT EXISTS firefly_checkpoints (
  pipeline_name   TEXT  NOT NULL,
  run_id          TEXT  NOT NULL,
  sequence        INT   NOT NULL,
  node_id         TEXT  NOT NULL,
  state           JSONB NOT NULL,
  completed_nodes JSONB NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (pipeline_name, run_id, sequence)
);
CREATE INDEX IF NOT EXISTS firefly_checkpoints_run
  ON firefly_checkpoints (pipeline_name, run_id);
```

- DDL runs once per `PostgresCheckpointer` instance via a `_ddl_applied` flag set on first `save`.
- `save` issues `INSERT … ON CONFLICT (pipeline_name, run_id, sequence) DO UPDATE SET node_id = EXCLUDED.node_id, state = EXCLUDED.state, completed_nodes = EXCLUDED.completed_nodes`.
- `load_latest` issues `SELECT pipeline_name, run_id, sequence, node_id, state, completed_nodes FROM firefly_checkpoints WHERE pipeline_name = %s AND run_id = %s ORDER BY sequence DESC LIMIT 1`.
- `list_runs` issues `SELECT DISTINCT run_id FROM firefly_checkpoints WHERE pipeline_name = %s ORDER BY run_id`.

## Optional dependencies

`pyproject.toml` gains two new extras, no new required dependencies and no new dev-dependencies:

```toml
[project.optional-dependencies]
redis    = ["redis>=5,<6"]
postgres = ["psycopg[binary]>=3,<4"]
```

Install paths:

```bash
pip install fireflyframework-agentic[redis]
pip install fireflyframework-agentic[postgres]
pip install fireflyframework-agentic[redis,postgres]
```

## Testing strategy

`unittest.mock` only. No `fakeredis`, no `pytest-postgresql`, no test containers. Real-service verification is out-of-band by the user against real Redis and real Postgres, not in this PR.

### `RedisCheckpointer` tests

Mock the `redis.Redis` client (`mock.create_autospec(redis.Redis)`). Assertions:

- `save` issues `client.set(key=..., value=<json>, ex=<ttl>)` with the expected key format and TTL.
- `save` issues `client.zadd("firefly:ckpt:<pipeline>:runs", {<run_id>: <unix_ts>})`.
- `load_latest` issues `client.keys("firefly:ckpt:<pipeline>:<run_id>:*")`, picks the lex-last key, then `client.get(<key>)`, returns the parsed `CheckpointRecord`.
- `load_latest` returns `None` when `keys` returns an empty list.
- `list_runs` issues `client.zrange("firefly:ckpt:<pipeline>:runs", 0, -1)` and returns its result.
- Constructing `RedisCheckpointer(url=...)` when `_redis is None` raises `ImportError` with a message that names the extra (`pip install fireflyframework-agentic[redis]`).

### `PostgresCheckpointer` tests

Mock the `psycopg.Connection` and its `cursor()` context manager. Assertions:

- First `save` issues the `CREATE TABLE IF NOT EXISTS` DDL exactly once. The DDL flag prevents subsequent `save` calls from re-issuing it.
- `save` issues `INSERT … ON CONFLICT (pipeline_name, run_id, sequence) DO UPDATE SET …` with bound parameters matching the `CheckpointRecord` fields.
- `load_latest` issues `SELECT … ORDER BY sequence DESC LIMIT 1` and returns the row hydrated into a `CheckpointRecord`. Returns `None` for the no-rows case.
- `list_runs` issues `SELECT DISTINCT run_id … ORDER BY run_id` and returns the list.
- Constructing `PostgresCheckpointer(dsn=...)` when `_psycopg is None` raises `ImportError` naming the extra.

### Protocol-conformance test

A single test module `tests/unit/pipeline/test_checkpoint_backends.py` parametrizes the existing software-factory scenario (architect → python_dev → deployer fails → resume → evaluator) across all three backends:

- `FileCheckpointer` — real, uses `tmp_path`.
- `RedisCheckpointer` — wrapping a `MagicMock` Redis client that records `set`/`get`/`keys`/`zadd`/`zrange` calls in-memory.
- `PostgresCheckpointer` — wrapping a `MagicMock` connection whose cursor returns canned results from an in-memory dict mimicking the schema.

The mocks keep enough state to make the full resume flow work (save then load returns what was saved). Protocol drift between backends is caught as a test failure.

## Documentation

`docs/pipeline.md` — "Checkpoint + Resume" subsection gains a backend-comparison table:

| Backend | Use when | Trade-off |
|---|---|---|
| `FileCheckpointer` | Dev, single-host, ephemeral | No cross-process / cross-host sharing |
| `RedisCheckpointer` | Multi-worker, sub-day-scale runs | TTL eviction; not durable forever |
| `PostgresCheckpointer` | Long-lived runs, compliance, audit-friendly | Operational overhead of a DB |

`examples/pipeline_state.py` — append a fourth scenario gated behind `if os.environ.get("PG_DSN"):` showing how to swap `FileCheckpointer` for `PostgresCheckpointer`. No-op when the env var is unset, so the example still runs anywhere.

`fireflyframework_agentic/pipeline/__init__.py` — re-export `RedisCheckpointer` and `PostgresCheckpointer` via a plain `from … import …`. Both classes always exist as importable names; the optional-dep gate is in their `__init__` methods. Rationale: simpler than `__getattr__` indirection on the package, and the canonical pattern in this codebase for OTel and other soft dependencies.

## Scope

- `pipeline/checkpoint.py`: ~250 LOC added
- `pyproject.toml`: two new `[project.optional-dependencies]` entries; **no new required deps, no new dev deps**
- `tests/unit/pipeline/test_checkpoint_backends.py`: ~180 LOC
- `docs/pipeline.md`: +20 LOC (table + a paragraph)
- `examples/pipeline_state.py`: +30 LOC (optional fourth scenario)
- `pipeline/__init__.py`: +2 exports

Total ~450 LOC + tests, independently shippable.

## Verification

After implementation:

1. `pytest tests/unit/pipeline/ -v` — pipeline suite green, all three backends pass the parametrized conformance test.
2. `pytest tests/unit/` — full unit suite green.
3. `ruff check` + `ruff format --check` clean.
4. `pyright` clean on touched modules.
5. `python -c "from fireflyframework_agentic.pipeline import RedisCheckpointer, PostgresCheckpointer"` works in a fresh venv with neither extra installed (the imports succeed; constructing the classes is what raises).
6. `python -c "from fireflyframework_agentic.pipeline import RedisCheckpointer; RedisCheckpointer(url='redis://x')"` in the no-extras venv raises a clear `ImportError` naming the extra.

## What lands next

- **Phase 3b** — `StatePipelineEventHandler` Protocol + OTel spans per state-pipeline node.
- **Phase 3c** — `Pause(reason)` sentinel for HITL approval gates + `AuditLog` Protocol with Postgres impl reusing the 3a Postgres connection.
