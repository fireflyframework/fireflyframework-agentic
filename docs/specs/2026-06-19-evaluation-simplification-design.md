# Evaluation Package Simplification

**Date:** 2026-06-19
**Branch:** `feat/evaluation-framework`

## Problem

The first migration of evaluation code into `fireflyframework_agentic/evaluation/` brought over too much infrastructure alongside the metrics: a CLI (`flyeval`), a five-gate framework (G1–G5), a registry/corpus/matcher pipeline, a scorecard renderer, champion persistence, run-config snapshotting, and statistical helpers. The actual value — the LLM judge metric functions — was buried under 10 supporting files.

The goal of this design is to gut that infrastructure and keep only the measurement code.

## What We Keep

All metric functions from both evaluation systems:

**Flyradar G4 (from `judge.py`):**
- `[D]` deterministic: `source_coverage`, `excerpt_fill_rate`
- `[E]` embedding-based: `semantic_recovery`
- `[J]` LLM judge: `faithfulness`, `numeric_temporal_fidelity`, `citation_relevance`, `nc_semantic_precision`, `fabricated_entity`, `contradiction`, `open_gap`, `actionability`, `severity_calibration`, `answer_relevancy`, `surface_deduplication`, `comparative_vs_champion` (champion passed as optional parameter — no persistence)

**Flycanon (from `llm_eval.py`):**
- Custom: `contains_answer`, `addresses_question` (median of N LLM calls per item)
- RAGAS: `answer_correctness`, `answer_relevancy`, `faithfulness`, `context_recall`, `context_precision`

**Retrieval (already in `lab/retrieval_metrics.py`):** unchanged.

## What We Delete

From `fireflyframework_agentic/evaluation/`:

| File | Reason |
|---|---|
| `cli.py` | `flyeval` CLI — experiment orchestration, not measurement |
| `gates.py` | G1–G5 gate framework — pipeline infrastructure |
| `corpus.py` | Corpus loader — pipeline infrastructure |
| `registry.py` | Registry management — pipeline infrastructure |
| `matcher.py` | Anchored matching utilities — pipeline infrastructure |
| `scorecard.py` | Scorecard renderer — reporting, not measurement |
| `run_config_snapshot.py` | Run config capture — pipeline infrastructure |
| `models.py` | `EvalConfig`, `GateVerdict` — only used by deleted files |
| `stats.py` | `aa_band`, `aggregate_grounding` — only used by deleted files |
| `champion.py` | Champion persistence — `comparative_vs_champion` metric accepts champion data as a parameter instead |

Tests for deleted modules are also removed: `test_champion.py`, `test_gates.py`, `test_matcher.py`, `test_stats.py`.

## Target Package Layout

```
fireflyframework_agentic/evaluation/
├── __init__.py       # exports: EvalContext, AdvisoryReport, all metric functions
├── judge_client.py   # JudgeClient — async LLM scoring client (httpx.AsyncClient)
└── judge.py          # ALL metric functions + EvalContext + AdvisoryReport
```

Three files. No CLI. No gates. No registry.

## Unified Interface

Every metric — flyradar [D], [E], [J] and flycanon custom and RAGAS — shares the same async signature:

```python
async def metric_name(item: dict, ctx: EvalContext) -> float | None
```

`item` is a plain dict with a normalized schema:

```python
{
    "question": str,
    "answer": str,
    "reference": str,
    "contexts": list[str],
    # flyradar extras (optional):
    "sources": list[str],
    "excerpts": list[str],
    # champion data (optional, for comparative_vs_champion):
    "champion_answer": str | None,
}
```

`EvalContext` is a Pydantic model carrying all dependencies:

```python
from pydantic import BaseModel, ConfigDict

class EvalContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: JudgeClient                  # async LLM call client
    embedder: OllamaEmbedder | None = None  # for [E] metrics and RAGAS embeddings
    runs: int = 3                        # flycanon multi-run median
```

No `ragas_llm` / `ragas_embeddings` — RAGAS metrics wrap `ctx.client` and `ctx.embedder` in LangChain adapters internally. Callers see one client, one embedder.

A composable type alias:

```python
Metric = Callable[[dict, EvalContext], Awaitable[float | None]]
```

Example usage:

```python
ctx = EvalContext(client=JudgeClient(model="claude-sonnet-4-6", api_key=KEY))
metrics: list[Metric] = [faithfulness, contains_answer, answer_correctness]
scores = await asyncio.gather(*[m(item, ctx) for m in metrics])
```

## `judge_client.py`

Contains only `JudgeClient` — a thin async HTTP client for Anthropic/OpenAI/Ollama scoring calls:

```python
class JudgeClient:
    async def chat_json(self, system: str, user: str, max_tokens: int = 200) -> dict: ...
```

Uses `httpx.AsyncClient`. Handles 429/5xx retry with `Retry-After` parsing. No embedding logic — embeddings come from `fireflyframework_agentic/embeddings/providers/ollama.py` (existing async `OllamaEmbedder`).

`cosine_similarity` is imported from `fireflyframework_agentic/embeddings/similarity.py` — no duplication.

## Dependencies (`pyproject.toml`)

`evaluation` optional extra changes:
- **Remove:** `scipy` (was only used by the deleted `stats.py`)
- **Add:** `ragas`, `langchain-anthropic`, `langchain-ollama`
- **Keep:** `numpy`

No changes to `embeddings/` — existing async `OllamaEmbedder` used as-is.

## Testing

| File | Status |
|---|---|
| `tests/unit/evaluation/test_judge.py` | New — unit tests per metric (mocked `EvalContext`) |
| `tests/unit/lab/test_retrieval_metrics.py` | Unchanged |
| `tests/unit/evaluation/test_champion.py` | Deleted |
| `tests/unit/evaluation/test_gates.py` | Deleted |
| `tests/unit/evaluation/test_matcher.py` | Deleted |
| `tests/unit/evaluation/test_stats.py` | Deleted |

## Implementation Order

1. Delete the 10 infrastructure files and their tests.
2. Rewrite `judge_client.py` — async `JudgeClient` with `httpx.AsyncClient`.
3. Rewrite `judge.py` — `EvalContext`, `AdvisoryReport`, all metric functions ported to async with unified `(item, ctx)` signature.
4. Port flycanon custom metrics (`contains_answer`, `addresses_question`) into `judge.py`.
5. Port RAGAS metrics into `judge.py` (wrap `ctx.client`/`ctx.embedder` in LangChain adapters internally).
6. Update `__init__.py` exports.
7. Update `pyproject.toml` extras.
8. Write unit tests for the new metric functions.
9. Update `docs/evaluation.md`.
10. Update CI `pr-gate.yml` if extras changed.
