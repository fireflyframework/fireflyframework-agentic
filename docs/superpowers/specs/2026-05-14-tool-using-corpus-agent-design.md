# Tool-using corpus answer agent

Date: 2026-05-14
Owner: javier-alvarez
Modules:
- `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py` (new)
- `fireflyframework_agentic/rag/retrieval/_python_compute.py` (new, private)
- `fireflyframework_agentic/rag/retrieval/answerer.py` (`Answer` gains `reasoning_trace`)
- `fireflyframework_agentic/rag/agent.py` (`CorpusAgent` gains `answer_strategy`)
- `examples/corpus_search/mcp_server.py` (corpus_query tool gains `strategy` + `include_trace`)

## Background

`CorpusAgent.query()` today runs a fixed pipeline: `expand → hybrid retrieve → rerank` in parallel with `StructuredRetriever.retrieve`, then a single `AnswerAgent.answer(question, hits, sql_outcome)` LLM call produces the final `Answer`. The answer LLM has no agency — it receives a pre-built prompt with chunks and (optionally) a SQL result table, and writes prose.

This is fast and cheap, but limits the system to questions the fixed pipeline happens to surface evidence for. Questions that require multiple retrieval rounds, verification across structured + unstructured sources, or post-hoc computation over SQL rows (weighted averages, growth rates, coefficient of variation, etc.) cannot be answered well.

The framework already has the building blocks for a tool-using agent:
- `StructuredRetriever` (`rag/retrieval/sql.py:556-628`) demonstrates a pydantic-ai agent driving a `FireflyAgent(tools=[...])` over a `_LoopContext` with contextvar-scoped state.
- `fireflyframework_agentic/reasoning/trace.py` defines `ReasoningTrace`, `ThoughtStep`, `ActionStep`, `ObservationStep` — exactly the typed step model needed for a reproducible audit trail. `ActionStep` already carries `tool_name` + `tool_args: dict[str, Any]`.

What's missing is the orchestrator that lifts this pattern from the SQL inner loop to the corpus answer layer, with a wider tool surface (knowledge search, structured query, table probe, restricted Python execution).

## Goals

- Replace `AnswerAgent` internals with a ReAct-style tool-using agent that plans its own retrieval and verification path.
- Tools available on day one: `knowledge_search`, `sql_query`, `inspect_table`, `python_compute`.
- Every tool call lands in a typed `ReasoningTrace` as `ActionStep(tool_name, tool_args)` + `ObservationStep` — anyone reading the trace can re-execute the same tool calls and observe the same outputs (modulo timestamps and floating-point reordering).
- Zero behavioural change for existing callers in the default configuration. Opt-in via a strategy flag.
- Reproducibility is testable: a dedicated replay test loads a recorded trace, re-executes every `ActionStep` with its `tool_args`, and verifies observations match.

## Non-goals

- Reusing `ReActPattern` / `PlanAndExecutePattern` from `reasoning/` as the orchestrator. The existing patterns drive text-shaped reason→act→observe loops via plain `agent.run(prompt)` calls and emit placeholder `ActionStep(tool_name="react_action", ...)` (see `react.py:115-134`); they do not dispatch real function tools. Bridging them to pydantic-ai's native tool loop is a separate piece of work and is called out below as a follow-up.
- Adding an explicit `Plan-then-Execute` decomposition step on top of ReAct. ReAct alone fits the four-tool surface; a planning layer can be added later if questions justify it.
- Replacing `StructuredRetriever`. It becomes one of the tools the outer agent calls.
- Web search, filesystem reads, HTTP, subprocess. Out of scope: they would break the "trace + corpus = reproducible" property.
- Promoting trace-translation glue into `reasoning/` as a first-class pattern. Spec'd as a follow-up after a second consumer emerges.

## Design

### 1. Architecture

