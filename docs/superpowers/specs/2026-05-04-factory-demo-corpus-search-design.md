# Spec 5 — Factory Demo: Corpus Search Agent

**Date:** 2026-05-04
**Status:** Draft
**Owner:** Agentic Factory MVP1
**Depends on:** Spec 1 (action runtime), Spec 2 (knowledge base), Spec 3 (specialized agents), Spec 4 (workflows)
**Required by:** Definition of Done for the factory MVP1 itself.

---

## Context

The factory MVP1 is only proven when it can take a real natural-language intent and end-to-end produce a Pull Request whose CI is green and whose code does what the intent asked for. This spec defines the first such demo: have the factory generate the **corpus-search agent** described in `docs/use-case-corpus-search.md` — a small pyfly-style service that watches a folder, ingests documents through `markitdown`, persists chunks + FTS5 + Chroma, and exposes a hybrid BM25+vector query API with citations.

This use case is the right first demo because:

1. **It already has a written design** (`docs/use-case-corpus-search.md`), which seeds the `product_owner` agent's input deterministically — the demo's PRD is not "novel" work, it is a re-derivation. That isolates factory bugs from intent ambiguity.
2. **Single-domain, small scope**: ingest + query, two operations, all primitives already in the agentic library (markitdown loader, chunkers, embedders, vector stores, hybrid retrieval). The factory's job is wiring, not invention.
3. **Linear architecture**: no fan-out, no cross-service contracts, no infrastructure beyond local disk. Stresses the four agents end-to-end without dragging in deploy concerns.
4. **Demonstrable in <30 minutes** of factory wall-clock time and < $5 of LLM cost.

## Non-goals

- Demoing the deployer (there is none in MVP1).
- Multi-stack: this demo is pyfly-only.
- The V2/V3 extensions described in `use-case-corpus-search.md` (post-processing extractors, property graph). The factory generates V1 only.
- Productizing the corpus-search agent itself. The output is a working PR; merging and operationalizing it is a separate decision.

## The intent

