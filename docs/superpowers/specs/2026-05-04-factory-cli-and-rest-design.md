# Spec 7 — Factory CLI + REST/SSE Entry

**Date:** 2026-05-04
**Status:** Draft — MVP2 backlog (not approved)
**Owner:** Agentic Factory MVP2
**Depends on:** Spec 6 (programmatic pipeline)
**Required by:** developer ergonomics; eventual portal UI in Phase 2

---

## Context

Once the factory runs as a programmatic DAG (Spec 6), two additional surfaces become valuable:

- **A `firefly-factory` CLI** — for developers iterating on intents locally without round-tripping GitHub.
- **A REST/SSE endpoint** — for host applications (e.g., a Phase-2 portal) to drive the factory and stream progress to UI clients.

Both surfaces are thin wrappers over `build_factory_pipeline().run(...)` plus the existing exposure layer (`fireflyframework_agentic.exposure.rest.create_agentic_app`).

## Non-goals

- A frontend. Phase 2 builds the portal.
- Authentication and tenancy. Spec 13 owns that.
- Job queueing across processes. The endpoint runs the pipeline in the same process.

## Sketch

### CLI

`firefly-factory` shipped via `[project.scripts]`:

| Command | Behavior |
|---|---|
| `firefly-factory run --intent "<text>" [--workspace ./out] [--max-iterations 3]` | Run the full pipeline, stream agent logs to stderr, exit 0 on green QA, exit 1 on max-iterations exhausted. |
| `firefly-factory define --intent "..."` | Run only `product_owner`; print PRD to stdout. |
| `firefly-factory design --prd <path>` | Run only `architect`; print ADR to stdout. |
| `firefly-factory generate --adr <path> --workspace ./out` | Run only `codegen`; write files to workspace. |
| `firefly-factory qa --workspace ./out` | Run only `qa`; print QAReport JSON to stdout. |
| `firefly-factory knowledge-base index` | Re-index the bundled knowledge_base/. |

CLI module: `src/fireflyframework_agentic/factory/cli/`.

### REST

Added to the existing `create_agentic_app()`-built FastAPI app:

| Endpoint | Method | Behavior |
|---|---|---|
| `/api/factory/run` | POST (SSE) | Body: `{intent, max_iterations?, workspace?}`. Streams `PipelineEvent` per stage. Final event carries `RunResult`. |
| `/api/factory/runs/{run_id}` | GET | In-memory fetch of last N runs (no persistence). |

The SSE stream reuses the existing `PipelineEventHandler` infrastructure — no new event protocol.

## Verification

- `firefly-factory run --intent "hello"` against stubbed agents completes in < 5 s and prints a green summary.
- `curl -N -X POST localhost:8000/api/factory/run -d '{"intent":"hello"}'` streams the same events the CLI surfaces, in order.
- A `pytest` integration test runs the FastAPI app with `httpx.AsyncClient` and asserts the SSE stream contains the expected stage markers.

## Open questions

- Should `firefly-factory run` push to GitHub by default, or stay headless? Spec proposes headless (write to `--workspace`) — pushing should be opt-in via `--push <repo>`.
- Should there be a `firefly-factory replay` for debugging a prior run from logs? Probably yes, but it depends on persistence (Spec 13) — defer.
