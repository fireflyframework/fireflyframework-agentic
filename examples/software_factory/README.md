# `software_factory/` — a state-based agentic SDLC pipeline

A small, self-contained example that shows the headline features of
`PipelineBuilder` in state mode:

- **State + reducers** — one Pydantic model carries everything the agents read or write; `extend` accumulates QA feedback across loop iterations.
- **Branching** — one `.branch("qa", qa_router)` call gives both the success terminus and the QA cycle.
- **Cycle with `recursion_limit`** — the QA fail → codegen loop is something port-based DAGs cannot express.
- **Checkpoint + resume** — `builder` raises a simulated transient error on its first call; `invoke(run_id=...)` resumes from the checkpoint.
- **Observability handler** — a `StatePipelineEventHandler` prints per-node progress.

No LLM calls. All agents are deterministic stubs so the example runs offline and the smoke test is stable.

## Run it

```bash
source ~/.venvs/firefly/bin/activate
python -m examples.software_factory
```

Expected output:

```
▶ [software-factory] run abc123ef… starting
  ▶ architect (visit #1)
    ✔ architect (0ms)
  ▶ codegen (visit #1)
    ✔ codegen (0ms)
  ▶ builder (visit #1)
    ✗ builder: dep install timed out
═ [software-factory] FAILED in 1ms

first run:  success=False  failed_node=builder  run_id=abc123ef…

▶ [software-factory] run abc123ef… starting
  ▶ builder (visit #1)
    ✔ builder (0ms)
  ▶ qa (visit #1)
    ✔ qa (0ms)
  ▶ codegen (visit #2)
    ✔ codegen (0ms)
  ▶ builder (visit #2)
    ✔ builder (0ms)
  ▶ qa (visit #2)
    ✔ qa (0ms)
  ▶ stable_release (visit #1)
    ✔ stable_release (0ms)
═ [software-factory] OK in 2ms

resumed:    success=True  release=v2026.05.28  iteration=2
qa_feedback: ['missing PSD2 strong-auth flow']
```

## The DAG

```
              ┌─────────── qa_status == 'fail' → codegen (recursion_limit=3) ─────────┐
              │                                                                       │
              ▼                                                                       │
architect → codegen → builder → qa ──(qa_router)──▶ stable_release                    │
                                  │                                                   │
                                  └───────────────────────────────────────────────────┘
```

| Node | What it does |
|---|---|
| `architect` | Writes a stub ADR string into `state.adr`. |
| `codegen` | Bumps `state.iteration`, writes `state.code = "v{iteration} (addresses: ...)"`. Iteration 2+ visibly incorporates `qa_feedback`. |
| `builder` | **Transient failure** on the first call across the process (`raise RuntimeError("dep install timed out")`). Succeeds on every subsequent call. |
| `qa` | **Substantive failure** on iteration 1 (`qa_status="fail"`, appends to `qa_feedback`). Passes on iteration 2. |
| `stable_release` | Sets `release_tag`. Terminal. |

### Why are `codegen` and `builder` separate nodes?

In stub form they look redundant. They're kept distinct because they model **two different failure-recovery patterns** the state-mode API supports:

| Failure mode | Meaning | How the pipeline recovers |
|---|---|---|
| `builder` raises | Transient (network blip, dep flake) — same code, just retry | The engine catches the exception, checkpoints the failure, returns `success=False`. `invoke(run_id=...)` resumes by re-running `builder` in place. **No cycle.** |
| `qa` returns `"fail"` | Substantive (tests don't pass) — the code itself needs to change | `qa_router` returns `"codegen"`; the cycle re-enters `codegen` which writes v2 informed by `qa_feedback`. |

One pipeline, two recovery patterns. Collapsing the nodes loses one of them.

## Swapping the checkpointer

The example defaults to `FileCheckpointer`. To run against a real Redis or Postgres:

```bash
FIREFLY_CKPT=postgres PG_DSN="postgresql://localhost:5432/firefly" python -m examples.software_factory
FIREFLY_CKPT=redis    REDIS_URL="redis://localhost:6379/0"       python -m examples.software_factory
```

The Postgres and Redis backends live in this folder as **plug-and-play templates**, not framework code:

- `checkpointers/postgres.py` — implements the framework's `Checkpointer` Protocol against a caller-supplied `psycopg.Connection`.
- `checkpointers/redis.py` — same idea against a caller-supplied `redis.Redis` client.
- `audit/postgres.py` — implements `QueryableAuditLog` against a caller-supplied `psycopg.Connection`.

Each file is a flat ~50-LOC class. The framework no longer ships these — copy whichever you need into your project, adapt the table name or key prefix, and pass your own connection. The framework's `Checkpointer` and `AuditLog` Protocols are the only contract you need to match.

## When to use Redis vs Postgres

Both implement the same `Checkpointer` Protocol. The choice is about durability, latency, and inspection:

|  | Redis | Postgres |
|---|---|---|
| Durability | RDB + AOF; can lose the tail on crash unless `fsync=always` (slow). | WAL-fsynced; survives crashes cleanly. |
| Latency | Sub-millisecond writes. | Single-digit ms. |
| TTL | Native per-key (`EX` on `SET`). Old checkpoints disappear automatically. | Manual (cron, partition drop). |
| Inspection | `KEYS` / `GET`; no SQL, no joins. | Full SQL — joinable with the app's domain tables. |
| Footprint | Often already in the stack as a cache. | Often already in the stack as the app DB. |

Rule of thumb:

- **Redis** for short-lived workflows (minutes to a few hours), high throughput, where you're OK losing the last few checkpoints on a hard crash and want automatic TTL cleanup.
- **Postgres** for long-running workflows (hours to days, anything that uses `Pause` for human approval), compliance/audit needs, or when you want to query checkpoint history with SQL.

For most Signature client apps already running on PostgreSQL Flexible Server, Postgres is the default; Redis is the choice when latency matters more than durability.

## File layout

```
software_factory/
├── README.md
├── __main__.py            # entry point — crash, then resume
├── state.py               # BuildState pydantic model + extend reducer
├── agents.py              # 5 stub agents (architect, codegen, builder, qa, stable_release)
├── pipeline.py            # build_pipeline(); qa_router
├── progress.py            # StatePipelineEventHandler implementation
├── checkpointers/
│   ├── postgres.py        # Checkpointer Protocol impl (psycopg)
│   └── redis.py           # Checkpointer Protocol impl (redis-py)
└── audit/
    └── postgres.py        # QueryableAuditLog Protocol impl (psycopg)
```

The end-to-end smoke test lives at `tests/examples/software_factory/test_pipeline.py` — same shape as the other example tests in this repo.
