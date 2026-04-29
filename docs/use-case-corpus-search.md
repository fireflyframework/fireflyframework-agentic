# Use Case: Corpus Search (`CorpusAgent`)

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

| | |
|---|---|
| Status | Design — pre-implementation |
| Date | 2026-04-29 |
| Branch | `javi/markitdown` |
| Supersedes | An earlier draft of this doc that included a knowledge-graph + extractors design — superseded by this corpus-search-first approach. |

This guide specifies a modular agent built on `fireflyframework-agentic` that watches
or scans a folder for new documents, ingests them via `markitdown`, and exposes a
hybrid (BM25 + vector) search query interface with LLM query expansion and answer
synthesis. No knowledge graph, no entity extractors at V1; structured extraction
(BPMN, person profiles) is deferred to V2 as **post-processing tools that operate on
the corpus**, not as ingest-time work.

The product is the qmd / GraphRAG-without-the-graph pattern: drop documents in a
folder, ask questions in natural language, get answers with citations.

---

## 1. Goal

A two-mode agent on top of `fireflyframework-agentic`:

- **Ingest mode** — scan a folder (or watch it), convert each file via `markitdown`,
  chunk, embed via OpenAI, and persist in a single SQLite file (chunks + FTS5) plus a
  Chroma vector store.
- **Query mode** — given a natural-language question, expand it via Haiku into 3–5
  reformulations, run BM25 + vector search for each, fuse the rankings via Reciprocal
  Rank Fusion (RRF), and synthesise an answer with `[chunk_id]` citations via Sonnet.

V1 ships **both modes end-to-end**. No reranker; RRF + Sonnet's reasoning over the
fused chunks does the work.

V2 (deferred) adds **post-processing extractors** — `extract_bpmn(doc_id)`,
`extract_person(name)`, `list_entities(type)` — that operate on the corpus, run an
LLM extraction, and emit a structured artefact (e.g. `.bpmn` XML, profile JSON). No
graph layer is required for these.

V3 (only if needed) adds a property-graph layer for fast cross-document structured
queries; the V2 extractors then become graph populators rather than one-shots.

---

## 2. Storage & deployment constraint (firm)

All persistent state lives on disk under a single root folder (default `./kg/`). All
dependencies are Python libraries — no daemons, no servers, no docker, no external
services beyond LLM/embedding API calls. The agent runs as a single Python process.

| Concern | Mechanism |
|---|---|
| Chunk store + FTS5 + ledger | SQLite (`./kg/corpus.sqlite`, WAL mode) |
| Chunk vectors | Chroma `PersistentClient` (`./kg/chroma/`) |
| File watching | `watchfiles` (in-process) |
| Document loading | `markitdown[pdf,docx,pptx,xlsx]` |

Network calls in V1 are limited to:
- **Embeddings** — Azure OpenAI by default (`EMBEDDING_BINDING_HOST` +
  `EMBEDDING_BINDING_API_KEY`). Plain OpenAI is supported by passing
  `--embed-model openai:<model>` (uses `OPENAI_API_KEY`).
- **Anthropic** — query expansion (Haiku) and answer synthesis (Sonnet).
  `ANTHROPIC_API_KEY` is **only required for `query`** — `ingest` never calls
  Anthropic, so it can run with embedding credentials alone.

---

## 3. Decisions consolidated

| # | Decision |
|---|---|
| Pipeline shape | Linear ingest (no fan-out, no extractors); single-call query |
| Trigger | Batch CLI primary; watcher (`watchfiles`) wraps the same code path |
| Chunk store | SQLite with FTS5 over chunk content (BM25 ranking) |
| Vector store | Chroma `PersistentClient`, OpenAI embeddings |
| Ledger | Co-located in `corpus.sqlite` as the `ingestions` table |
| Re-ingestion | Doc-id replace (delete chunks for `doc_id`, then re-chunk and re-embed) |
| Query expansion | Haiku, 3–5 reformulations per question |
| Hybrid retrieval | BM25 (FTS5) + vector (Chroma) per reformulation, fused via RRF (k=60) |
| Reranker | **None** in V1 — RRF + Sonnet's context handling are sufficient |
| Answer synthesis | Sonnet 4.6 with retrieved chunks as context, `[chunk_id]` citations |
| LLM (expansion) | `anthropic:claude-haiku-4-5-20251001`; env `ANTHROPIC_API_KEY` |
| LLM (answer) | `anthropic:claude-sonnet-4-6` |
| Embeddings (default) | `azure:text-embedding-3-small` — env `EMBEDDING_BINDING_HOST` + `EMBEDDING_BINDING_API_KEY` |
| Embeddings (alternative) | `openai:text-embedding-3-small` — env `OPENAI_API_KEY` |
| Concurrency | Files processed serially in V1 |
| Config surface | CLI flags only (no config file) |
| Default `--root` | `./kg` |
| Default top-K | BM25=30, vector=30, fused=10, presented to Sonnet |
| V2 (deferred) | Per-doc / per-entity extraction tools as post-processing over the corpus |

