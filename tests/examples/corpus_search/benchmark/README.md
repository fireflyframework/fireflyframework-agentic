# corpus_search benchmark

A small synthetic corpus + a labelled query suite for measuring retrieval quality
of the `corpus_search` agent. Evolve the pipeline (chunking, FTS5 tokenizer, RRF
parameters, reranker, expansion) with concrete numbers rather than intuition.

## What it measures

| Metric | Definition |
|---|---|
| **Hit@1 / Hit@5 / Hit@20** | Was a ground-truth doc in the top-K candidates (pre-rerank)? |
| **MRR** | Mean Reciprocal Rank of the first matching candidate (pre-rerank). |
| **Doc-match rate** | Fraction of queries where any expected doc appeared anywhere in the candidate pool. |
| **Substring match** | Fraction of queries where an expected substring appeared in the post-rerank top-5. Strictest "did we actually surface the answer?" signal. |
| **Correct-rejection rate** | For negative (out-of-corpus) queries: fraction where nothing ranked in the pool. |

**Note on pre-rerank vs post-rerank:** `rank`, `Hit@K`, and MRR are computed
from the full candidate pool *before* the reranker fires. `substring_match` and
`retrieved_doc_basenames` in the trace are from the *post-rerank* top-5. This
is intentional — it lets you separate retriever quality from reranker quality.
When `--expand` is on, rank is still pre-rerank but now reflects the full
expanded+fused pool.

---

## Run modes

Five configurations, each isolating a different component. Run them in order
to build a ladder of baselines.

### 1. Mechanics (CI-friendly, no API keys)

Deterministic SHA-256 hash embeddings + in-memory vector store. Vector signal
is noise; metrics primarily reflect BM25 quality. Use this in CI.

```bash
uv run python tests/examples/corpus_search/benchmark/runner.py --mode mechanics
```

### 2. Real embeddings (Azure OpenAI)

Requires `EMBEDDING_BINDING_HOST` + `EMBEDDING_BINDING_API_KEY`.

```bash
uv run python tests/examples/corpus_search/benchmark/runner.py --mode real
```

Isolates raw hybrid retrieval (BM25 + semantic vectors, no expansion, no rerank).

### 3. Real + reranker

Adds the listwise Haiku reranker. Requires `ANTHROPIC_API_KEY`.

```bash
uv run python tests/examples/corpus_search/benchmark/runner.py --mode real --rerank
```

`substring_match` now reflects reranker quality; `Hit@K` / MRR still measure
the retriever. The gap between Hit@5 (pre-rerank) and substring_match
(post-rerank) shows how much rescue work the reranker is doing.

### 4. Real + expansion (HyDE)

Adds query expansion: paraphrase variants + one HyDE (Hypothetical Document
Embedding) passage per query. Requires `ANTHROPIC_API_KEY`.

```bash
uv run python tests/examples/corpus_search/benchmark/runner.py --mode real --expand
```

HyDE generates a short passage written *as if* it were an excerpt from the
answer document, then embeds it. This fixes queries where the question phrasing
has zero keyword overlap with the document (e.g. "Who runs the show?"). The
failure trace for failing queries now shows every issued sub-query, including
the hyde passage, so you can inspect what the expander generated.

### 5. Full pipeline (expansion + reranker)

```bash
uv run python tests/examples/corpus_search/benchmark/runner.py --mode real --expand --rerank
```

Matches production query behaviour exactly.

---

## Comparing configurations

Save each run to a JSON file with `--json`, then diff or summarise.

```bash
# Record baselines
uv run python tests/examples/corpus_search/benchmark/runner.py \
    --mode real --json runs/01_real.json

uv run python tests/examples/corpus_search/benchmark/runner.py \
    --mode real --rerank --json runs/02_real_rerank.json

uv run python tests/examples/corpus_search/benchmark/runner.py \
    --mode real --expand --json runs/03_real_expand.json

uv run python tests/examples/corpus_search/benchmark/runner.py \
    --mode real --expand --rerank --json runs/04_real_expand_rerank.json
```

### Quick summary across all runs

