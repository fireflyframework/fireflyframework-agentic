# corpus_search benchmark

A small synthetic corpus + a labelled query suite for measuring retrieval quality
of the `corpus_search` agent. Lets us evolve the pipeline (chunking, FTS5
tokenizer, RRF parameters, reranker, expansion) with concrete metrics rather
than vibes.

## What it tests

- **Hit@1 / Hit@5 / Hit@20** — was at least one ground-truth-relevant doc in the top-K?
- **MRR** (Mean Reciprocal Rank) — how high did the first relevant doc rank?
- **Doc-match rate** — fraction of queries where any expected doc appeared in the candidates.
- **Substring-match rate** — fraction of queries where any expected substring appeared in retrieved chunk content (a stricter "did we actually find the answer" signal).
- **Correct-rejection rate** — for out-of-corpus queries (e.g. "Who is the CEO of Microsoft?"), did the retriever return nothing high-confidence?

## What it doesn't test

- Answer-agent quality (Sonnet's synthesis): non-deterministic, expensive, and
  measuring "is this answer correct" requires either human eval or another LLM
  judge — both out of scope here. The benchmark stops at retrieval.

## Synthetic corpus (`corpus/`)

10 fictional documents about "Acme Corp" — a made-up B2B SaaS company.
Each doc is loaded with specific seeded facts that the queries verify. Mix
of English, Spanish, and Portuguese to cover multilingual retrieval.

| File | Topic | Language |
|---|---|---|
| `01_company_overview.md` | CEO, founding, leadership, HQ | English |
| `02_q4_financials.md` | Q4 2025 revenue, regional breakdown | English |
| `03_engineering_roadmap.md` | Rust migration, API v3, Postgres 17 | English |
| `04_privacy_policy_es.md` | DPO, data retention, GDPR/LGPD | Spanish |
| `05_security_standards.md` | ISO 27001, SOC 2, MFA, encryption | English |
| `06_meeting_minutes_q1.md` | Series C, layoffs, Madrid office | English |
| `07_product_specs.md` | API rate limits, SLA, file sizes | English |
| `08_employee_handbook.md` | Vacation, 401k, parental leave | English |
| `09_press_release.md` | Series C announcement, Sequoia | English |
| `10_glossary_pt.md` | Technical terminology | Portuguese |

## Query suite (`queries.json`)

20 queries spanning factual lookup, cross-document synthesis, multilingual,
cross-language (English query against Spanish corpus, etc.), and negative
(out-of-corpus) cases. Each carries:

- `expected_doc_basenames` — which docs should be retrieved
- `expected_substrings` — which strings should appear in retrieved chunks
- `category` — for breakdown reporting
- `language` — to track multilingual performance
- `negative: true` — for queries with no expected answer

## Running

### Mechanics mode (CI-friendly, no API)

Deterministic SHA-256-hash embeddings, in-memory vector store, no LLM. Tests
the pipeline mechanics. Vector signal is essentially noise here, so metrics
mostly reflect BM25 + sanitisation quality.

```bash
uv run python -m examples.corpus_search.benchmark.runner --mode mechanics
```

### Real mode (Azure OpenAI embeddings)

Requires `EMBEDDING_BINDING_HOST` + `EMBEDDING_BINDING_API_KEY`.

```bash
uv run python -m examples.corpus_search.benchmark.runner --mode real
```

### Real mode + reranker

Adds the listwise Haiku reranker between retrieval and metrics. Requires
`ANTHROPIC_API_KEY` too.

```bash
uv run python -m examples.corpus_search.benchmark.runner --mode real --rerank
```

### Compare runs

```bash
uv run python -m examples.corpus_search.benchmark.runner --mode real --json runs/baseline.json
# ... change something ...
uv run python -m examples.corpus_search.benchmark.runner --mode real --json runs/experiment.json

diff <(jq '.queries[] | {id,hit_at_5,rank_of_first_match}' runs/baseline.json) \
     <(jq '.queries[] | {id,hit_at_5,rank_of_first_match}' runs/experiment.json)
```

## Adding queries

1. Add a doc to `corpus/` with the new fact.
2. Add a query entry to `queries.json` with `expected_doc_basenames` /
   `expected_substrings`.
3. Re-run the benchmark.

## Adding new metrics

`runner.py` is the single source. `QueryResult` and `BenchmarkResult` carry
the schema; `_aggregate` rolls up. The runner is deliberately small so
extending it is a matter of adding one or two methods.

## Interpreting results

- **Hit@5 ≥ 80%** is a reasonable bar for retrieval over this corpus shape.
- **Substring match < doc-match**: the retriever found the right doc but not
  the right chunk. Try smaller `chunk_size` or larger overlap.
- **MRR < 0.6**: relevant docs are present but ranking is poor. The
  reranker should help; also worth inspecting BM25 vs vector contributions
  individually.
- **Correct-rejection low**: the retriever is over-eager. RRF + sanitisation
  should yield empty hits for out-of-corpus terms; if it doesn't, the
  reranker (with its quality-over-quantity prompt) is the right place to
  filter.