The intent fed to `factory-run.yml` is a 200-word brief, not the full design doc. The longer doc remains in `knowledge_base/` (or attached as a context artifact via Spec 2's `knowledge_search`) so the `product_owner` agent can retrieve it during goal decomposition.

```
Generate a Python service that watches a folder for documents (PDF, DOCX, PPTX,
markdown), ingests each new file through markitdown, chunks each document into
~800-token windows, embeds each chunk with OpenAI text-embedding-3-small, and
persists chunks + an FTS5 index in SQLite (./kg/corpus.sqlite, WAL mode) and the
chunk vectors in a Chroma PersistentClient (./kg/chroma/). Expose a query API:
given a natural-language question, expand it into 3-5 reformulations using Claude
Haiku, run BM25 and vector search for each reformulation, fuse rankings via RRF
with k=60, and synthesise an answer with [chunk_id] citations using Claude Sonnet.
Ship as a single CLI: `corpus ingest <path>`, `corpus watch <path>`, `corpus
query "<question>"`. Storage root is configurable (default ./kg/). All deps must
be Python libraries — no daemons, no docker. Add unit tests for chunking,
ingestion idempotency, and query happy path.
```

This text is checked in at `tests/factory/demos/corpus_search/intent.txt` and is the input the QA harness uses.

## Expected factory outputs

### `product_owner` produces

- **`PRD.md`** with sections:
  - Context (1 paragraph: "We need a small corpus-search service…").
  - Objectives: (1) ingest, (2) query with citations, (3) zero-infra deployment.
  - Acceptance criteria (verbatim list, each must hold for QA to pass — see below).
  - Out of scope: graph layer, V2 extractors, multi-tenancy.
  - Risks: embedding cost at scale, file-watcher race conditions on rapid edits.
  - Assumptions: OpenAI + Anthropic API keys provided by env; single-machine deployment.
- **`SPEC.yaml`** — machine-readable, schema per Spec 3 — with the acceptance criteria as structured items so `architect` and `qa` can refer to them by id.

### `architect` produces

- **`ADR.md`** documenting the choice of:
  - SQLite (FTS5 + ledger) over a separate FTS engine.
  - Chroma `PersistentClient` over `sqlite-vec` for chunk vectors (because Chroma is required by the use-case doc; a follow-up ADR can reconsider).
  - `watchfiles` over polling.
  - Hybrid BM25 + Chroma retrieval with RRF fusion.
- **`architecture.yaml`** with modules: `corpus.ingest`, `corpus.store`, `corpus.retrieval`, `corpus.cli`, plus the chosen `archetype: pyfly-fastapi-microservice` (extended with a CLI module — see Spec 2 open question).

### `codegen` produces

A repository with this layout (committed on a new branch and opened as a PR):

```
corpus-search/
├── pyproject.toml          # markitdown[pdf,docx,pptx], chromadb, watchfiles, click, anthropic, openai
├── README.md
├── corpus/
│   ├── __init__.py
│   ├── cli.py              # `corpus ingest|watch|query` via click
│   ├── ingest/
│   │   ├── loader.py       # markitdown wrapper
│   │   ├── chunker.py
│   │   └── pipeline.py
│   ├── store/
│   │   ├── sqlite.py       # ledger + FTS5
│   │   └── chroma.py       # PersistentClient wrapper
│   ├── retrieval/
│   │   ├── expand.py       # Haiku query expansion
│   │   ├── search.py       # BM25 + vector + RRF
│   │   └── synthesise.py   # Sonnet answer + citations
│   └── config.py
├── tests/
│   ├── test_chunker.py
│   ├── test_ingest_idempotent.py
│   └── test_query_happy_path.py
└── .github/workflows/
    └── ci.yml              # ruff + pytest
```

### `qa` verifies

The acceptance criteria the `qa` agent runs against the PR's CI results:

| ID | Criterion | How qa verifies |
|---|---|---|
| AC1 | `corpus ingest tests/fixtures/` ingests 5 fixture documents idempotently | Runs the CLI; asserts `corpus.sqlite` row count = 5 chunks-per-doc × 5 docs (within tolerance); re-runs and asserts no duplicates. |
| AC2 | `corpus query "<known-fact>"` returns a non-empty answer with at least one `[chunk_id]` citation | Runs the CLI; parses output; asserts citation regex matches at least once. |
| AC3 | All `pytest` tests pass | Reads CI workflow run; asserts conclusion `success`. |
| AC4 | `ruff check .` passes | Reads CI workflow run; asserts ruff job conclusion `success`. |
| AC5 | No `INFO` log shows an exception traceback during ingest | Tails the CLI logs; greps for `Traceback`; asserts none. |
| AC6 | First query latency < 10 s on the 5-doc fixture corpus | Times the query CLI invocation. |
| AC7 | The codebase contains no calls to `requests`, `urllib3`, or other HTTP libs except via OpenAI/Anthropic SDKs | Static check with `grep -r`. Enforces "no daemons, no servers" constraint. |

If any criterion fails, `qa` produces a `QAReport.json` whose `failures[]` reference the criterion id, and the QA loop (Spec 4) re-dispatches `factory-generate.yml` with the report attached.

## Definition of done for the demo

1. Run `gh workflow run factory-run.yml -F intent="$(cat tests/factory/demos/corpus_search/intent.txt)"` against a clean target repo.
2. Within 30 minutes, the run produces:
   - A merged-ready PR labeled `factory:generated`.
   - All seven acceptance criteria pass per the `qa` agent's report.
   - A CalVer tag `2026.05.0` on the PR head SHA after merge.
3. Total LLM cost recorded by `UsageTracker` is below $5.
4. The QA loop iteration count is recorded; iteration ≤ 2 is the success bar (one re-roll allowed; chronic 3-iteration runs indicate prompt or knowledge-base gaps).

## Alternative use cases considered (not chosen for the first demo)

- **IDP pipeline.** Has a working reference at `examples/idp_pipeline.py`. Exercises Reflexion + validation + memory + 7-node DAG together. **Risk:** too large for a first demo — the factory's failure modes will be hard to disentangle from the IDP's complexity. Promote to MVP2 demo.
- **TODO REST microservice.** Smallest possible scope. **Risk:** doesn't exercise the agentic library's distinctive value (RAG, hybrid retrieval, reasoning patterns). The demo would look like a generic CRUD generator.
- **Conversational FAQ bot.** Narrow scope, low cost. **Risk:** no build/QA loop muscle — the factory's QA feedback loop barely fires. Doesn't prove the loop's value.

Recommendation stays: **corpus search**.

## Verification

For this spec itself (planning):
- The intent text is checked in to `tests/factory/demos/corpus_search/intent.txt`.
- The acceptance criteria table is exhaustive (every claim in the use-case doc has at least one criterion).
- The expected repository layout is plausible against the chosen archetype + the use-case doc's storage constraints.

For the demo's eventual run (out of scope for spec-writing):
- A clean target repo (e.g. `signature/demo-corpus-search`) is set up with the factory workflows checked in (per Spec 4) and `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` secrets.
- `factory-run.yml` is dispatched with the intent.
- The DoD's three success bars (PR green, AC1–AC7 pass, < $5 cost) are met within two iterations.

## Open questions

- The use-case doc allows OpenAI for embeddings and Anthropic for reasoning. Should the demo pin specific model versions, or let the agents pick the latest? Spec proposes pinning in `architecture.yaml` so the demo is reproducible across months.
- AC6's 10s latency budget is generous and covers cold-start of Chroma. Re-run latency should be sub-second; do we add an AC for that? Spec proposes no — sub-second is implied by AC3 (tests pass) and over-specifying invites flakes on slow runners.
- Should the demo target repo be a temporary fresh repo per run, or a long-lived `signature/demo-corpus-search` reused across runs? Spec proposes long-lived for ease of inspection; PR per run keeps history clean.
