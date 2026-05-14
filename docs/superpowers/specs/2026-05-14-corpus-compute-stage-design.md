# Corpus answer compute stage: deterministic calculations + steps trail

Date: 2026-05-14
Owner: javier-alvarez
Modules touched: `fireflyframework_agentic/reasoning/`, `fireflyframework_agentic/rag/retrieval/`, `fireflyframework_agentic/rag/agent.py`

## Background

Today, `CorpusAgent.query()` in `rag/agent.py:615-646` runs unstructured retrieval (BM25 + vector + reranker → top-k chunks) and structured retrieval (agentic text-to-SQL loop → result table or probe trail) in parallel, then hands both to `AnswerAgent.answer()` in `rag/retrieval/answerer.py:128-189`. The answerer is **Sonnet without tools**: it receives chunks and SQL results and must synthesize a final answer in one shot.

This produces three observed failure classes:

1. **Arithmetic on SQL results.** SQL returns the right rows, but Sonnet re-aggregates / computes percentages / sums in prose and gets it wrong. The model has no way to *run* the arithmetic — it has to *infer* it from text.
2. **Multi-step reasoning / joins.** Questions like "who are the direct reports of Javier" require a chain of lookups (find Javier's id → query employees where manager_id = ...). The single SQL pass can return one of the legs but the join across legs falls back to Sonnet's prose-stitching, which is unreliable.
3. **Unit / date / scale conversions.** USD vs EUR, FY vs calendar year, K/M/B scaling, headcount vs FTE. Sonnet sometimes converts silently or inconsistently with the source.

Beyond correctness, there is a **trust gap**: even when the answer is right, users cannot see how it was computed. There is no record of which SQL ran, which rows it returned, what was multiplied by what. The OTel telemetry in `rag/_telemetry.py` captures per-stage durations and citation counts but not the actual computations.

## Goals

- Replace the single-shot Sonnet answer with a three-stage pipeline: **retrieve → compute & verify → narrate**.
- The compute stage produces a structured `ReasoningResult[ComputedFacts]` containing both the computed values and a `ReasoningTrace` of the steps that produced them.
- Each step is deterministic (Python-executed) with explicit inputs, outputs, and citations — the LLM picks the step and arguments, but does not perform arithmetic in its head.
- The trace rides along on the returned `Answer` so callers (MCP, CLI) can render the steps trail under the prose answer.
- Build the compute stage as a **generic reasoning pattern** (`CorpusComputePattern` or successor) in `fireflyframework_agentic/reasoning/`, so it is reusable for other features and follows the existing `AbstractReasoningPattern` contract.
- Keep the narrator (Sonnet) strictly responsible for prose + citations — never for computation.

## Non-goals

- Replacing the existing structured / SQL retriever. The SQL agent in `rag/retrieval/sql.py` keeps its role: produce one initial structured retrieval pass. The new compute stage can *also* run SQL via its toolkit, but it does not subsume the first-pass retriever.
- Adding a general-purpose Python code interpreter / sandboxed REPL. The toolkit is a fixed set of typed operations (sql, arith, join, convert, lookup, verify). This bounds the surface and keeps every step inspectable.
- Wholesale rewrite of `AnswerAgent`. The narrator role survives — its prompt is tightened and its inputs change (it receives `ComputedFacts` + chunks, not raw SQL tables), but the `Answer` Pydantic model is extended additively.
- Streaming / incremental rendering of the trace. The trace is returned in full with the final answer. Streaming UX is a future concern.
- Optimising the compute stage for token cost or latency in this iteration. Correctness and traceability first; we will measure and tighten in a follow-up.
- Changing how citations work for chunks. Existing `[chunk_id]` inline citation rules apply to the narrator's prose output unchanged.

## Design

### Architecture

```
question
   │
   ├──► (existing) parallel retrieval ──► top_hits (List[ChunkHit])
   │                                       sql_outcome (SqlRetrievalOutcome)
   │
   ▼
[NEW] CorpusComputePattern.run(question, top_hits, sql_outcome)
   │
   │  Plan:
   │    Step 1 — sql_run("SELECT id FROM employees WHERE name='Javier'")
   │    Step 2 — sql_run("SELECT name FROM employees WHERE manager_id=:id", from Step 1)
   │    Step 3 — arith({"op":"count","values": <Step 2 rows>})
   │    Step 4 — verify(<chunk_id=org_chart.pdf:p3> supports the result)
   │
   ▼
ReasoningResult[ComputedFacts]
  ├─ output: ComputedFacts(values={"direct_reports_count": 4, "direct_reports": [...]}, citations=[...])
  └─ trace:  ReasoningTrace(steps=[ThoughtStep, ActionStep, ObservationStep, ...])
   │
   ▼
AnswerAgent.narrate(question, ComputedFacts, top_hits)
   │  Sonnet, instructions tightened: NO recomputation, ONLY narrate
   │  Receives the computed values + chunks, outputs prose with [chunk_id] citations
   ▼
Answer(text, citations, cited_sources, trace)
```

Two things to highlight in this diagram:

- The existing parallel retrieval step is **unchanged**. `sql_outcome` is still produced by the structured retriever's agentic SQL loop. The compute stage *consumes* it as its starting context; it does not replace it.
- The narrator's role becomes thinner. It no longer sees the raw SQL or has to do arithmetic. It receives a `ComputedFacts` payload and a set of chunks, and must write prose that cites both.

### Component 1: `CorpusComputePattern` (generic reasoning pattern)

**Location:** `fireflyframework_agentic/reasoning/corpus_compute.py` (new file).

A new subclass of `AbstractReasoningPattern`. It follows the same Template Method shape as `PlanAndExecutePattern` but overrides `_act` / `_execute_step` to dispatch on a **typed step kind**, not to call `agent.run(prompt)` for free-text execution.

Public API:

```python
class CorpusComputePattern(AbstractReasoningPattern):
    """Plan a sequence of typed compute steps over corpus retrieval results.

    The LLM produces a plan as a list of ComputeStep discriminated-union items.
    Each step kind has a Python executor (no further LLM call) that produces
    a deterministic ComputeObservation with structured inputs/outputs.
    """

    def __init__(
        self,
        *,
        toolkit: ComputeToolkit,
        max_steps: int = 10,
        model: str | Model | None = None,
        prompts: dict[str, PromptTemplate] | None = None,
        step_timeout: float | None = None,
    ) -> None: ...
```

The toolkit is injected so that the corpus passes a `ComputeToolkit` configured against the corpus SQLite file and the current retrieval results; other callers can pass a different toolkit. The pattern itself is agnostic about what tools exist — it just dispatches by `step.kind` to `toolkit.dispatch(step)`.

The pattern reuses `ReasoningTrace`, `ThoughtStep`, `ActionStep`, `ObservationStep` from `reasoning/trace.py` unchanged. The plan structure reuses `PlanStepDef` and `ReasoningPlan` from `reasoning/models.py` — but `PlanStepDef.action` (new optional field, see Component 3) carries a discriminated `ComputeStep`.

### Component 2: `ComputeStep` discriminated union

**Location:** `fireflyframework_agentic/reasoning/compute_steps.py` (new file).

A Pydantic discriminated union covering the typed operations the compute stage understands. Each variant is the **input schema** for an operation; its executor produces a matching observation.

```python
class SqlRunStep(BaseModel):
    kind: Literal["sql_run"] = "sql_run"
    sql: str                                  # parameterised; :name placeholders
    params: dict[str, Any] = {}               # filled from prior step outputs by step id
    rationale: str                            # one-line "why this query"

class ArithStep(BaseModel):
    kind: Literal["arith"] = "arith"
    op: Literal["count", "sum", "avg", "min", "max", "percent", "diff", "ratio"]
    inputs: list[Any]                         # filled from prior step outputs
    rationale: str

class JoinStep(BaseModel):
    kind: Literal["join"] = "join"            # multi-hop lookup chain over rows
    left: StepRef                             # reference to a prior step's rows
    right_sql: str                            # sql whose result is the right side
    on: dict[str, str]                        # left_col -> right_col
    select: list[str]
    rationale: str

class ConvertStep(BaseModel):
    kind: Literal["convert"] = "convert"
    value: Any
    from_unit: str
    to_unit: str
    rationale: str

class LookupStep(BaseModel):
    kind: Literal["lookup"] = "lookup"        # retrieve a specific chunk by id
    chunk_id: str
    rationale: str

class VerifyStep(BaseModel):
    kind: Literal["verify"] = "verify"        # cross-check a value across sources
    claim: str
    against: list[StepRef]                    # other step outputs / chunks
    rationale: str

ComputeStep = Annotated[
    SqlRunStep | ArithStep | JoinStep | ConvertStep | LookupStep | VerifyStep,
    Field(discriminator="kind"),
]
```

`StepRef` is a small helper: `step_id: str, path: str | None = None` (path is an optional JSONPath into the prior step's structured output, e.g. `"$.rows[*].id"`).

Each step carries a `rationale` string that goes into the trace's `ThoughtStep` content. This is how the steps trail reads naturally — the rationale is the "why" between two `ActionStep`/`ObservationStep` pairs.

### Component 3: `ComputeToolkit` (corpus-bound executors)

**Location:** `fireflyframework_agentic/rag/retrieval/compute_toolkit.py` (new file).

This is the **thin corpus wiring** the scoping decision called for. The toolkit is corpus-specific (knows about the corpus SQLite file, chunks, schemas); the pattern is generic (knows about steps and traces).

```python
class ComputeToolkit:
    def __init__(
        self,
        *,
        corpus_db_path: Path,
        retrieval_context: RetrievalContext,   # top_hits, sql_outcome, schemas
    ) -> None: ...

    async def dispatch(
        self,
        step: ComputeStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation: ...
```

`RetrievalContext` is a tiny dataclass bundling the inputs the toolkit needs from the prior retrieval stage. Executor methods (`_run_sql`, `_run_arith`, `_run_join`, `_run_convert`, `_run_lookup`, `_run_verify`) are private and deterministic. None of them call an LLM. They:

- **`_run_sql`**: parameterise placeholders from `previous` outputs, open the corpus SQLite via the existing `_connect` helper, execute, return rows + columns. Read-only enforcement (no `INSERT`/`UPDATE`/`DELETE`/`DDL` allowed) is checked at parse time.
- **`_run_arith`**: cast inputs to numeric types, apply the op, raise `ComputeError` on incompatible inputs (e.g. summing strings) — the pattern records the failure as an `ObservationStep` and stops or replans.
- **`_run_join`**: take a rows reference (`left`), run `right_sql`, join in Python by `on` mapping, project `select`.
- **`_run_convert`**: a small fixed table of conversions (currency at a configurable rate, time units, decimal/percent, K/M/B scaling). If the conversion is not in the table, fail explicitly — we do not silently call out to external rates.
- **`_run_lookup`**: fetch chunk by id from the corpus.
- **`_run_verify`**: compare a claim against `against` references using a simple match policy (exact, numeric tolerance, substring); produce a verdict plus the evidence excerpts.

Each executor returns a `ComputeObservation` carrying: `step_id`, `output` (structured), `citations` (list of chunk_ids and / or sql query identifiers), `success`, `error`.

### Component 4: extended `Answer` model + narrator instructions

**Location:** `fireflyframework_agentic/rag/retrieval/answerer.py`.

The `Answer` model grows two additive fields:

```python
class Answer(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)
    cited_sources: list[CitedSource] = Field(default_factory=list)
    computed_facts: ComputedFacts | None = None     # NEW
    trace: ReasoningTrace | None = None             # NEW
```

`ComputedFacts` is a simple Pydantic model containing the final `values` dict (named computed scalars / rows) and a `citations` list (which chunk_ids ground each value). It is the output type of `CorpusComputePattern`.

`AnswerAgent` is renamed in spirit (file kept) to a **narrator**:

- It receives `question`, `top_hits`, and a new `computed: ComputedFacts | None` argument.
- The system prompt (`_INSTRUCTIONS`) is amended with a new rule: **do not perform arithmetic, unit conversion, or aggregation. If a quantity is needed, take it verbatim from the `computed_facts.values` block. If a needed value is missing, say so.**
- The chunks-only path (no SQL, no compute) keeps the existing behavior unchanged.

This isolates the computation entirely from the narrator. The narrator's job is to assemble prose with `[chunk_id]` citations and surface the precomputed values; nothing else.

### Component 5: wiring in `CorpusAgent.query`

**Location:** `fireflyframework_agentic/rag/agent.py:615-646`.

The change is small and localised:

```python
async def query(self, question: str, *, top_k: int = 5) -> Answer:
    ...
    schemas = await self._schema_registry.list_schemas()
    top_hits, sql_outcome = await asyncio.gather(
        self.retrieve(question, top_k=top_k, rerank=True),
        self._structured_retriever.retrieve(question, schemas),
    )

    # NEW: compute & verify stage
    compute_result = await self._compute_stage.run(
        question=question,
        top_hits=top_hits,
        sql_outcome=sql_outcome,
        schemas=schemas,
    )

    answer = await self._answerer.answer(
        question,
        top_hits,
        sql_outcome=sql_outcome,
        computed=compute_result.output,
    )
    answer.computed_facts = compute_result.output
    answer.trace = compute_result.trace
    ...
```

`self._compute_stage` is a `CorpusComputeStage` adapter built in `__init__` next to `self._answerer`. It owns the `CorpusComputePattern` instance, the `ComputeToolkit` factory, and the model selection (defaulting to the existing `self._sql_model` for the planner — Haiku is sufficient to pick steps, no need for Sonnet at planning time).

When `sql_outcome.outcome == "no_signal"` and `top_hits` is empty, the compute stage is **skipped** entirely (same short-circuit logic as today). When the compute pattern itself fails (timeout, planner produced an invalid plan), the pipeline falls back to today's behavior: send chunks + sql_outcome to the narrator without a computed-facts block. The trace records the failure for observability.

### Component 6: telemetry & traceability surfaces

**Location:** `fireflyframework_agentic/rag/_telemetry.py`, and the OTel spans inside the new pattern.

- A new OTel span `firefly.rag.compute` is opened per `compute_stage.run` call, with attributes: `n_steps`, `n_sql_runs`, `n_arith`, `compute_outcome` (succeeded / fell_back / failed), `planner_model`.
- Each step inside the pattern records its own span as a child: `firefly.rag.compute.step` with `kind`, `step_id`, `success`, `duration_ms`, `error` (when applicable).
- The `ReasoningTrace` is serialised in `Answer.trace` for downstream rendering (CLI, MCP). It is **not** logged into structured logs by default to avoid leaking PII from chunk excerpts (see CLAUDE.md guardrail: "Don't log request bodies in monitoring tools"). A debug-mode flag in `_telemetry.py` can opt in for local development.

### Component 7: MCP / CLI rendering

**Location:** `fireflyframework_agentic/tools/builtins/corpus_rag.py` and the CLI examples / docs.

- The MCP `corpus_query` tool's response shape is extended to optionally include `trace` and `computed_facts` blocks. Existing fields are unchanged so existing clients keep working.
- The CLI's `query` command (or equivalent docs example) renders the trail under the prose answer when present:

```
$ ff corpus query "How many direct reports does Javier have?"
Javier has 4 direct reports.

How this was computed
  1. SQL — SELECT id FROM employees WHERE name='Javier'
         → id = 18  [source: employees.csv]
  2. SQL — SELECT name FROM employees WHERE manager_id=18
         → 4 rows: Ana, Luis, Pia, Tom
  3. count(rows) = 4
  Verified against: org_chart.pdf:p3
```

Rendering is plain text by default; a `--trace=json` flag emits the structured `ReasoningTrace`.

## Module / file layout

```
fireflyframework_agentic/
├── reasoning/
│   ├── corpus_compute.py      (NEW) — CorpusComputePattern
│   ├── compute_steps.py       (NEW) — ComputeStep union, StepRef, ComputeObservation, ComputedFacts
│   └── ...                              (existing files unchanged, but compute_steps re-exported in __init__)
├── rag/
│   ├── agent.py               (MOD)  — wire compute stage in query()
│   ├── retrieval/
│   │   ├── answerer.py        (MOD)  — narrator role: forbid recomputation, accept ComputedFacts
│   │   ├── compute_toolkit.py (NEW)  — ComputeToolkit and RetrievalContext (corpus-bound executors)
│   │   └── compute_stage.py   (NEW)  — thin adapter: builds toolkit + pattern, exposes run()
│   └── _telemetry.py          (MOD)  — span helpers for compute & per-step
└── tools/builtins/
    └── corpus_rag.py          (MOD)  — surface trace + computed_facts in MCP response
```

## Testing strategy

**Unit tests** (`tests/unit/reasoning/test_corpus_compute.py`):
- Construct `CorpusComputePattern` with a stub toolkit. Feed it canned plans (planner mocked). Assert the dispatched steps run in order, observations are recorded, and the trace shape is correct.
- Per step kind: assert `ComputeError` cases produce a `FAILED` step with the error message in the `ObservationStep`, and that the pattern stops (when `allow_replan=False`) or replans (when on).
- Plan timeout: step_timeout produces a `ReasoningError` recorded in the trace.

**Unit tests for the toolkit** (`tests/unit/corpus_search/test_compute_toolkit.py`):
- Run real `_run_sql` against an in-memory SQLite fixture; assert read-only enforcement (write SQL rejected at parse time).
- `_run_arith` numeric op correctness incl. div-by-zero, bad input types.
- `_run_join` produces correctly projected rows.
- `_run_convert` for the supported conversions; explicit failure for unsupported units.
- `_run_verify` exact / tolerance / substring policies.

**Integration tests** (`tests/integration/test_corpus_agent_compute.py`):
- Full `CorpusAgent.query()` over a small fixture corpus, planner mocked to emit canned plans.
- Three scenarios mirroring the failure classes:
  - Arithmetic: "What's the gross margin?" with revenue and COGS in a fact table.
  - Multi-step join: "Direct reports of Javier" — two-hop SQL.
  - Unit conversion: "Revenue in EUR" against USD source.
- Assert: returned `Answer` has matching prose, `computed_facts.values` carries the expected numeric result, `trace.steps` contains the expected step kinds in order, and chunk-id citations are present in both the narrator prose and the trace.

**No mock-the-database in integration tests** (CLAUDE.md guardrail: real SQLite). Mock only the planner LLM call.

**Telemetry tests** (`tests/unit/rag/test_telemetry_compute.py`):
- Span and metric assertions: `firefly.rag.compute` span emitted, per-step children, `compute_outcome` attribute populated.

## Migration plan

1. Land the generic pattern + step union + tests (no wiring) — `reasoning/corpus_compute.py`, `reasoning/compute_steps.py`, unit tests. Reasoning module is internal; no API commitment yet.
2. Land the corpus-side toolkit + adapter + tests — `rag/retrieval/compute_toolkit.py`, `rag/retrieval/compute_stage.py`, unit tests, no wiring into `query()` yet.
3. Wire `compute_stage` into `CorpusAgent.query()` behind a constructor flag `enable_compute_stage: bool = False`. Add integration tests covering both branches (flag on, flag off → today's behavior). This lets us land the change without changing default behavior.
4. Update `AnswerAgent` instructions and signature to accept `computed: ComputedFacts | None`. Make the new arg optional; existing call sites stay valid.
5. Flip the flag to `True` by default once the integration suite is green. The chunks-only / no-SQL path remains the no-op short-circuit.
6. Update MCP response shape and CLI rendering — additive changes only.
7. Document the steps-trail UX in `docs/` (user-facing) and the pattern in `reasoning/`'s README.

Each step is independently revertable. No breaking changes to `Answer`'s existing fields.

## Open questions for review

- The default planner model. The proposal is to default to `self._sql_model` (Haiku) to keep cost low; Sonnet remains the narrator. Worth confirming this default matches the project's cost/latency posture.
- Conversion table policy. Hardcoded rates feel fragile; the alternative is to require the question or the source to state the rate explicitly and refuse otherwise. The current proposal does the latter — fail explicitly when an unknown unit is asked — which matches CLAUDE.md's "no silent errors" guardrail. Worth confirming.
- Whether `verify` is part of the first cut. It is the most useful for trust but the trickiest to define cleanly. We can scope it as a thin "exact / numeric-tolerance / substring" implementation in this cut and iterate.