```bash
for f in runs/*.json; do
  printf "%-40s  hit@5=%.0f%%  mrr=%.3f  substr=%.0f%%\n" \
    "$f" \
    "$(jq '.hit_at_5_rate * 100' "$f")" \
    "$(jq '.mean_reciprocal_rank' "$f")" \
    "$(jq '.substring_match_rate * 100' "$f")"
done
```

### Per-query diff (which queries changed?)

```bash
diff \
  <(jq -r '.queries[] | [.id, .hit_at_5, .rank_of_first_match] | @csv' runs/01_real.json) \
  <(jq -r '.queries[] | [.id, .hit_at_5, .rank_of_first_match] | @csv' runs/04_real_expand_rerank.json)
```

### Per-category breakdown

```bash
jq '.by_category' runs/04_real_expand_rerank.json
```

### Paraphrase category specifically

```bash
for f in runs/*.json; do
  echo "$f:"
  jq '.by_category.paraphrase' "$f"
done
```

---

## Parameters

| Flag | Default | Effect |
|---|---|---|
| `--mode` | `mechanics` | `mechanics` (hash embedder) or `real` (Azure OpenAI). |
| `--rerank` | off | Enable Haiku listwise reranker. |
| `--expand` | off | Enable query expansion + HyDE. |
| `--top-k` | `5` | Final number of chunks fed to metrics / reranker output. |
| `--rerank-pool` | `20` | Candidate pool size fed into the reranker. |
| `--rerank-model` | `claude-haiku-4-5-20251001` | Model for reranking. |
| `--expansion-model` | `claude-haiku-4-5-20251001` | Model for query expansion. |
| `--json PATH` | off | Write machine-readable results to PATH (parent dir auto-created). |
| `--quiet` | off | Suppress per-query trace; print nothing (useful when scripting). |

---

## Corpus (`corpus/`)

12 documents about "Acme Corp" — a fictional B2B SaaS company.

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
| `11_competitor_overview.md` | DocuStream Corp (distractor) | English |
| `12_archived_bolt_v1_specs.md` | Archived v1 specs (distractor) | English |

Docs 11 and 12 are **distractor documents**: they share vocabulary with Acme
docs (same SLA percentage, same rate-limit endpoint names) to stress-test the
retriever's ability to distinguish the correct source.

---

## Query suite (`queries.json`)

32 queries across 9 categories:

| Category | n | What it stresses |
|---|---|---|
| `factual_lookup` | 13 | Direct keyword retrieval — BM25-friendly. |
| `multilingual_es` | 2 | Spanish query against Spanish doc. |
| `multilingual_pt` | 1 | Portuguese query against Portuguese doc. |
| `cross_language` | 1 | English query against Spanish doc. |
| `cross_doc_synthesis` | 2 | Answer requires combining two docs. |
| `multi_hop` | 3 | Answer requires reading a chain across docs. |
| `paraphrase` | 3 | Idiomatic phrasing with zero keyword overlap — BM25 blind. |
| `distractor` | 3 | Right doc shares vocabulary with a wrong doc. |
| `negative` | 4 | Out-of-corpus — correct answer is "I don't know". |

---

## Adding queries

1. Add a doc to `corpus/` with the new fact.
2. Add a query entry to `queries.json` with `expected_doc_basenames` /
   `expected_substrings`.
3. If the query is structurally novel (new category), add it to the table above.
4. Re-run to confirm the floor assertions in `tests/unit/rag/test_benchmark_smoke.py`
   still hold.

---

## Interpreting results

**Hit@5 ≥ 80%** is a reasonable bar for retrieval-only (no expansion).
**Hit@5 ≥ 95%** is expected with expansion + reranker on this corpus.

**Substring match < doc-match**: the retriever found the right doc but not the
right chunk. Try smaller `chunk_size` or larger overlap in `_ingest_corpus`.

**MRR < 0.6**: relevant docs are present but ranking is poor. The reranker
should help; also inspect BM25 vs vector RRF weights.

**Paraphrase hit@5 < factual hit@5**: the gap measures how much BM25 is
carrying the load. If it's large, enabling `--expand` (HyDE) should close it.

**Correct-rejection low**: the retriever is over-eager. RRF + sanitisation
should return nothing for out-of-corpus queries; if it doesn't, the
reranker's quality-over-quantity prompt is the right filter.
