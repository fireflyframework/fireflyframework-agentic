# Corpus Search End-to-End with Real Data + Azure Monitor / AppInsights

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

| | |
|---|---|
| Status | **Approved** |
| Date | 2026-05-04 |
| Branch | `javi/corpus-search-e2e-appinsights` |
| Pull request | [#102](https://github.com/fireflyframework/fireflyframework-agentic/pull/102) |
| Author | Javier Alvarez-Valle |

---

## 1. Goal

Run the existing `examples/corpus_search` agent end-to-end against a real
multi-format research corpus (operator-supplied, dropped into `./drop`),
verify retrieval and answer quality with a hand-curated test bank, and confirm
that **OpenTelemetry traces, metrics, and logs flow into Azure Application
Insights** unchanged when the framework is deployed to Azure. The exercise
doubles as the acceptance test for the upcoming Azure deployment.

The specific corpus used in the validation run is operator-supplied and
held locally only — neither its filenames nor its contents are checked
into this repository. See `examples/corpus_search/test_queries.template.md`
for the test-bank pattern operators use against their own corpus.

The work also fixes two real telemetry gaps in the framework that are
backend-agnostic — they block any vendor, not just Azure — so they ship in the
same PR rather than as a separate cleanup.

## 2. Non-goals

- No production Azure deployment in this iteration; we validate locally with the
  Azure Monitor exporter pointed at a real AppInsights resource.
- No new corpus features (no extractors, no graph layer — V2/V3 from the
  original corpus-search spec stay deferred).
- No Studio / UI work.
- No reranker, embedder, or answer-model tuning beyond defaults.
- No query-time concurrency / batching.
- No dashboards-as-code (KQL stays in this spec; provisioning is a follow-up).

## 3. State of the world (verified 2026-05-04)

- **Vector store**: `SqliteVecVectorStore`
  (`fireflyframework_agentic.vectorstores.sqlite_vec_store`). Co-resides with
  `SqliteCorpus` in the same SQLite file via the `vec0` virtual table (cosine
  distance). **Chroma was removed**; the older
  `docs/use-case-corpus-search.md` is stale on this point and is not the
  source of truth for this spec.
- **Retrieval modules**: live in the framework at
  `fireflyframework_agentic.rag.{corpus,ingest,retrieval}`.
  `examples/corpus_search/` is a thin facade
  (`agent.py`, `cli.py`, `__main__.py`, `retrieval/answerer.py`).
- **Storage layout**: a single `./kg/corpus.sqlite` (chunks + FTS5 + vec0 +
  ledger). No separate vector daemon, no Chroma directory.
- **Application code is already pure OpenTelemetry**:
  `FireflyTracer.__init__` calls `trace.get_tracer(...)` and `FireflyMetrics.__init__`
  calls `metrics.get_meter(...)`. No vendor SDK leaks into business logic; the
  vendor selection lives only inside `configure_exporters(...)`.
- **Two real gaps** surfaced during the audit:
  1. `configure_exporters` only wires `TracerProvider`. There is no
     `MeterProvider`, so every `FireflyMetrics` counter/histogram goes to the
     NoOp global meter and is dropped — this affects OTLP and AppInsights
     equally.
  2. `FireflyEvents._emit` writes through Python `logging`. There is no bridge
     to OTel logs, so events never leave the process via the OTel pipeline.
- **Drop folder**: operator-supplied multi-format corpus under `./drop/`,
  scale at validation time was 56 files spanning PDFs, DOCX, XLSX, HTML,
  and an embedded PNG (~180 MB). The folder, its sub-folders, and any
  document-level metadata remain local and are not committed (`/drop/`
  is gitignored). Operators evaluating the example against their own
  corpus produce their own non-committed test bank from
  `test_queries.template.md`.

## 4. Decisions consolidated

| # | Decision |
|---|---|
| AppInsights wiring | Real now (Javi-provisioned resource, conn string from `.env`). |
| Integration approach | **Raw exporters** via `azure-monitor-opentelemetry-exporter`, wired into providers we own (`configure_exporters`). Distro path (`configure_azure_monitor`) is **not** used — it would replace our providers and create a different code path for Azure vs non-Azure. |
| Vendor portability | App code never imports vendor exporters; switching to AWS = adding kwargs to `configure_exporters` (or running OTLP → ADOT Collector unchanged). |
| Embedding provider | `azure:text-embedding-3-small` via `EMBEDDING_BINDING_HOST` + `EMBEDDING_BINDING_API_KEY`. |
| Query LLMs | `anthropic:claude-haiku-4-5-20251001` for expansion + rerank, `anthropic:claude-sonnet-4-6` for answer. |
| Drop scope | All 56 files. Expected `load_failed` tail on the `.png` and the extension-less file is part of the test (exercises failure-monitoring path). |
| Clean slate | `rm -rf ./kg` before ingestion; no partial state from prior runs leaks in. |
| Telemetry off-ramp | Histograms recorded for every stage; spans for forensic drill-down. AppInsights uses both. |
| Privacy | Question text goes into spans (needed to triage retrieval misses). Document content, answer text, connection strings, API keys — never. Citation lists carry chunk IDs only. |
| Scope of fixes in this PR | `MeterProvider` + `LoggerProvider` setup added to `configure_exporters`; `FireflyEvents` bridged to OTel logs via `LoggingHandler`. Both fixes are vendor-neutral and ship together. |

## 5. Architecture

```
.env  ──►  examples/corpus_search/cli.py  (loads dotenv first)
            │
            ├─ configure_exporters(
            │     service_name="corpus-search",
            │     azure_monitor_connection_string=APPLICATIONINSIGHTS_CONNECTION_STRING,
            │     console=os.getenv("FIREFLY_AGENTIC_CONSOLE_TELEMETRY") == "1",
            │   ) ──► ProviderBundle
            │
            │  ┌────────────────────────────────────────────────────────┐
            │  │ TracerProvider   ── BatchSpanProcessor          ─┐     │
            │  │ MeterProvider    ── PeriodicExportingMetricReader─┼──► AzureMonitor*Exporter ──► AppInsights
            │  │ LoggerProvider   ── BatchLogRecordProcessor     ─┘     │
            │  │   ▲                                                    │
            │  │   └── opentelemetry.sdk._logs.LoggingHandler attached  │
            │  │       to "fireflyframework_agentic" parent logger      │
            │  │       (so FireflyEvents + every logger.info() flows)   │
            │  └────────────────────────────────────────────────────────┘
            ▼
        CorpusAgent
            │
            ├─ ingest_one(path)            span: rag.ingest.document
            │     ├─ markitdown.load        span: rag.ingest.load
            │     ├─ chunker.chunk          span: rag.ingest.chunk
            │     ├─ embed_with_retry       span: rag.ingest.embed
            │     │     └─ per-attempt      span: rag.ingest.embed.attempt
            │     └─ corpus.upsert + vec    span: rag.ingest.store
            │
            └─ query(question)             span: corpus_search.query
                  ├─ expander.expand        span: rag.query.expand
                  ├─ hybrid.retrieve        span: rag.query.retrieve
                  │     ├─ per-variant      span: rag.query.bm25
                  │     └─ per-variant      span: rag.query.vector
                  ├─ reranker.rerank        span: rag.query.rerank
                  └─ answerer.answer        span: corpus_search.answer
```

All persistent state in `./kg/corpus.sqlite`.

## 6. Framework changes

### 6.1 `pyproject.toml`

Add a new optional extra and roll it into `all`:

```toml
[project.optional-dependencies]
azure = [
    "azure-identity>=1.19",
    "msal>=1.31",
    "pyjwt[crypto]>=2.10.0",
    "azure-monitor-opentelemetry-exporter>=1.0.0b30",  # NEW
]
```

### 6.2 `src/fireflyframework_agentic/observability/exporters.py`

Replace the trace-only function with a three-provider version. Backwards
compatible — same kwargs still work; existing callers receive a `ProviderBundle`
instead of a bare `TracerProvider`. The legacy return type is preserved by
exposing `bundle.tracer` so `configure_exporters(...).tracer` continues to type
the same.

```python
@dataclass(frozen=True)
class ProviderBundle:
    tracer: TracerProvider
    meter: MeterProvider
    logger: LoggerProvider

def configure_exporters(
    *,
    service_name: str = "fireflyframework_agentic",
    otlp_endpoint: str | None = None,
    azure_monitor_connection_string: str | None = None,
    console: bool = False,
    metric_export_interval_ms: int = 60_000,
) -> ProviderBundle: ...
```

Behaviour:

1. Build a single `Resource` (`service.name`, `service.version`, `service.instance.id`).
2. Construct `TracerProvider`, `MeterProvider` (with one or more
   `PeriodicExportingMetricReader` instances), `LoggerProvider` from that resource.
3. For each backend kwarg present, attach the matching exporters via
   `BatchSpanProcessor` / `PeriodicExportingMetricReader` /
   `BatchLogRecordProcessor`. Multiple backends can stack (e.g. console +
   Azure Monitor for local debugging).
4. Register globally: `trace.set_tracer_provider`,
   `metrics.set_meter_provider`, `_logs.set_logger_provider`.
5. Attach `opentelemetry.sdk._logs.LoggingHandler(level=INFO,
   logger_provider=logger_provider)` to the `fireflyframework_agentic` parent
   logger so `FireflyEvents` and every `logger.info(...)` call flows through
   OTel without code changes elsewhere.
6. **Idempotent** — repeated calls with identical args do not double-register
   handlers. Tracked via a module-level guard keyed on the resource attributes
   tuple.
7. **Connection string never logged** — the success log line carries only the
   exporter name, not the value.

Azure block:

```python
if azure_monitor_connection_string:
    try:
        from azure.monitor.opentelemetry.exporter import (
            AzureMonitorTraceExporter,
            AzureMonitorMetricExporter,
            AzureMonitorLogExporter,
        )
    except ImportError:
        logger.warning(
            "azure-monitor-opentelemetry-exporter is not installed; "
            "AppInsights export disabled. Install with the [azure] extra."
        )
    else:
        cs = azure_monitor_connection_string
        tracer_provider.add_span_processor(
            BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=cs))
        )
        metric_readers.append(
            PeriodicExportingMetricReader(
                AzureMonitorMetricExporter(connection_string=cs),
                export_interval_millis=metric_export_interval_ms,
            )
        )
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(AzureMonitorLogExporter(connection_string=cs))
        )
        logger.info("Azure Monitor exporters attached")
```

### 6.3 `examples/corpus_search/cli.py`

A small `_init_telemetry()` helper called before any agent work, environment-
driven so the same code runs locally and in Azure with no flag changes:

```python
def _init_telemetry() -> None:
    load_dotenv()  # idempotent
    cs = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    otlp = os.getenv("FIREFLY_AGENTIC_OTLP_ENDPOINT")
    configure_exporters(
        service_name="corpus-search",
        azure_monitor_connection_string=cs,
        otlp_endpoint=otlp,
        console=os.getenv("FIREFLY_AGENTIC_CONSOLE_TELEMETRY") == "1",
    )
```

No new CLI flags.

### 6.4 No application code changes required

`agents/`, `rag/`, and `examples/corpus_search/agent.py` already use the OTel
global API. The provider-setup change in 6.2 is enough for them to start
emitting metrics and logs into the configured backend. Section 7 adds *new*
spans/metrics/events on top of that — those edits live in `rag/*` and
`examples/corpus_search/*`, not in agents.

## 7. Instrumentation pass

Principle: **the framework instruments framework primitives; the example
instruments the example's choreography.** Anyone using `rag.*` directly gets
the same telemetry as the example.

### 7.1 Framework-side spans + metrics (`src/fireflyframework_agentic/rag/`)

**`rag/ingest/pipeline.py::ingest_one`**
- Outer span `rag.ingest.document`. Attributes:
  `firefly.rag.doc_id`, `firefly.rag.source_path`, `firefly.rag.mime_type`,
  `firefly.rag.bytes`.
- Sub-spans for each stage: `rag.ingest.load`, `rag.ingest.hash`,
  `rag.ingest.chunk` (`chunk_count`, `total_chars`),
  `rag.ingest.reset` (`prior_chunks_deleted`),
  `rag.ingest.embed` (`chunks`, `tokens_estimated`, `attempt_count`),
  `rag.ingest.store`, `rag.ingest.ledger`.
- `Span.set_status(StatusCode.ERROR, ...)` on every error branch *before* the
  ledger upsert so the error and the terminal status are visible together.
- One `FireflyEvent` per terminal status — `rag.ingest.success`,
  `rag.ingest.skipped`, `rag.ingest.load_failed`, `rag.ingest.failed` —
  carrying `doc_id`, `source_path`, `n_chunks`, `attempt`, plus a truncated
  error string for failures.

**`rag/ingest/retry.py::embed_with_retry`**
- Span `rag.ingest.embed.attempt` per attempt.
  Attributes: `attempt_index`, `retry_after_ms` (when present).

**`rag/retrieval/expander.py::expand`**
- Span `rag.query.expand`. Attributes:
  `n_variants_requested`, `n_variants_returned`, `model`. LLM cost/tokens
  flow through the existing agent path (`UsageTracker`).

**`rag/retrieval/hybrid.py::retrieve`**
- Outer span `rag.query.retrieve`. Attributes: `queries`, `top_k_per_query`,
  `top_k_final`.
- Sub-spans `rag.query.bm25` and `rag.query.vector` per variant
  (`variant_index`, `hits`).

**`rag/retrieval/reranker.py::rerank`**
- Span `rag.query.rerank`. Attributes: `pool_size`, `top_k`,
  `kept_chunk_ids` (joined string), `dropped_hallucinated_count`. Short-
  circuit branches still emit a span with `rerank.shortcircuit=true`.

### 7.2 Example-side spans (`examples/corpus_search/`)

**`agent.py::CorpusAgent.ingest_folder`** — outer span
`corpus_search.ingest_folder`. Attributes: `folder`, `n_files`, plus per-file
rollup counts of each terminal status. Each per-file `ingest_one` span is a
child via the active context, so the trace tree shows the whole batch under
one root.

**`agent.py::CorpusAgent.query`** — outer span `corpus_search.query`
(attribute `question`) wrapping the four `rag.query.*` sub-spans plus
`corpus_search.answer` for synthesis. The `cited_sources` list is logged as
an event on the answer span (not as an attribute — too large).

**`retrieval/answerer.py::AnswerAgent.answer`** — span `corpus_search.answer`.
Attributes: `n_hits`, `model`, `citation_count`, `hallucinated_citation_count`.

### 7.3 Latency monitoring — histograms (the AppInsights-friendly side)

Spans are sampled by AppInsights at moderate volumes and adaptive sampling
kicks in earlier; histograms exported via the metrics pipeline land in
`customMetrics` un-sampled. Use spans for forensic drill-down, histograms
for SLO/regression alerts. Each histogram is recorded inside the matching
span via a small `_timed_span` helper so the same numbers always show up
in both pipelines.

```python
@asynccontextmanager
async def _timed_span(name: str, *, histogram, labels: dict[str, str]):
    start = time.perf_counter()
    with tracer.start_as_current_span(name, attributes=labels) as span:
        try:
            yield span
        finally:
            histogram.record((time.perf_counter() - start) * 1000.0, labels)
```

**Ingestion histograms (unit `ms`):**

| Metric | Labels |
|---|---|
| `firefly.rag.ingest.duration` | `stage` ∈ {`load`, `hash`, `chunk`, `reset`, `embed`, `store`, `ledger`}, `status` ∈ {`success`, `failed`} |
| `firefly.rag.ingest.document.duration` | `status`, `mime_type` |
| `firefly.rag.embed.attempt.duration` | `provider`, `outcome` ∈ {`ok`, `retry`, `fatal`} |

**Query histograms (unit `ms`):**

| Metric | Labels |
|---|---|
| `firefly.rag.query.duration` | `stage` ∈ {`expand`, `retrieve`, `rerank`, `answer`} |
| `firefly.rag.query.total.duration` | `outcome` ∈ {`answered`, `no_info`} |
| `firefly.rag.retrieve.modality.duration` | `modality` ∈ {`bm25`, `vector`}, `variant_index` |

**Counters (existing `FireflyMetrics` + new):**

- `firefly.rag.ingest.documents` (counter, label `status`).
- `firefly.rag.ingest.chunks` (counter).
- `firefly.rag.ingest.bytes` (counter).
- `firefly.rag.embed.retries` (counter, label `provider`).
- `firefly.rag.rerank.fallback` (counter, label `reason` — set to the
  exception class name; increments when the reranker raises and the
  pipeline falls back to retrieval order).

### 7.4 What is *not* instrumented

- `SqliteCorpus.bm25_search` / `SqliteVecVectorStore.search`: covered by the
  parent retrieve span. Sub-millisecond on a 56-doc corpus; deeper spans
  would be noise.
- The chunker is synchronous and short — the parent `rag.ingest.chunk` span
  is enough.
- `markitdown` internals — the whole call is the span.

### 7.5 Privacy

- **Document content**: never. Span attributes carry IDs, sizes, counts.
- **Question text**: yes, in the `corpus_search.query` span as an attribute
  (needed to triage retrieval misses against AppInsights samples). If
  redaction is later required, add a `redact_query=True` flag.
- **Answer text**: no.
- **Citations**: chunk IDs only.
- **Connection strings, API keys, `$HOME` paths**: never logged. The
  Azure-Monitor success log line carries no values.

## 8. AppInsights surfaces

### 8.1 KQL panels (committed in this spec; provisioning is a follow-up)

**Per-stage ingestion latency:**

```kql
customMetrics
| where name == "firefly.rag.ingest.duration"
| summarize p50=percentile(value,50), p95=percentile(value,95), p99=percentile(value,99)
    by bin(timestamp, 1m), tostring(customDimensions.stage)
| render timechart
```

**Per-stage query latency:** identical shape with
`name == "firefly.rag.query.duration"`.

**Failure rate:**

```kql
customMetrics
| where name == "firefly.rag.ingest.documents"
| summarize sum(value) by bin(timestamp, 5m), tostring(customDimensions.status)
| render timechart
```

`failed` and `load_failed` should be flat zero in steady state; the `.png`
and extension-less files inflate `load_failed` once during the e2e run.

**Span drill-down for a single question:**

```kql
dependencies
| where name startswith "rag.query" or name startswith "corpus_search"
| where customDimensions.["firefly.run.id"] == "<correlation-id>"
| project timestamp, name, duration, customDimensions
| order by timestamp asc
```

### 8.2 Alerts (codified here, configured in Azure portal/CLI after first run)

| Alert | Condition | Severity |
|---|---|---|
| Ingest embed p95 regression | `firefly.rag.ingest.duration{stage="embed"}` p95 over 5m > 2× the rolling 1h baseline | Warning |
| Ingest stage error spike | `firefly.rag.ingest.documents{status="failed" or status="load_failed"}` rate over 5m > 0 | Warning |
| Query end-to-end p95 | `firefly.rag.query.total.duration` p95 over 5m > 8000 ms | Warning |
| Query rerank disabled (fallback) | `firefly.rag.rerank.fallback` counter increases | Info |

The first run produces the baseline numbers that the alert thresholds quote.

## 9. Test-query methodology

### 9.1 Document sampling

The operator manually reads one representative document per top-level
category in their corpus and captures 5–10 verbatim facts into a scratch
notes file (not committed) before writing questions. The categories
themselves vary by corpus and the specific document filenames stay local.

### 9.2 Question shape — 10 questions

Lives in `examples/corpus_search/test_queries.md` — **gitignored**, so
the operator's questions and the documents they reference do not enter
version control. The committed
`examples/corpus_search/test_queries.template.md` documents the YAML
schema and recommended question mix; operators copy the template and
populate it against their own corpus.

Mix:

| # | Kind | Why it stresses the pipeline |
|---|---|---|
| 4 | Factual lookup, single doc | Baseline retrieval — if these miss, ingestion is broken. |
| 2 | Synthesis across 2+ docs | Tests RRF — answer integrates chunks the reranker pulled from different sources. |
| 1 | Date / number | Tests BM25 over morphology + porter stemmer interaction with numerals. |
| 1 | Cross-language phrasing (question one language, source another) | Forces vector retrieval to do real work; BM25 alone cannot bridge across language. |
| 1 | Tabular fact (XLSX) | Tests markitdown's XLSX→markdown extraction quality. |
| 1 | Negative control (fact NOT in corpus) | Must produce "I don't have enough information." with empty `cited_sources`. If it hallucinates here, the whole pipeline's grounding is broken. |

### 9.3 Pass criteria

For each non-negative question:
1. **Citation grounding**: at least one `Answer.cited_sources[*].source_path`
   matches an entry in `expected_source_paths`. Off-by-one (right doc, wrong
   chunk) is a soft fail.
2. **Factual claim**: a hand-listed must-mention key (substring/regex check;
   no LLM-as-judge in V1 — the human reviewer scores).
3. **No hallucinated citations**: every chunk_id in the answer text matches a
   chunk_id in `cited_sources`. (The pipeline already drops these post-call,
   so this should be free.)

For the negative control:
1. Answer must contain "don't have enough information" (or equivalent).
2. `cited_sources` must be empty.

### 9.4 Per-query record

| field | source |
|---|---|
| `question_id`, `question` | `test_queries.md` |
| `answer_text`, `cited_sources[]` | `Answer` object |
| `latency_ms` total + per-stage | `firefly.rag.query.duration` |
| `cost_usd` | `default_usage_tracker.get_summary_for_correlation(query_id)` |
| `n_variants`, `n_candidates_pre_rerank`, `n_top_k` | span attributes |
| `passed` | manual review against `pass_criteria` |
| `notes` | freeform — retrieval surprises, mistranslated terms, etc. |

### 9.5 Fairness guardrails

- The 6 read files are also in the corpus — no fabricated questions about
  excluded content.
- Question wording is *not* taken verbatim from the doc; otherwise we test
  exact-match retrieval, not the system.
- Question batch is committed *before* the query run, so answers cannot
  influence questions.

## 10. Run procedure

### 10.1 Phase gates

Each phase ends with a checkpoint. No "best effort, keep going".

| Phase | Gate condition |
|---|---|
| 0. Branch + draft PR | Branch + draft PR exist. **Already done.** |
| 1. Framework changes (`exporters.py` rewrite, `pyproject.toml` extra) | `uv sync --extra azure` succeeds; new unit tests for `configure_exporters` pass; the existing 1383+ test suite stays green. |
| 2. Instrumentation pass on `rag/*` and `examples/corpus_search/*` | `uv run pytest tests/rag/ tests/examples/corpus_search/` green. New tests assert spans/metrics emitted (using `InMemorySpanExporter` + `InMemoryMetricReader`). |
| 3. Telemetry init in `cli.py` + smoke test | `python -m examples.corpus_search query "ping"` against an empty `./kg` produces the canned no-info answer **and** a span tree visible in AppInsights `dependencies` blade within 60s. |
| 4. Test query bank committed | `examples/corpus_search/test_queries.md` reviewed by Javi. |
| 5. Clean-slate ingestion | All 56 files processed; ledger states summed; no `ingest_one` raised an unhandled exception. |
| 6. Query battery | All 10 questions executed end-to-end; report drafted. |
| 7. Sign-off | Javi reviews the report and the AppInsights baseline dashboards. |

### 10.2 Pre-flight checks

A small `--preflight` flag on the CLI that fails fast on any of:

```
[✓] APPLICATIONINSIGHTS_CONNECTION_STRING is set (length sanity check, never logged)
[✓] EMBEDDING_BINDING_HOST and EMBEDDING_BINDING_API_KEY are set
[✓] ANTHROPIC_API_KEY is set (only required for query phase, but verified up front)
[✓] ./drop exists and contains at least one file
[✓] ./kg is empty OR --force-clean was passed
[✓] sqlite-vec extension loads (the same load happens at first ingest call; failing early is friendlier)
[✓] One outbound HTTPS reachability ping with a tiny test span flushed and confirmed
```

### 10.3 Clean slate

`rm -rf ./kg` (after `--force-clean` confirmation if `./kg` exists). The
directory is recreated lazily by `CorpusAgent._ensure_corpus_ready()`.

### 10.4 Live monitoring during ingestion

Two surfaces watched in parallel:

**Local logs** — `cli.py ingest --verbose` prints per-file ledger status. We
watch stderr for:
- Lines containing `ERROR` (these go to AppInsights too but stderr is faster).
- Lines containing `embed_with_retry: attempt N` where N > 2 (signals the
  embedding endpoint is throttling; may need to slow concurrency).

**AppInsights Live Metrics + Failures blade** —
- Live Metrics shows `firefly.rag.ingest.documents` rate,
  `firefly.rag.ingest.duration{stage="embed"}` p95, and incoming exception
  count.
- Failures blade lists any span with `StatusCode.ERROR`. Clicking through
  gives `firefly.rag.doc_id` + source path.

### 10.5 What counts as an "issue worth reporting back" during the run

Reported to Javi as it happens, not at the end:

| Class | Examples | Action |
|---|---|---|
| **Hard failure** | unhandled exception in `ingest_one`; AppInsights export drops to zero mid-run; embed retries exhausted on >5 files | Stop the run, capture state, report. |
| **Quality regression** | `firefly.rag.ingest.duration{stage="embed"}` p95 > 5s sustained; PDF that loaded but produced 0 chunks | Report after the phase, do not stop. |
| **Expected** | `.png` and extension-less file in `load_failed` | Note in report, do not interrupt. |

If the `failed` or `load_failed` count exceeds ~10% of files, we pause and
triage before the query phase.

### 10.6 Query battery execution

Sequential, not concurrent — answers are easier to inspect, and the system
has no concurrency story for query yet:

```
for q in test_queries.md:
    correlation_id = "qrun-{date}-{q.id}"
    set OTel baggage `firefly.run.id` = correlation_id
    answer = await agent.query(q.question, top_k=5)
    record row in run report:
        question, answer.text, [c.source_path for c in answer.cited_sources],
        latency_ms (from histogram + span), cost_usd (from UsageTracker for correlation_id)
    show side-by-side to Javi: question, answer, expected_source_paths, actual cited paths
    Javi marks pass/fail/soft-fail in the report
```

The `correlation_id` baggage is what lets the AppInsights post-mortem KQL
filter to a single question's full span tree.

## 11. Deliverables

1. `azure-monitor-opentelemetry-exporter` wired into `configure_exporters`
   (under the consolidated `[azure]` extra alongside the AAD-auth deps),
   `MeterProvider` and
   `LoggerProvider` setup, `LoggingHandler` bridge.
2. Instrumentation pass on `rag/{ingest,retrieval}/*` and
   `examples/corpus_search/{agent,retrieval/answerer}.py`.
3. `examples/corpus_search/cli.py` calls `_init_telemetry()` before any agent
   work; reads `APPLICATIONINSIGHTS_CONNECTION_STRING` from env / `.env`.
4. `examples/corpus_search/test_queries.md` — 10 hand-curated questions with
   `expected_source_paths` and `pass_criteria`.
5. `docs/superpowers/specs/2026-05-04-corpus-search-e2e-run-report.md` —
   the post-run report, sign-off block, and the perf baseline that future
   regressions compare against. Sections:
   1. Inputs (file count, total bytes, embedding model, query models,
      AppInsights resource id without conn string).
   2. Ingestion summary (table per terminal status, total elapsed time,
      total embedding tokens + cost).
   3. Per-file ledger excerpt — non-`success` rows verbatim with the
      captured error string.
   4. Latency baseline table (the histograms from §7.3).
   5. Query results table — one row per question, pass/fail, link to the
      AppInsights KQL fetching the corresponding span tree.
   6. Issues found (both classes from §10.5) with proposed follow-up tickets.
   7. Sign-off block.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Embedding cost on 180MB | Pre-flight estimate before kicking off; `text-embedding-3-small` is ~$0.02/1M tokens so even worst case is single-digit USD. |
| `markitdown` PDF quality on scanned/image-heavy government documents | Expected `load_failed` tail; the `.png` and extension-less file are deliberate failure-monitoring tests. |
| Telemetry double-init (CLI calls `configure_exporters`, framework imports could re-call) | Idempotent guard in `configure_exporters` keyed on the resource attributes tuple. |
| Connection-string leakage | `.env` is gitignored; `configure_exporters` success line carries no value; pre-flight check verifies presence by length only. |
| AppInsights sampling hides regressions | Histograms are exported un-sampled via the metrics pipeline; alert thresholds reference histograms, not span counts. |
| Run report drift if perf baseline isn't reviewed | Sign-off block in the report makes the baseline an explicit Javi-approved contract; future PRs that change p95 ≥ 50% must update the baseline. |

## 13. Out of scope (named so they don't sneak in)

- Query-time concurrency / batching.
- Dashboards-as-code (`bicep`/`azure-cli` to provision the AppInsights workbook).
  KQL stays in this spec; provisioning is a follow-up.
- Reranker tuning, alternative embedders, alternative answer models.
- Tracing into `markitdown` internals.
- Auto-redaction of question text in spans.

## 14. Next-step skill to invoke (after sign-off)

`superpowers:writing-plans` → produces an implementation plan that
`superpowers:executing-plans` (or `superpowers:subagent-driven-development`)
will execute against the phase gates in §10.1.