Public surface (`CorpusAgent.query()` → `Answer`) is unchanged. The internals of the answer phase change from "fixed pipeline" to "tool-using ReAct loop driven by pydantic-ai's native tool calling."

```
CorpusAgent.query(question, *, top_k=5, include_trace=False)
  │
  ├── _ensure_query_ready()                              (unchanged)
  │
  └── ReasoningAnswerAgent.answer(question, include_trace)   (new entry point when answer_strategy="reasoning")
        │
        ├── build system prompt: schema summary + tool catalog + rules + corpus stats
        │
        ├── set _LoopContext in contextvar
        │
        ├── await FireflyAgent(output_type=Answer, tools=[…]).run(
        │     prompt,
        │     usage_limits=UsageLimits(
        │       tool_calls_limit=max_tool_calls,
        │       request_limit=max_llm_calls,
        │     ),
        │ )
        │
        ├── translate AgentRunResult.all_messages() → ReasoningTrace
        │
        ├── enrich Answer.cited_sources from _LoopContext.accumulated_hits
        │
        └── attach reasoning_trace to Answer if include_trace=True
```

Existing components retained, repurposed as tool implementations:
- `QueryExpander`, `HybridRetriever`, `HaikuReranker` — called by `knowledge_search` (via `CorpusAgent.retrieve`).
- `StructuredRetriever` — called by `sql_query`.
- `_build_inspect_tool` primitives in `sql.py` — exposed directly as `inspect_table`.

`AnswerAgent` (the existing fast path) is kept for `answer_strategy="fast"` and remains the default.

### 2. New constructor flag on `CorpusAgent`

```python
class CorpusAgent:
    def __init__(
        self,
        *,
        # … existing params unchanged …
        answer_strategy: Literal["fast", "reasoning"] = "fast",
        max_reasoning_tool_calls: int = 20,
        max_reasoning_llm_calls: int = 10,
        reasoning_wall_clock_seconds: float = 120.0,
    ) -> None: ...
```

`answer_strategy="fast"` is byte-identical to today. `answer_strategy="reasoning"` constructs a `ReasoningAnswerAgent` in `_ensure_query_ready` instead of an `AnswerAgent`. The fast-path remains the default — strategy is opt-in.

### 3. `Answer` schema additions

```python
class Answer(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)
    cited_sources: list[CitedSource] = Field(default_factory=list)
    reasoning_trace: ReasoningTrace | None = None    # NEW
```

`reasoning_trace` defaults to `None`. The MCP `corpus_query` tool serialises with `model_dump(exclude_none=True)` so existing JSON consumers see no new field unless `include_trace=True` is set.

### 4. `ReasoningAnswerAgent`

New file `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`.

```python
class ReasoningAnswerAgent:
    def __init__(
        self,
        *,
        model: str,
        corpus_agent: "CorpusAgent",
        structured_retriever: StructuredRetriever,
        schema_registry: SchemaRegistry,
        db_path: Path,
        max_tool_calls: int = 20,
        max_llm_calls: int = 10,
        wall_clock_seconds: float = 120.0,
    ) -> None:
        self._model = model
        self._corpus_agent = corpus_agent
        self._structured_retriever = structured_retriever
        self._schema_registry = schema_registry
        self._db_path = db_path
        self._max_tool_calls = max_tool_calls
        self._max_llm_calls = max_llm_calls
        self._wall_clock = wall_clock_seconds

        # Tool closures — see Section 5. Each grabs the contextvar-scoped
        # _LoopContext on call; production callers MUST go through answer().
        self._knowledge_search = _build_knowledge_search()
        self._sql_query = _build_sql_query()
        self._inspect_table = _build_inspect_table()
        self._python_compute = _build_python_compute()

        self._agent = FireflyAgent(
            name="reasoning_answerer",
            model=model,
            output_type=Answer,
            instructions=_SYSTEM,
            tools=[self._knowledge_search, self._sql_query, self._inspect_table, self._python_compute],
            auto_register=False,
        )

    async def answer(self, question: str, *, include_trace: bool = False) -> Answer: ...
```

