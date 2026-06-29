# Evaluation Guide

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The Evaluation subpackage provides **metrics for assessing LLM and pipeline outputs**:
LLM-as-judge metrics (faithfulness, relevancy, answer correctness, …) and deterministic
information-retrieval metrics (recall@k, nDCG, MRR, …). Every metric is a plain function
you call directly and combine however your harness needs — there is no gate, verdict, or
promotion machinery to opt into.

---

## Installation

The evaluation subpackage needs `numpy` for the embedding path and `ragas` (plus its
LangChain providers) for the RAGAS metrics. Install the optional extra:

```bash
pip install "fireflyframework-agentic[evaluation]"
```

Everything except the RAGAS metrics works without `ragas` installed; the RAGAS functions
import it lazily and only fail if you call them without the extra.

---

## Two metric families

| Family | Module | Needs an LLM? | Use it to evaluate… |
|--------|--------|---------------|---------------------|
| **LLM-as-judge** | `evaluation.judge` | Most metrics yes (a few are deterministic/embedding) | The semantic quality of a model's answers and reports — faithfulness, relevancy, correctness, hallucination. |
| **Retrieval** | `evaluation.retrieval_metrics` | No (pure functions, no network) | The ranked retrieval that feeds the LLM — recall@k, precision@k, MRR, MAP, nDCG, latency. |

Both are re-exported from `fireflyframework_agentic.evaluation`.

---

## LLM-as-judge metrics

Each judge metric is an **async function** with the same signature:

```python
async def metric(item: dict, ctx: EvalContext) -> dict | float | None
```

- `item` — a plain dict of the output under evaluation (see schema below).
- `ctx` — an `EvalContext` carrying the judge client, optional embedder, and run count.
- The return is either a small summary dict, a single float, or `None` when the metric
  cannot run (e.g. an embedding metric with no embedder, or a missing field).

### EvalContext and JudgeClient

```python
from fireflyframework_agentic.evaluation import EvalContext, JudgeClient

ctx = EvalContext(
    client=JudgeClient("anthropic:claude-haiku-4-5-20251001"),
    runs=3,          # metrics that repeat use the median of this many calls
    embedder=None,   # optional OllamaEmbedder, required only by semantic_recovery
)
```

`JudgeClient` is an async multi-provider chat client. The model spec is
`"<provider>:<model>"`, where provider is one of `anthropic`, `openai`, `azure`, `ollama`.
Temperature is pinned to `0.0` for stable verdicts, and API keys are read lazily from the
environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_*`, `OLLAMA_HOST`) — so
constructing a client never requires a secret.

### Item schema

The judge metrics read whichever keys they need and ignore the rest, so one `item` dict can
serve many metrics.

**RAG / Q&A items** (single answer under test):

```python
item = {
    "question":  "What is the boiling point of water at sea level?",
    "answer":    "Water boils at 100 degrees Celsius at sea level.",
    "reference": "Water boils at 100 °C at standard atmospheric pressure.",
    "contexts":  ["...retrieved passage...", "..."],   # used by RAGAS metrics
}
```

**Report / discovery items** (a structured pipeline output):

```python
item = {
    "findings":        [{"id": ..., "title": ..., "description": ..., "severity": ...,
                         "evidence_refs": [{"evidence_id": ...}], ...}],
    "evidence_index":  [{"id": ..., "locator": "doc.md#L1", "excerpt": "..."}],
    "process_graph":   {"processes": [{"name": ..., "activities": [...], "decisions": [...]}]},
    "proposed_actions": [{"title": ..., "finding_id": ..., "expected_savings_fte": ...}],
    "workspace":       {"name": ..., "description": ...},
    "nc_items":        [{"id": ..., "description": "a statement that is factually false"}],
    "lexical_missed_ids": ["..."],   # ids the lexical pass missed (semantic_recovery)
    "champion":        { ... another item ... },   # baseline for comparative_vs_champion
}
```

### Quick start — scoring Q&A pairs

```python
import asyncio
from fireflyframework_agentic.evaluation import (
    EvalContext, JudgeClient, contains_answer, addresses_question,
)

item = {
    "question":  "Who wrote Romeo and Juliet?",
    "reference": "Romeo and Juliet was written by William Shakespeare around 1594–1596.",
    "answer":    "It was written by Shakespeare.",
}