---

## 4. Architecture

### 4.1 Pipeline overview

**Ingest (per file):**

```mermaid
graph LR
    LOAD[markitdown] --> PRE[chunk + tag]
    PRE --> RESET[delete prior chunks for doc_id]
    RESET --> EMBED[embed chunks]
    EMBED --> STORE[store: SQLite + Chroma]
    STORE --> LEDGER[write ledger entry]
```

**Query (per question):**

```mermaid
graph LR
    Q[question] --> EXP[Haiku: expand to N reformulations]
    EXP --> BM25[BM25 search FTS5]
    EXP --> VEC[vector search Chroma]
    BM25 --> RRF[Reciprocal Rank Fusion]
    VEC --> RRF
    RRF --> ANS[Sonnet: answer with citations]
```

### 4.2 Framework additions

```
src/fireflyframework_agentic/
├── content/loaders/                      [NEW]
│   └── markitdown.py                     # MarkitdownLoader -> Document(content, metadata)
└── pipeline/triggers/                    [NEW]
    └── folder_watcher.py                 # FolderWatcher (watchfiles + stability + reconciliation)
```

`pyproject.toml` adds optional extras:

- `[markitdown]` — `markitdown[pdf,docx,pptx,xlsx]`.
- `[watch]` — `watchfiles`.
- `[corpus-search]` — convenience umbrella that pulls the above + `vectorstores-chroma` + `openai-embeddings`.

### 4.3 The agent (composes framework primitives)

```
examples/corpus_search/
├── __init__.py                # exports CorpusAgent
├── agent.py                   # CorpusAgent — high-level facade
├── corpus.py                  # SqliteCorpus (chunks + FTS5 + ledger)
├── retrieval/
│   ├── __init__.py
│   ├── expander.py            # QueryExpander — Haiku-based reformulations
│   ├── hybrid.py              # HybridRetriever — BM25 + vector + RRF
│   └── answerer.py            # AnswerAgent — Sonnet final answer
├── ingest/
│   ├── __init__.py
│   ├── pipeline.py            # async ingest_one(...) function
│   └── ledger.py              # IngestLedger
├── cli.py                     # python -m examples.corpus_search ingest|query
├── __main__.py
└── tests/
```

### 4.4 Default storage layout

```
./kg/
├── corpus.sqlite              # chunks, chunks_fts (FTS5), ingestions
└── chroma/                    # OpenAI embeddings of chunks
```

---

## 5. Component contracts

### 5.1 SQLite schema

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE chunks (
  chunk_id      TEXT PRIMARY KEY,         -- "<doc_id>-<index>"
  doc_id        TEXT NOT NULL,
  source_path   TEXT NOT NULL,
  index_in_doc  INTEGER NOT NULL,
  content       TEXT NOT NULL,
  metadata      TEXT NOT NULL              -- JSON (mime_type, title, hash, ...)
);
CREATE INDEX idx_chunks_doc ON chunks(doc_id);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  content,
  content='chunks',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2 porter'
);