`answer()` builds the prompt, sets the contextvar, calls `self._agent.run(...)` under `asyncio.wait_for(..., timeout=self._wall_clock)`, translates the message history to a `ReasoningTrace`, enriches `cited_sources` from `_LoopContext.accumulated_hits`, optionally attaches the trace, and returns the `Answer`.

On `UsageLimitExceeded` / `TimeoutError` / unhandled exception inside the loop, `answer()` returns a partial `Answer(text="I couldn't complete reasoning within the budget. Partial findings: …", ...)` rather than raising — matches the resilience contract of `StructuredRetriever.retrieve` (`sql.py:621-625`).

### 5. `_LoopContext` and tool closures

Private dataclass, fresh per `answer()` call:

```python
@dataclass(slots=True)
class _LoopContext:
    corpus_agent: "CorpusAgent"
    structured_retriever: StructuredRetriever
    schemas: list[TargetSchema]
    db_path: Path
    accumulated_hits: dict[str, ChunkHit] = field(default_factory=dict)
    sql_calls: list[SqlRetrievalOutcome] = field(default_factory=list)
```

The LLM-call cap (`max_llm_calls`) is enforced by pydantic-ai's `UsageLimits(request_limit=max_llm_calls)` rather than a counter on `_LoopContext` — no hand-tracking required.

Held in `_CURRENT_CTX: contextvars.ContextVar[_LoopContext | None]`. Same idiom as `StructuredRetriever`'s `_CURRENT_CTX` (`sql.py:568`).

Tool signatures and contracts:

**`knowledge_search(query: str, top_k: int = 5) → list[dict]`**
- Calls `ctx.corpus_agent.retrieve(query, top_k=top_k, rerank=True)`.
- Returns `[{"chunk_id", "source_path", "score", "snippet": content[:400]}, …]`.
- Side-effect: every returned `ChunkHit` is recorded in `ctx.accumulated_hits[chunk_id] = hit`.
- When to call: free-text / narrative / definitional questions; supplementing SQL with context.

**`sql_query(question: str) → dict`**
- Calls `ctx.structured_retriever.retrieve(question, ctx.schemas)`.
- Returns `{"outcome", "attempted_sql", "result_markdown", "probe_trail": [{"table","column","op","result"}, …]}`.
- Side-effect: appends the `SqlRetrievalOutcome` to `ctx.sql_calls`.
- When to call: aggregations, filters, lookups, counts.

**`inspect_table(table: str, column: str, op: str, value: str | None = None) → str`**
- Direct SQL probe (no inner LLM). Same op enum as `_build_inspect_tool`: `distinct_values | count | sample_rows | value_range | find_similar | numeric_summary`.
- Returns the markdown string `_build_inspect_tool` already produces.
- When to call: cheap discovery before committing to `sql_query`.

**`python_compute(source: str, data: dict[str, Any] | None = None) → str`**
- Restricted Python execution sandbox. Full spec in Section 6.

### 6. `python_compute` sandbox (`_python_compute.py`)

**Public surface:**

```python
def run_python_compute(
    source: str,
    data: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 5.0,
    output_cap_bytes: int = 8192,
) -> str: ...
```

Returns the value bound to `result` after executing `source` in a restricted namespace (or the value of the last expression if `result` is not set), plus any captured stdout. Output combined cap is `output_cap_bytes`, then truncated with `"… (truncated, N more bytes)"`.

**Allowed source shape:** multi-line — assignments, loops, conditionals, comprehensions, try/except, function/class defs.