async def main():
    ctx = EvalContext(client=JudgeClient("anthropic:claude-haiku-4-5-20251001"), runs=3)
    contains   = await contains_answer(item, ctx)     # 0.0–1.0
    addresses  = await addresses_question(item, ctx)  # 0.0–1.0
    print(contains, addresses)

asyncio.run(main())
```

See `examples/llm_eval_example.py` for a runnable version that scores a list of items
(built-in sample data or a JSONL file) and prints a table.

### Metric catalog

**Deterministic** — no LLM call, always available:

| Metric | Returns | Measures |
|--------|---------|----------|
| `source_coverage` | `{cited, total, orphaned}` | Distinct source documents cited by ≥1 finding vs. all sources; `orphaned` lists uncited stems. |
| `excerpt_fill_rate` | `{populated, total}` | Fraction of `evidence_index` entries that carry a non-empty excerpt. |

**Embedding** — requires `ctx.embedder`:

| Metric | Returns | Measures |
|--------|---------|----------|
| `semantic_recovery` | `{lexical_recall, recovered_recall, recovered, tau, scored_denominator}` or `None` | Context-recall: recovers lexically-missed items via embedding similarity above `tau` (default 0.70). Returns `None` when no embedder is set. |

**LLM-as-judge** — requires `ctx.client`:

| Metric | Returns | Measures |
|--------|---------|----------|
| `faithfulness` | `{supported, total, unsupported_ids}` | Does each finding's cited evidence entail its claim? |
| `numeric_temporal_fidelity` | `{mismatches, count}` | Numbers/dates asserted in a finding that don't match its evidence. |
| `citation_relevance` | `{precision, relevant, total}` | Context precision: fraction of cited passages actually relevant to the claim. |
| `nc_semantic_precision` | `{asserted, total, asserted_ids}` | How many negative-control falsehoods (`nc_items`) the output asserts or endorses. |
| `fabricated_entity` | `{count, entities}` | Systems/orgs/metrics named in the output but absent from the corpus. |
| `contradiction` | `{count, pairs}` | Internally contradictory finding pairs. |
| `open_gap` | `{gap}` | G-Eval open probe: the most important issue the output missed (free-text, no score). |
| `actionability` | `{score, rated}` | Average 0–1 rating of whether proposed actions are specific, quantified, and linked. |
| `severity_calibration` | `{miscalibrated, total, verdicts}` | Whether each finding's stated severity matches its evidence (under/over/calibrated). |
| `answer_relevancy` | `{score}` | Does the output address the stated workspace intention? |
| `surface_deduplication` | `{distinct, redundant, total, distinct_rate, redundant_pairs}` | Fraction of near-duplicate process-graph nodes that are genuinely distinct. |
| `comparative_vs_champion` | `{candidate, champion, more_consistent}` or `None` | Pairwise five-axis review of candidate vs. `item["champion"]`. `None` if no champion. |

**RAG Q&A** — requires `ctx.client`; repeats `ctx.runs` times and returns the median:

| Metric | Returns | Measures |
|--------|---------|----------|
| `contains_answer` | `float` or `None` | Does the answer contain the correct information from the reference? |
| `addresses_question` | `float` or `None` | Does the answer directly address what the question asks? |

**RAGAS** — requires the `ragas` extra and `ctx.client` (plus an embedder for some):

| Metric | Returns | Measures |
|--------|---------|----------|
| `answer_correctness` | `float` or `None` | Semantic F1 of the answer against the reference. |
| `ragas_faithfulness` | `float` or `None` | Answer grounded in the retrieved `contexts`. |
| `context_recall` | `float` or `None` | Reference coverage by the retrieved `contexts`. |
| `context_precision` | `float` or `None` | Retrieved `contexts` relevant to the question. |

### Running every metric at once

`run_judge()` runs all metrics concurrently and collects them into an `AdvisoryReport`. It
is best-effort and never raises — any metric that fails is recorded in `report.errors`
instead of propagating.

```python
import asyncio
from fireflyframework_agentic.evaluation import run_judge, EvalContext, JudgeClient

async def main():
    ctx = EvalContext(client=JudgeClient("anthropic:claude-haiku-4-5-20251001"), runs=3)
    report = await run_judge(item, ctx, pipeline_model="anthropic:claude-sonnet-4-6")
    print(report.metrics)   # {metric_name: result, ...}
    print(report.errors)    # ["metric: ExceptionType: message", ...]