-- Auto-sync triggers (FTS5 external-content pattern)
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;
CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
  INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE ingestions (
  doc_id              TEXT PRIMARY KEY,
  source_path         TEXT NOT NULL,
  content_hash        TEXT NOT NULL,
  status              TEXT NOT NULL,       -- 'success' | 'failed' | 'load_failed'
  ingested_at         TEXT NOT NULL,       -- ISO 8601
  attempt             INTEGER NOT NULL DEFAULT 1
);
```

The `porter` stemmer in the FTS5 tokenizer enables matching "running" with "run",
"queries" with "query", etc. Combined with `remove_diacritics 2`, the BM25 side
handles English morphology and accents reasonably well.

### 5.2 `SqliteCorpus`

```python
class SqliteCorpus:
    def __init__(self, path: Path) -> None: ...
    async def initialise(self) -> None: ...
    async def upsert_chunks(self, chunks: Sequence[StoredChunk]) -> None: ...
    async def delete_by_doc_id(self, doc_id: str) -> int: ...
    async def bm25_search(self, query: str, *, top_k: int = 30) -> list[ChunkHit]: ...
    async def get_chunks(self, chunk_ids: list[str]) -> list[StoredChunk]: ...
    async def query(self, sql: str, params: dict | None = None) -> list[dict]: ...
    async def close(self) -> None: ...
```

`StoredChunk(chunk_id, doc_id, source_path, index_in_doc, content, metadata)`,
`ChunkHit(chunk_id, score, content, metadata)`.

`bm25_search` issues:

```sql
SELECT c.chunk_id, c.content, c.metadata, bm25(chunks_fts) AS score
FROM chunks_fts
JOIN chunks c ON c.rowid = chunks_fts.rowid
WHERE chunks_fts MATCH :q
ORDER BY score
LIMIT :k;
```

### 5.3 `QueryExpander`

```python
class QueryExpander:
    def __init__(self, model: str): ...
    async def expand(self, question: str, *, n_variants: int = 4) -> list[str]: ...
```

Internally builds a small `FireflyAgent` with a Pydantic output schema returning a
list of strings. Prompt:

> Generate {n} alternative ways to phrase the same question that might match
> different wording in source documents. Include synonyms and related concepts.
> Return a JSON list of strings.

The original question is always included in the returned list (so total = `n + 1`).

### 5.4 `HybridRetriever`

```python
class HybridRetriever:
    def __init__(self, corpus: SqliteCorpus, vector_store: VectorStoreProtocol, embedder: EmbeddingProtocol): ...
    async def retrieve(
        self,
        queries: Sequence[str],
        *,
        top_k_per_query: int = 30,
        top_k_final: int = 10,
    ) -> list[ChunkHit]: ...
```

For each query in the list:

1. **BM25** via `corpus.bm25_search(query, top_k=top_k_per_query)`.
2. **Vector**: embed query, then `vector_store.search(query_embedding, top_k=top_k_per_query)`.

Fuse all `2N` rankings (N variants × 2 modalities) via Reciprocal Rank Fusion:

```
score(chunk) = Σ over rankings r: 1 / (k + rank_r(chunk))    # k = 60
```

Return the top `top_k_final` by RRF score, deduplicated by `chunk_id`, with their
content materialised from the corpus.

### 5.5 `AnswerAgent`

```python
class AnswerAgent:
    def __init__(self, model: str): ...
    async def answer(self, question: str, hits: Sequence[ChunkHit]) -> Answer: ...
```

`Answer(text, citations: list[str])` — Pydantic model. Sonnet receives the question
and the fused chunks formatted as:

```
[chunk-id-1] (source: filename.pdf)
content of chunk 1...

[chunk-id-2] (source: other.docx)
content of chunk 2...
```

System prompt instructs Sonnet to answer **only from the provided chunks**, cite
using `[chunk_id]` inline, and explicitly say "I don't have enough information" if
the chunks don't support an answer. The output schema collects unique citations
into a flat list.

### 5.6 `IngestLedger`

```python
class IngestLedger:
    def __init__(self, corpus: SqliteCorpus): ...
    async def should_skip(self, doc_id: str, content_hash: str) -> bool: ...
    async def upsert(self, doc_id: str, source_path: str, content_hash: str, *, status: str) -> None: ...
```

Wraps the `ingestions` table. Statuses: `success`, `failed`, `load_failed`. No
`partial` status (no fan-out → no partial state).

### 5.7 `CorpusAgent` (high-level facade)

```python
class CorpusAgent:
    def __init__(
        self,
        *,
        root: Path,
        embed_model: str,
        expansion_model: str,
        answer_model: str,
    ) -> None: ...

    async def ingest_one(self, path: Path) -> IngestionResult: ...
    async def ingest_folder(self, folder: Path) -> list[IngestionResult]: ...
    async def watch(self, folder: Path) -> AsyncIterator[IngestionResult]: ...
    async def query(self, question: str) -> Answer: ...
    async def close(self) -> None: ...