**Pre-populated namespace:**
- Stdlib modules: `math`, `statistics`, `decimal`, `fractions`, `datetime`, `calendar`, `re`, `string`, `textwrap`, `unicodedata`, `json`, `collections`, `itertools`, `functools`, `operator`, `dataclasses`, `enum`. A deterministic random source is exposed as `random` bound to a fresh `random.Random(0)` instance per `python_compute` call — we never reseed the global `random` module, so the sandbox cannot perturb host state.
- Third-party: `numpy` (as `np`), `pandas` (as `pd`). Lazy-imported on first call.
- `data` keys bound as locals.
- Builtins whitelist: `abs, all, any, bool, bytes, chr, dict, divmod, enumerate, filter, float, frozenset, int, isinstance, issubclass, iter, len, list, map, max, min, next, ord, pow, range, repr, reversed, round, set, slice, sorted, str, sum, tuple, zip`.
- `print()` redirected to an in-memory buffer; captured text is appended to the returned string.

**AST-enforced denylist** (validated by walking the parsed AST before execution; any violation returns `"python_compute error: <reason>"`):
- Names starting with `__` (blocks reflection escapes via `().__class__.__bases__[0].__subclasses__()` and dunder access on builtins).
- Calls to the Python builtins `eval`, `exec`, `compile`, `__import__`, `open`, `input`, `breakpoint`, `help`, `dir`, `vars`, `globals`, `locals`.
- `import` of any name not in the module whitelist above.
- `from <X> import …` of any module not in the whitelist.
- Attribute access whose attribute name is one of: `__globals__, __locals__, __builtins__, __code__, __closure__, __class__, __subclasses__, __bases__, __mro__, __dict__, __module__, __reduce__, __reduce_ex__, __getattribute__, __setattr__, __delattr__, __init_subclass__`.

**Resource limits:**
- Wall-clock timeout: 5s default, enforced by running the body in a worker thread with a join timeout. Pragmatic, not adversarially safe — we trust our own model, not an attacker. On timeout returns `"python_compute timeout after 5s"`.
- Output cap: 8 KB combined (stdout + result repr).

**Result rendering:**
- `pd.DataFrame` → `to_markdown(index=False)`.
- `np.ndarray` → `repr` inside `numpy.printoptions(threshold=200, edgeitems=3)`.
- Anything else → `repr(result)`.

**Dependencies:** `numpy` and `pandas` are added to a new optional extra `reasoning-eval` in `pyproject.toml`. `_python_compute.py` lazy-imports on first call; a missing import raises a clean `RuntimeError("install fireflyframework-agentic[reasoning-eval] to use python_compute")` that `answer()` surfaces back into the agent as a tool error so the model can stop calling it.

### 7. Trace translation

`_trace_from_run_result(result: AgentRunResult, *, pattern_name: str = "reasoning_answerer") → ReasoningTrace`.

Walks `result.all_messages()` and emits:

| pydantic-ai part | Emit |
|------------------|------|
| `UserPromptPart` (our prompt) | skip |
| `SystemPromptPart` | skip |
| `TextPart` from model (intermediate, not final structured-output) | `ThoughtStep(content=text)` |
| `ToolCallPart` | `ActionStep(tool_name=part.tool_name, tool_args=part.args_as_dict)` |
| `ToolReturnPart` | `ObservationStep(content=_truncate(part.content, 2000), source=part.tool_name)` |
| Final structured-output part | skip (captured as `Answer`) |

`ObservationStep.content` truncation: 2000 chars max with `"… (N more bytes)"` suffix. Full results stay recoverable by re-running the tool from the `ActionStep.tool_args`.

Translation is **lossless for `tool_name` + `tool_args`** — that's the reproducibility-critical property.

### 8. Citation enrichment

Reuse `_build_cited_sources` from `answerer.py:116` verbatim. The only change: feed it `list(ctx.accumulated_hits.values())` (union across all `knowledge_search` calls) instead of a single `retrieve()` result. SQL evidence is not represented in `cited_sources`; it lives in the trace as `ActionStep(tool_name="sql_query", tool_args={"question": ...})` with the full `attempted_sql` in the corresponding `ObservationStep`.

### 9. System prompt skeleton