asyncio.run(main())
```

`AdvisoryReport` fields:

| Field | Type | Description |
|-------|------|-------------|
| `judge_model` | `str` | The judge model spec used. |
| `same_provider_caveat` | `bool` | `True` when the judge and the evaluated pipeline share a provider (self-grading risk). |
| `calibrated` | `bool` | Reserved; always `False` for now. |
| `runs` | `int` | Judge runs per repeated metric. |
| `metrics` | `dict` | Per-metric results, keyed by metric name. |
| `details` | `dict` | Supporting context (counts, ids). |
| `errors` | `list[str]` | Per-metric failures captured best-effort. |

---

## Retrieval metrics

Deterministic IR metrics over ranked retrieval results — no LLM and no network, the same
design as scikit-learn or MS MARCO evaluation scripts. Each is a plain function over a list
of result rows.

### Row schema

```python
results = [
    {
        "retrieved": [{"rank": 1, "source_id": "SOP-002.md", "is_gold": True},
                      {"rank": 2, "source_id": "SOP-001.md", "is_gold": False}],
        "gold": ["SOP-002.md"],          # gold source identifiers
        # optional:
        "no_answer": False,              # model refused / produced no answer
        "answer": "...",                 # used for no_answer detection if no_answer absent
        "citations": [{"is_gold": True}],
        "search_ms": 42.0,
        "answer_ms": 310.0,
    },
]
```

`rank` is 1-based (rank 1 is the top hit). Duplicate sources are de-duplicated by
`source_id`, keeping the best-ranked chunk.

### Metric catalog

| Function | Signature | Measures |
|----------|-----------|----------|
| `hit_at_k` | `(results, k) -> float` | Fraction of queries with ≥1 gold document in top-k. |
| `recall_at_k` | `(results, k) -> float` | Mean fraction of gold documents found in top-k. |
| `precision_at_k` | `(results, k) -> float` | Mean fraction of top-k results that are gold. |
| `mrr` | `(results, k=10) -> float` | Mean reciprocal rank of the first gold hit. |
| `map_score` | `(results, k=10) -> float` | Mean average precision at k. |
| `ndcg` | `(results, k=10) -> float` | Mean normalised discounted cumulative gain at k. |
| `no_answer_rate` | `(results) -> float \| None` | Fraction of queries with no answer. `None` if no results. |
| `citation_precision` | `(results) -> float \| None` | Precision of in-answer citations vs. the gold set. `None` if no citations. |
| `mean_latency_ms` | `(results, field) -> float \| None` | Mean latency for `"search_ms"` or `"answer_ms"`. `None` if absent. |

### Example

```python
from fireflyframework_agentic.evaluation import recall_at_k, ndcg, mrr

print(f"Recall@5: {recall_at_k(results, 5):.3f}")
print(f"nDCG@10:  {ndcg(results):.3f}")
print(f"MRR@10:   {mrr(results):.3f}")
```

---

## Reference

All symbols below are importable from `fireflyframework_agentic.evaluation`.

### Core types

| Symbol | Kind | Description |
|--------|------|-------------|
| `EvalContext` | Pydantic model | Carries `client`, optional `embedder`, and `runs` for the judge metrics. |
| `JudgeClient` | Class | Async multi-provider (`anthropic`/`openai`/`azure`/`ollama`) JSON chat client. |
| `AdvisoryReport` | Dataclass | Aggregated `run_judge` output: `metrics`, `errors`, and run metadata. |
| `Metric` | Type alias | `Callable[[dict, EvalContext], Awaitable[dict \| float \| None]]`. |
| `parse_model` | Function | Split `"provider:model"` into `(provider, model)`. |
| `same_provider` | Function | `True` if two model specs share a known provider prefix. |

### Judge metrics

`source_coverage`, `excerpt_fill_rate`, `semantic_recovery`, `faithfulness`,
`numeric_temporal_fidelity`, `citation_relevance`, `nc_semantic_precision`,
`fabricated_entity`, `contradiction`, `open_gap`, `actionability`,
`severity_calibration`, `answer_relevancy`, `surface_deduplication`,
`comparative_vs_champion`, `contains_answer`, `addresses_question`,
`answer_correctness`, `ragas_faithfulness`, `context_recall`, `context_precision`,
and the orchestrator `run_judge`.

### Retrieval metrics

`hit_at_k`, `recall_at_k`, `precision_at_k`, `mrr`, `map_score`, `ndcg`,
`no_answer_rate`, `citation_precision`, `mean_latency_ms`.