```

`IngestionResult(doc_id, source_path, status, n_chunks)`.

---

## 6. Data flow

### 6.1 Ingest (per file)

`doc_id = sha256(absolute_path)[:16]` — deterministic across watcher restarts.

1. **Load**: `MarkitdownLoader.load(path)` → `Document(content, metadata)`. On error → ledger `load_failed`, stop.
2. **Hash + skip check**: compute `content_hash = sha256(file_bytes)`. If `ledger.should_skip(doc_id, content_hash)` → return early.
3. **Chunk**: `TextChunker(chunk_size=600, chunk_overlap=80).chunk(content)` → list of chunks.
4. **Reset**: `corpus.delete_by_doc_id(doc_id)` and `vector_store.delete(filter={doc_id})`.
5. **Embed**: `OpenAIEmbedder.embed([c.content for c in chunks])` → embeddings.
6. **Store**: `corpus.upsert_chunks(stored_chunks)` and `vector_store.upsert(documents=...)` with `chunk_id` as IDs.
7. **Ledger**: `ledger.upsert(doc_id, path, content_hash, status="success")`.

Linear pipeline; the framework's `PipelineBuilder` is overkill for this — a single
async function suffices.

### 6.2 Query (per question)

1. **Expand**: `expander.expand(question, n_variants=4)` → list of 5 strings (original + 4 variants).
2. **Retrieve**: `retriever.retrieve(queries, top_k_per_query=30, top_k_final=10)` → 10 fused chunk hits.
3. **Answer**: `answerer.answer(question, hits)` → `Answer(text, citations)`.

If retrieval returns no hits, the answer agent is told explicitly and is expected to
say "I don't have enough information."

---

## 7. Error handling

- **`load_markitdown` raises** → ledger `load_failed`, no chunks/vectors written.
- **`embed` raises** → ledger `failed`, no chunks/vectors written; cleanup via `delete_by_doc_id`.
- **`upsert` raises** → ledger `failed`; cleanup via `delete_by_doc_id`.
- **`expand` raises during query** → fall back to the original question only (no expansion).
- **Empty retrieval** → answer agent returns "I don't have enough information." with empty citations.

Re-ingestion is always full-replace (delete-by-doc-id then re-chunk + re-embed).
There is no "rerun-only-failed" path.

---

## 8. Testing strategy

### 8.1 Unit (no LLM)

- `SqliteCorpus`: round-trip upsert, delete-by-doc-id, BM25 search returns hits.
- `IngestLedger`: state transitions.
- `MarkitdownLoader`: smoke tests with HTML / PDF / DOCX fixtures.
- `FolderWatcher`: debounce + stability via simulated `watchfiles` events.
- `HybridRetriever.fuse` (RRF math): given two ranked lists, fused order matches expected.

### 8.2 Integration (fake LLM)

- Full ingest of a tiny fixture: assert chunks in SQLite, vectors in Chroma, ledger row.
- Re-ingest same hash → skipped.
- Re-ingest changed hash → old chunks gone, new chunks present.
- Query path with stub `QueryExpander` and stub `AnswerAgent` returning canned data.

### 8.3 End-to-end (real LLM, gated)

- Drop a small fixture markdown file → run ingest CLI → ask a question → assert citations point to fixture chunks. Skipped unless `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are set.

### 8.4 Regression

- All existing examples (`basic_agent.py`, `idp_pipeline.py`, etc.) continue to pass.

---

## 9. CLI

Single entry point with two subcommands:

```bash
# Ingest (default: Azure OpenAI for embeddings, no Anthropic key needed)
python -m examples.corpus_search ingest \
    --folder ./drop \
    [--root ./kg] \
    [--embed-model azure:text-embedding-3-small] \
    [--watch] \
    [--verbose]

# Query (requires ANTHROPIC_API_KEY for expansion + answer)
python -m examples.corpus_search query "who is the CEO of OpenAI?" \
    [--root ./kg] \
    [--expansion-model anthropic:claude-haiku-4-5-20251001] \
    [--answer-model anthropic:claude-sonnet-4-6] \
    [--top-k 10] \
    [--verbose]
```