Lives in `reasoning_answerer.py` as `_SYSTEM`. Includes:

1. Role: "You answer questions about a corpus by calling tools to retrieve and verify evidence."
2. Schema summary: rendered via `_build_schema_context(schemas, db_path)` (reuse existing helper from `sql.py`).
3. Corpus stats hint: doc_count, chunk_count, schema_count (from `CorpusStats`).
4. Tool catalog: one-paragraph description per tool, with the "when to call" rule.
5. Strategy rules:
   - Probe cheap before committing expensive. `inspect_table` < `sql_query` (which spawns an inner LLM loop).
   - For numeric answers, verify with `python_compute` over the returned rows when the calculation is non-trivial (weighted means, growth rates, stdev, CV, ratios).
   - Cite `knowledge_search` chunks inline as `[chunk_id]`; SQL-grounded claims should name the source table.
   - If neither retrieval nor SQL surfaces evidence, return `"I don't have enough information."` (unchanged contract).
   - Language and diacritic rules from `_INSTRUCTIONS` in `answerer.py:35-74` — copied verbatim.

### 10. MCP surface

`corpus_query` tool in `examples/corpus_search/mcp_server.py` gains two optional kwargs:

```python
async def corpus_query(
    corpus_id: str,
    question: str,
    top_k: int = 5,
    strategy: Literal["fast", "reasoning"] = "fast",
    include_trace: bool = False,
) -> dict[str, Any]: ...
```

Existing fast-path callers see no change. New callers opt into reasoning explicitly. Response JSON gains an optional `reasoning_trace` field when `include_trace=True`, serialised via `Answer.model_dump(exclude_none=True)`.

## Tests

### Unit (`tests/unit/corpus_search/`)

1. **`test_reasoning_answerer.py`** — `ReasoningAnswerAgent` with a stubbed pydantic-ai model. Replay a pre-baked tool-call sequence. Cases:
   - Knowledge-only path → Answer with citations.
   - SQL-only path → Answer with SQL evidence in trace.
   - Mixed path: knowledge_search → sql_query → python_compute → Answer.
   - No-info path: tools called, returned empty, Answer is `"I don't have enough information."`
   - Tool-limit exhaustion: `UsageLimits(tool_calls_limit=N)` triggers, partial Answer returned with note.
   - Wall-clock timeout: `asyncio.wait_for` fires, partial Answer returned.

2. **`test_python_compute_sandbox.py`** —
   - Happy path: multi-line code; `numpy.mean`; `pandas.DataFrame` → markdown.
   - Denylist (each pattern, separate test case): `__import__('os').system('…')`, `().__class__.__bases__[0].__subclasses__()`, attribute access to `__globals__`, calls to the `eval` builtin, `import os`, `from sys import argv`, dunder name on user variable.
   - Error paths: syntax error, undefined name, type error, timeout, output truncation past `output_cap_bytes`.
   - Determinism: `random.random()` using the per-call `Random(0)` instance produces the same value across runs.

3. **`test_trace_translation.py`** — pure function: synthetic `all_messages()` sequences mapped to expected `ReasoningTrace.steps`. No LLM, no I/O.

4. **`test_citation_enrichment.py`** — `_LoopContext.accumulated_hits` populated from multiple stubbed `knowledge_search` calls; `cited_sources` is the union; hallucinated chunk_ids dropped.

5. **`test_corpus_agent_strategy_flag.py`** — `answer_strategy="fast"` runs the unchanged path (regression guard); `"reasoning"` instantiates `ReasoningAnswerAgent`.

### Integration (`tests/examples/corpus_search/`)

A new `tests/examples/corpus_search/benchmark/corpus/reasoning/` fixture set:
- `quarterly_revenue.csv` — `business_unit, region, product, year, quarter, revenue_usd, units_sold`, ~150 rows. Includes NULL revenue cells.
- `headcount_snapshots.csv` — `business_unit, snapshot_date, headcount`, quarterly snapshots.
- `methodology.md` — defines "Operating Efficiency" = revenue per headcount. Drives the joint RAG+SQL+python_compute path.

Ground-truth values committed in `tests/examples/corpus_search/reasoning_fixtures.py` as a dict.

#### End-to-end test questions

| # | Question | Path | Assertion |
|---|----------|------|-----------|
| 1 | "What's the YoY revenue growth rate per business unit from 2023 to 2024?" | sql_query → python_compute | Each BU's growth rate within 0.1pp; trace has ≥1 `sql_query` followed by `python_compute` whose `data` derives from the SQL rows |
| 2 | "What's the weighted average price across products, weighted by units sold?" | sql_query → python_compute (`sum(p*u)/sum(u)`) | Numeric within 0.01; `python_compute.source` contains the weighted-mean formula |
| 3 | "For Q4 2024 revenue, treat blank cells as 0 — what's the mean per region and the standard deviation?" | sql_query with COALESCE → python_compute using `statistics.stdev` | Both stats within 0.01; `python_compute.source` references `statistics` |
| 4 | "What's the coefficient of variation of monthly headcount per BU, and rank BUs most-stable to least-stable?" | sql_query → python_compute (CV per BU, sort) | Ranking matches ground truth exactly |
| 5 | "What's the Operating Efficiency for each BU in 2024 Q3?" | knowledge_search → sql_query → python_compute | Each BU within 0.5; trace has `knowledge_search` BEFORE `sql_query`; `Answer.text` cites the methodology chunk_id |

#### Tier A — deterministic replay (`@pytest.mark.integration`, PR gate)

Per question, a JSON replay fixture at `tests/examples/corpus_search/replay/q{N}_<slug>.json` records the model's tool-call decisions for that question. The test:

1. Loads the fixture corpus into a real `CorpusAgent` (real SQLite, real sqlite-vec, real embedder stub).
2. Stubs the pydantic-ai inner model with a `FunctionModel` that returns the next pre-recorded tool call (or final `Answer`) on each turn.
3. Real tool closures run against the real DB and `_python_compute` sandbox.
4. Asserts: `Answer.text` contains the expected value; `ReasoningTrace.steps` matches the recorded `ActionStep` sequence (by tool_name + tool_args); the value-producing tool was actually called; `tool_args` is JSON-serialisable on every step.

#### Tier B — real-LLM end-to-end (`@pytest.mark.nightly`)

Same 5 questions, real LLM. Tolerances loosened:
- Answer must contain expected value within stated tolerance.
- Trace contains ≥1 `sql_query` and ≥1 `python_compute`.
- `python_compute.source` references variable names populated from a prior `sql_query` observation (regex grep).

One retry per question on flake. Three nightlies red in a row = real regression.

#### Reproducibility self-test — `test_trace_is_replayable.py`

Single high-value test:

1. Run question 1 in Tier A. Capture `Answer.reasoning_trace`.
2. Build a fresh `_LoopContext` (new DB connection, empty `accumulated_hits`).
3. Walk `reasoning_trace.steps`. For each `ActionStep`, look up the corresponding tool closure and call it with `step.tool_args`. Capture the observation.
4. Compare each replayed observation against the original `ObservationStep.content`.
5. Run the final `python_compute` step and assert its returned value matches.

This test *is* the spec's central claim: traces are reproducible.

#### Capture helper

`scripts/capture_reasoning_replay.py` — operator-only CLI that runs one question through Tier B and writes the resulting tool-call sequence as a Tier A JSON fixture. Used to refresh fixtures when the prompt changes. Not part of the test suite.

## Observability

New telemetry, routed through `fireflyframework_agentic/rag/_telemetry.py`:

- **Span** `firefly.rag.reasoning.answer` (replaces `firefly.rag.answer` when `strategy=reasoning`). Attributes: `tool_calls_total`, `tool_calls_by_name.knowledge_search`, `tool_calls_by_name.sql_query`, `tool_calls_by_name.inspect_table`, `tool_calls_by_name.python_compute`, `n_messages`, `terminal_state ∈ {answered, no_info, tool_limit, llm_limit, timeout, error}`.
- **Histogram** `firefly.rag.reasoning.tool_call_duration_ms`, labelled by `tool_name`.
- **Counter** `firefly.rag.reasoning.terminal_state`, labelled by outcome.
- **Existing** `firefly.rag.query` span gains attribute `firefly.rag.answer_strategy ∈ {fast, reasoning}` regardless of which path ran.
- **Cost tracking**: pydantic-ai's `result.usage()` aggregates token usage across every internal turn; recorded under `agent="reasoning_answerer"` in `default_usage_tracker` — no new code required, budget enforcement just works.

## Rollout phasing

- **Phase 1 (this spec):** ship the implementation. Default `answer_strategy="fast"`. Strategy is opt-in at construction and at the MCP boundary. Zero behavioural change for existing callers.
- **Phase 2 (separate PR):** MCP `corpus_query` gains `strategy` + `include_trace` params. Documented in the use-case guide.
- **Phase 3 (separate PR, after eval comparison):** flip default to `"reasoning"` in a minor version bump. `"fast"` remains as the cost-sensitive escape hatch.

## Docs updates

- `docs/use-case-corpus-search.md` — new section: "Reasoning answers and reproducible traces" — one worked example with a short trace and the equivalent CLI replay command.
- `docs/reasoning.md` — note the gap (existing patterns don't dispatch real tools) and the framework's chosen approach (delegate to pydantic-ai's native tool loop and translate the message history). Flag the follow-up: promoting `ToolCallingReActPattern` into `reasoning/`.
- `CHANGELOG.md` — entry under "Added": `answer_strategy` flag, `reasoning_trace` field on `Answer`, `[reasoning-eval]` optional extra. Note the default stays `"fast"` in this release.

## Implementation order

1. `_python_compute.py` + sandbox unit tests. Standalone — no other deps.
2. Tool closures (`knowledge_search`, `sql_query`, `inspect_table`, `python_compute`) over `_LoopContext` + per-tool unit tests with stubbed `corpus_agent` / `structured_retriever`.
3. `_trace_from_run_result` + trace-translation tests.
4. `ReasoningAnswerAgent` + integration tests with stubbed model.
5. `Answer.reasoning_trace` field; `CorpusAgent.answer_strategy` plumbing; regression test that `"fast"` is unchanged.
6. Fixture corpus + Tier A integration tests (5 questions).
7. Reproducibility self-test (`test_trace_is_replayable.py`).
8. MCP wire-through (`strategy`, `include_trace`).
9. Tier B nightly tests + capture helper.
10. Docs + CHANGELOG.

## Open follow-ups (out of scope for this spec)

- Promote `ToolCallingReActPattern` into `fireflyframework_agentic/reasoning/` once a second consumer emerges (research agent, evaluator agent). Carry over the trace-translation helper.
- Plan-then-ReAct decomposition for multi-hop questions (the agent plans sub-questions, runs a small ReAct loop per sub-question). Punt until questions in the wild demand it.
- Streaming traces — emit `ActionStep`s as they happen rather than at the end of `answer()`. Useful for chat UIs showing reasoning live.
- Per-corpus tool customisation — let an operator disable `python_compute` or restrict `inspect_table` ops on a per-corpus basis.
- **Pydantic Monty evaluation** (tracked in #186): two watch-items — (A) replacing `_python_compute.py`'s AST-validated Python sandbox with Monty's Rust-based interpreter once its pydantic-ai integration GAs and numpy/pandas are supported; (B) adding an alternate `answer_strategy="monty"` where the LLM writes one Python script that calls tools as functions, reducing round-trips on multi-step questions.