API keys read from environment / `.env` (matching the dotenv refactor in `examples/`).
The CLI validates exactly the credentials needed for the chosen subcommand:

| Subcommand | `--embed-model` prefix | Required env vars |
|---|---|---|
| `ingest` | `azure:` (default) | `EMBEDDING_BINDING_HOST`, `EMBEDDING_BINDING_API_KEY` |
| `ingest` | `openai:` | `OPENAI_API_KEY` |
| `query` | (uses defaults) | `EMBEDDING_BINDING_HOST`, `EMBEDDING_BINDING_API_KEY`, `ANTHROPIC_API_KEY` |

---

## 10. V2 trajectory — post-processing extraction tools

When BPMN export and similar structured outputs become a real need, add CLI
subcommands and / or query-agent tools that operate **over the existing corpus**:

```bash
# Per-document BPMN extraction: read chunks for doc X, LLM extract, emit .bpmn XML
python -m examples.corpus_search extract-bpmn --doc-id <id> > out/<id>.bpmn

# Per-entity profile aggregation: search corpus, LLM aggregates, emit JSON
python -m examples.corpus_search extract-profile "Sam Altman" > sam.json
```

Each extractor:

1. Selects relevant chunks from the corpus (single doc for BPMN; search-driven for profile).
2. Runs an LLM extraction call with a Pydantic schema.
3. Emits a structured artefact to disk (XML, JSON, etc.).

Optionally caches the artefact under `./kg/cache/extractions/`. No persistent graph
storage; the artefact files *are* the output.

V3 (only if structured cross-document queries become a hot path) adds a property-
graph layer; the V2 extractors then become graph populators rather than one-shots.

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `markitdown` PDF rendering quality varies | Start with markitdown; fall back to `pdfplumber` (the IDP example's approach) per format if quality issues surface in practice. |
| Embedding cost at scale | OpenAI `text-embedding-3-small` is ~$0.02 / 1M tokens; cheap. Larger corpora can swap to local embeddings (deferred). |
| Retrieval misses on rare entity names | The `porter` stemmer + Haiku query expansion covers most variants; if quality is the main failure mode, add a reranker in V2. |
| Sonnet hallucinates beyond chunks | System prompt restricts to provided chunks; `Answer.citations` field enforces explicit grounding; tests can spot-check that answer claims appear in cited chunks. |
| Watcher misses files during downtime | Startup scan reconciles against the ledger. |
| Single-writer SQLite under future parallel ingest | V1 is serial. A future `--concurrency N` serialises writes through a small queue. |

---

## 12. Open assumptions

1. **CLI subcommand naming**: `ingest` and `query`. If you prefer `index` instead of `ingest`, easy rename.
2. **Default `--root` is `./kg/`** even though there is no graph in V1; the directory name is preserved for V2/V3 continuity.
3. **OpenAI embeddings** require `OPENAI_API_KEY`; embedding failures are document-level failures.
4. **License header** on each new file follows the existing repo convention (Apache 2.0, "Copyright 2026 Firefly Software Solutions Inc.").
5. **No conversation memory** in V1 query mode — each `query()` call is independent. Multi-turn / conversational mode is V2.

---

## 13. Glossary

- **Corpus** — the markdown'd, chunked, embedded set of documents under `./kg/`.
- **BM25** — Best Matching 25, the standard term-frequency ranking used by SQLite FTS5; powers the lexical half of hybrid search.
- **RRF** — Reciprocal Rank Fusion. Given multiple ranked result lists, scores each item as `Σ 1 / (k + rank_i)` with `k=60`, producing a single fused ranking. No ML, no training.
- **Doc-id replace** — re-ingestion semantic: deleting all chunks and vectors for a `doc_id` before re-running ingest.
- **`CorpusAgent`** — the high-level facade combining `MarkitdownLoader`, `TextChunker`, `OpenAIEmbedder`, `SqliteCorpus`, Chroma, the optional `FolderWatcher`, plus the query stack (`QueryExpander`, `HybridRetriever`, `AnswerAgent`).
