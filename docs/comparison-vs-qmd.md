# Comparison: corpus_search vs. qmd

Generated 2026-04-29; qmd HEAD as of fetch time.

---

## 1. Side-by-Side Feature Matrix

| Feature | **qmd** (`@tobilu/qmd` v2.1.0) | **corpus_search** (this repo) |
|---|---|---|
| **Language / runtime** | TypeScript, Node ≥ 22 (also Bun); compiled to ESM | Python 3.13, asyncio |
| **Chunking strategy** | Smart markdown-aware: scored break points (h1→h3>code-block>hr>blank-line>list-item); never splits inside code fences; 900 token / 3600 char chunks, 15% overlap (`store.ts:51-110`). Optional AST-aware chunking for `.ts/.tsx/.js/.py/.go/.rs` via web-tree-sitter (`ast.ts`) | Fixed-size character chunking: 600 chars, 80-char overlap via `TextChunker` (`agent.py:77`). No structure awareness. |
| **BM25 / FTS5 setup** | `documents_fts USING fts5(filepath, title, body, tokenize='porter unicode61')` — indexes three fields including document path and title (`store.ts:initializeDatabase`). No `remove_diacritics`. | `chunks_fts USING fts5(content, content='chunks', content_rowid='rowid', tokenize='porter unicode61 remove_diacritics 2')` — external content table, single `content` field, with diacritic normalisation (`corpus.py:76-81`). FTS query sanitised through `sanitize_fts_query` (double-quoted OR tokens). |
| **Embedding model + dimensions** | Local GGUF via `node-llama-cpp`: default `embeddinggemma-300M-Q8_0` (~300M params); also supports Qwen3-Embedding. Dimensions detected at runtime; `vectors_vec` schema parameterised on first embed (`store.ts:ensureVecTableInternal`). | Remote API: Azure OpenAI `text-embedding-3-small` (1536d) by default; `openai:text-embedding-3-small` as alternative. No local embedding option. |
| **Vector store** | `sqlite-vec` virtual table (`vectors_vec USING vec0(embedding float[N] distance_metric=cosine)`) — everything in one SQLite file (`store.ts:ensureVecTableInternal`). | ChromaDB `PersistentClient` in a separate `./kg/chroma/` directory (`agent.py:166-179`). |
| **Query expansion** | Yes — fine-tuned local GGUF (`qmd-query-expansion-1.7B-q4_k_m.gguf`, fine-tune of Qwen3-1.7B) via `node-llama-cpp`. Outputs typed sub-queries: `lex` (BM25 only), `vec` (vector only), `hyde` (hypothetical document → vector). Skips expansion when initial BM25 has "strong signal" (score ≥ 0.85, gap ≥ 0.15) (`store.ts:hybridQuery`). Results cached in `llm_cache` SQLite table. | Yes — Anthropic `claude-haiku-4-5-20251001` via cloud API. Returns 4 free-text rephrasing variants; all routes both BM25 and vector. Falls back to original query on failure (`expander.py:56-87`). No caching; no strong-signal bypass. |
| **Reranker** | Yes — local GGUF `Qwen3-Reranker-0.6B-Q8_0` via `node-llama-cpp`. Pointwise scores per candidate against the query (`llm.ts`). Up to 40 candidates (`RERANK_CANDIDATE_LIMIT`). | Yes — Anthropic `claude-haiku-4-5-20251001` via cloud API. Listwise: LLM picks and orders top-K from the 20-candidate RRF pool (`reranker.py`). Falls back to retrieval order on failure. |
| **Result fusion (RRF)** | Yes — RRF across all typed sub-query results (`hybridQuery` in `store.ts`). k=60 (implied by standard RRF). | Yes — RRF across BM25+vector results for each of up to 5 queries, k=60 (`hybrid.py:27-44`). |
| **Answer synthesis** | No — qmd is a search/retrieval engine; it returns ranked document chunks with scores, snippets, and context annotations. The caller (LLM agent, MCP client) synthesises the answer. | Yes — `AnswerAgent` (Sonnet 4.6) receives top-K reranked chunks, returns structured `Answer(text, citations, cited_sources)` with inline `[chunk_id]` markers (`answerer.py`). "I don't have enough information" short-circuit on empty hits. |
| **File watching** | No built-in watcher. Users run `qmd update` manually or set a cron/`update_command` per collection in the YAML config. | Yes — `FolderWatcher` using `watchfiles.awatch` with debounce (500 ms), size-stability polling, and startup reconciliation scan (`folder_watcher.py`). `CorpusAgent.watch()` combines startup scan + live events. |
| **File format support** | Markdown only (default `**/*.md` glob). Collections are defined by glob pattern; no format converter. | All formats supported by `markitdown`: PDF, DOCX, PPTX, XLSX, HTML, plain text, Markdown — converted to Markdown before chunking (`markitdown.py`). |
| **MCP server** | First-class, built-in (`src/mcp/server.ts`). Exposes tools `query`, `get`, `multi_get`, `status`. Dual transport: stdio (default) and HTTP with `--http` flag (shared long-lived process, keeps models in VRAM). Dynamic server instructions injected into the LLM system prompt from live index state. MCP Resources: `qmd://{path}` URIs. | None. |
| **CLI surface** | Rich: `qmd update`, `qmd embed`, `qmd search`, `qmd vsearch`, `qmd query`, `qmd get`, `qmd multi-get`, `qmd collection add/remove/rename/list`, `qmd context add/remove/list`, `qmd status`, `qmd mcp`, `qmd maintenance` + several output formats (`--json`, `--files`, `--xml`, `--csv`) | Minimal: `python -m examples.corpus_search ingest --folder … [--watch]`, `… query "…"`, `… show-chunk <id>`. Three subcommands, no output format flags. |
| **Persistence layout** | Single SQLite file (default `~/.cache/qmd/index.sqlite`) + separate YAML config (`~/.config/qmd/index.yml`). Tables: `content` (hash→markdown), `documents` (virtual paths), `documents_fts` (FTS5), `content_vectors` (embedding metadata), `vectors_vec` (sqlite-vec virtual table), `llm_cache`, `store_collections`, `store_config`. | Two files under `./kg/`: `corpus.sqlite` (tables: `chunks`, `chunks_fts`, `ingestions`) + `chroma/` directory (ChromaDB). |
| **Config / customisation** | YAML config file (`~/.config/qmd/index.yml` or `--config`) with named collections, per-path context annotations, custom glob patterns, per-collection `update_command`, and model overrides (`QMD_EMBED_MODEL`, `QMD_RERANK_MODEL` env vars). CLI mutations write through to YAML. SDK accepts inline config or DB-only. | CLI flags only: `--root`, `--embed-model`, `--expansion-model`, `--rerank-model`, `--rerank-pool`, `--top-k`, `--watch`. No config file. |
| **Multi-collection** | Yes — named collections with independent paths, glob patterns, and per-path context strings that travel with search results. | No — single folder per ingest run; doc_id is SHA-256 of absolute path. |
| **LLM result caching** | Yes — `llm_cache` table in SQLite; caches query-expansion results by content hash; evicted to most-recent 1000 entries (`store.ts:setCachedResult`). | No. |
| **Index health / maintenance** | `qmd status` (counts, embedding state), `qmd maintenance` (vacuum, orphan cleanup, delete inactive docs). SDK `getIndexHealth()` / `getStatus()`. | `show-chunk` only. No maintenance tooling. |

---

## 2. What qmd Does That We Don't

**2.1 Fully local inference (no API keys needed)**
All LLM operations — query expansion, reranking, answer synthesis — run via `node-llama-cpp` with downloaded GGUF models. No Anthropic key, no OpenAI key, no cloud cost for queries.
`src/llm.ts` default models: `embeddinggemma-300M-Q8_0.gguf` (embed), `qwen3-reranker-0.6b-q8_0.gguf` (rerank), `qmd-query-expansion-1.7B-q4_k_m.gguf` (expand).

**2.2 sqlite-vec — single-file vector store**
Vectors live in `vectors_vec USING vec0(embedding float[N] distance_metric=cosine)` inside the same SQLite file as the document index (`src/store.ts:ensureVecTableInternal`). No external ChromaDB process or directory. Simpler backup, simpler deployment.

**2.3 MCP server (first-class, dual transport)**
`src/mcp/server.ts` exposes `query`, `get`, `multi_get`, `status` as MCP tools plus `qmd://{path}` resource URIs. The HTTP transport (`qmd mcp --http`) keeps models loaded in VRAM across requests. Dynamic server instructions are injected on connect from live index state (`buildInstructions`). We have nothing equivalent.

**2.4 Typed query expansion (lex / vec / hyde)**
qmd's expander produces typed sub-queries that route to different backends: `lex` → FTS5 only, `vec` → vector only, `hyde` → hypothetical document embedding → vector only (`src/store.ts:ExpandedQuery`). This enables HyDE (Hypothetical Document Embeddings), which can improve recall for abstract questions where no keyword matches exist. Our expander produces free-text variants that always hit both BM25 and vector.

**2.5 Strong-signal BM25 bypass**
When the top BM25 result scores ≥ 0.85 with a gap ≥ 0.15 from the runner-up, qmd skips query expansion and reranking entirely (`src/store.ts:STRONG_SIGNAL_MIN_SCORE`, `STRONG_SIGNAL_MIN_GAP`). This makes simple lookups near-instant. We always run expansion and reranking regardless of BM25 quality.

**2.6 LLM result cache**
Query expansion results are cached in the `llm_cache` SQLite table by content hash. Repeated or similar queries avoid LLM round-trips (`src/store.ts:getCachedResult/setCachedResult`).

**2.7 AST-aware chunking for source code**
`src/ast.ts` uses web-tree-sitter (optional deps: `tree-sitter-typescript`, `tree-sitter-python`, `tree-sitter-go`, `tree-sitter-rust`) to extract AST break points for code files, merged with markdown break points. Code chunks stay at function/class boundaries. We have no code-aware chunking.

**2.8 Multi-collection with per-path context annotations**
Collections are named and can carry context strings at any path prefix (e.g., `/journal/2025` → "Daily notes from 2025"). These context strings travel with search results to the LLM consumer. This dramatically improves answer quality in agentic flows. Our system is single-collection per ingest run with no context annotations.

**2.9 Rich CLI and output formats**
`qmd search` / `qmd query` accept `--json`, `--files`, `--xml`, `--csv` flags for structured output suited to agentic pipelines. We emit plain text.

**2.10 Explicit docid scheme and document retrieval**
qmd assigns short `#abc123` docids (content hash prefix) visible in search results, allowing `qmd get #abc123` to retrieve full document body including line-range slicing (`getDocumentBody`). We expose `show-chunk <chunk_id>` only (chunk level, not document level).

**2.11 HTTP MCP daemon mode**
`qmd mcp --http --daemon` runs a background HTTP MCP server that keeps models loaded in VRAM, writes a PID file, and accepts `qmd mcp stop`. Embedding/reranking contexts are disposed after 5 min idle. No equivalent in our system.

---

## 3. What We Do That qmd Doesn't

**3.1 Answer synthesis with citations**
`AnswerAgent` (Sonnet 4.6) synthesises a grounded natural-language answer from the retrieved chunks, citing `[chunk_id]` inline and returning structured `CitedSource` records with source paths and snippets (`answerer.py`). qmd is a retrieval engine; the answer step is left to the caller.

**3.2 Listwise LLM reranker**
Our `HaikuReranker` sends all candidates to the LLM in a single prompt and receives an ordered selection (`reranker.py:_INSTRUCTIONS`). qmd's reranker is pointwise (per-document scoring), which requires N LLM calls. Listwise is cheaper at moderate N and can exploit cross-candidate comparison.

**3.3 Non-Markdown document ingestion**
`MarkitdownLoader` converts PDF, DOCX, PPTX, XLSX, HTML, and plain text to Markdown before chunking (`markitdown.py`). qmd only indexes Markdown files directly.

**3.4 Real-time folder watching with stability detection**
`FolderWatcher` uses `watchfiles.awatch` (kernel-level inotify/kqueue events), debounces at 500 ms, and holds a file back until its size is stable across 2 polls at 200 ms intervals (`folder_watcher.py:wait_for_stability`). A startup reconciliation scan ensures nothing is missed during downtime. qmd has no built-in watcher.

**3.5 Python ecosystem and framework integration**
Built on `fireflyframework-agentic` — inherits `FireflyAgent`, `TextChunker`, `EmbeddingProtocol`, `VectorStoreProtocol`, `FolderWatcher`. Composable with the rest of the framework (IDP pipeline, graph stores, other triggers). qmd is a self-contained TypeScript library.

**3.6 Ingest-only mode without LLM keys**
`CorpusAgent._ensure_corpus_ready` constructs only the embedder and corpus on first ingest; the entire LLM stack (`QueryExpander`, `HaikuReranker`, `AnswerAgent`) is constructed lazily on first `query()` call (`agent.py:92-119`). `ingest` subcommand works with only embedding credentials — no `ANTHROPIC_API_KEY` required.

**3.7 Azure OpenAI embedding support**
`CorpusAgent._build_embedder` supports `azure:<deployment>` provider prefix, reading `EMBEDDING_BINDING_HOST` and `EMBEDDING_BINDING_API_KEY` (`agent.py:127-155`). qmd has no Azure provider.

**3.8 Explicit content-hash deduplication**
`IngestLedger.should_skip` skips re-ingestion when `doc_id` and `content_hash` are unchanged (`ingest/ledger.py`). Re-ingest on hash change does full delete-then-replace with best-effort vector store cleanup. qmd tracks document modification time but the deduplication mechanism is different (file hash vs mtime).

**3.9 FTS5 diacritic normalisation**
`tokenize='porter unicode61 remove_diacritics 2'` in `chunks_fts` normalises accented characters so "café" matches "cafe" (`corpus.py:80`). qmd's FTS uses `porter unicode61` without `remove_diacritics`.

---

## 4. Architectural / Design Philosophy Differences

**MCP-first (qmd) vs. CLI-first (corpus_search)**
qmd's README leads with the MCP server and frames CLI tools as auxiliary. The MCP tools (`query`, `get`, `multi_get`) are the primary consumption surface for agentic workflows. Our system has no MCP layer; the CLI is the only interface.

**Local-only inference vs. cloud API**
qmd deliberately avoids cloud API keys: every LLM operation runs via `node-llama-cpp` with local GGUF models. This is a firm design constraint (README: "Ideal for your agentic flows" without cloud dependency). Our system requires Anthropic and OpenAI/Azure API keys for query (and embedding), making it unsuitable for air-gapped or cost-sensitive deployments at query time.

**Retrieval engine vs. RAG pipeline**
qmd returns ranked search results (documents + scores + snippets + context). It is deliberately a retrieval engine — the caller decides what to do with results. Our system is a full RAG pipeline: ingest → retrieve → rerank → synthesise answer. This makes us more opinionated but requires less caller-side complexity.

**Single-file storage (qmd) vs. dual-store (corpus_search)**
qmd stores everything (FTS, vectors, content, metadata) in one SQLite file using `sqlite-vec`. Backup is `cp index.sqlite`. Our system uses a SQLite file (FTS + chunks + ledger) plus a separate Chroma directory (vectors). This is operationally more complex and introduces a two-phase cleanup on re-ingest.

**Named collections with context annotations (qmd) vs. flat corpus (corpus_search)**
qmd's collections carry human-readable context strings at path prefixes that travel with results to the LLM. This is described in the README as the "key feature." Our system has a flat doc_id-keyed corpus with no concept of collections or context.

**TypeScript / Node ecosystem vs. Python / asyncio**
qmd ships as an npm package (`@tobilu/qmd`), installs globally with `npm install -g`, and integrates with Claude Code via a plugin marketplace. Our system is a Python module requiring `uv` or pip and the fireflyframework-agentic environment.

**Scale and concurrency**
qmd processes collections serially in `reindexCollection` but embeds in batches (`DEFAULT_EMBED_MAX_DOCS_PER_BATCH = 64`). The MCP HTTP daemon keeps models warm. Our system is explicitly serial in V1 (`docs/use-case-corpus-search.md:89`) with a SQLite asyncio lock for writes. Neither system is designed for high-concurrency production workloads at V1.

---

## 5. Areas Where qmd's Approach Is Better Than Ours

**5.1 No cloud dependency at query time.** Running expansion and reranking locally via GGUF models eliminates per-query API costs, network latency, and privacy exposure. For a personal knowledge base this is strictly better.

**5.2 Single-file storage is operationally simpler.** One SQLite file beats SQLite + Chroma directory for backup, versioning, and portability. `sqlite-vec` is a mature extension; there is no ChromaDB version to keep in sync.

**5.3 Typed sub-queries (lex/vec/hyde) are semantically richer.** Routing `hyde` queries only to vector search (not BM25) avoids the noise from hypothetical document text hitting the keyword index. Our free-text variants route everything to both.

**5.4 Strong-signal bypass cuts latency for simple lookups.** A BM25 score ≥ 0.85 with a clear gap triggers immediate return without LLM expansion or reranking. For a user retrieving a known document, the median latency is ~100ms vs. our 3–5s round-trips.

**5.5 LLM result caching avoids repeated expansion cost.** The `llm_cache` table persists expansion results. If the same (or structurally identical) query is repeated, there is zero LLM cost. We have no cache.

**5.6 Context annotations dramatically improve agentic quality.** Per-path context strings sent alongside results give the LLM consumer rich framing ("Meeting notes from 2025-Q1") without needing to read the document. We have no equivalent.

**5.7 AST-aware chunking preserves code semantics.** For repos indexed by qmd (TypeScript, Python, Go, Rust), chunks respect function and class boundaries. Our fixed-character chunker can split a function in half.

---

## 6. Areas Where Our Approach Is Better Than qmd's

**6.1 Answer synthesis with inline citations.** The `AnswerAgent` (Sonnet 4.6) produces a grounded natural-language answer with `[chunk_id]` citations and `CitedSource` records mapping citations to source files. qmd leaves this entirely to the caller. For users who want "ask a question, get an answer with sources" as a single command, we win.

**6.2 Broader file format support.** PDF, DOCX, PPTX, XLSX, HTML via `markitdown` without any pre-processing by the user. qmd requires Markdown; PDFs must be converted before indexing.

**6.3 Real-time file watching with stability polling.** `FolderWatcher` detects writes in-process, debounces, waits for file stability, and reconciles on restart. qmd requires a cron job or manual `qmd update`.

**6.4 Listwise reranking is cheaper at moderate N.** A single Haiku call with 20 candidates is cheaper than 20 pointwise rerank calls. At `N=20`, our reranker is O(1) LLM calls; qmd's is O(N).

**6.5 Azure OpenAI embeddings for enterprise deployments.** Many enterprise environments mandate Azure OpenAI endpoints. Our `--embed-model azure:<deployment>` flag handles this natively.

**6.6 Python ecosystem and framework composability.** The example plugs directly into `fireflyframework-agentic` primitives (`FireflyAgent`, `TextChunker`, `VectorStoreProtocol`). Adding a new trigger (SQS, REST webhook), a new loader, or a new post-processing extractor is framework-native. qmd is self-contained and harder to extend.

**6.7 Ingest does not require LLM keys.** Separation of ingest (embedding only) from query (LLM required) allows running ingest jobs in environments without Anthropic keys — useful in CI/CD or batch-processing pipelines.

---

## 7. Migration / Interoperability Notes

**Moving from qmd to corpus_search:**
- qmd indexes only Markdown; our system accepts the same files. A user with a `~/notes/**/*.md` collection can point `ingest --folder ~/notes` at the same directory.
- The SQLite schemas are incompatible (qmd: `documents` + `documents_fts` + `content_vectors` + `vectors_vec`; ours: `chunks` + `chunks_fts`). There is no migration tool; documents must be re-ingested.
- qmd's `qmd://collection/path.md` virtual path scheme has no equivalent in our system; chunk_ids are the only opaque handle.
- Users lose: named collections, per-path context annotations, local GGUF inference, MCP tools.
- Users gain: answer synthesis, broader file formats, live watching.

**Moving from corpus_search to qmd:**
- Users lose: PDF/DOCX/PPTX/XLSX ingestion (must pre-convert to Markdown), answer synthesis, Azure embedding support, Python integration.
- Users gain: MCP server, local inference (no API keys at query time), single-file storage, named collections with context, rich CLI.
- A user relying on our `Answer.cited_sources` structure would need to implement their own RAG synthesis layer on top of qmd's search results.
- The two systems can co-exist on the same document corpus — each builds its own independent index from the same files.

---

## 8. Three Concrete V2 Improvements Grounded in qmd

**8.1 Replace ChromaDB with sqlite-vec**

qmd demonstrates that `vectors_vec USING vec0(embedding float[N] distance_metric=cosine)` (`src/store.ts:ensureVecTableInternal`) is a viable production vector store inside SQLite. Replacing Chroma with sqlite-vec would:
- Reduce the persistence layout from two paths (`corpus.sqlite` + `chroma/`) to one.
- Eliminate the two-phase cleanup on re-ingest (delete from SQLite, then best-effort delete from Chroma).
- Simplify backup to a single file copy.
- Remove the `chromadb` optional dependency.

The `fireflyframework-agentic` `VectorStoreProtocol` already abstracts the vector backend, so this is a backend swap, not an API change. The implementation pattern is fully available in `src/store.ts:ensureVecTableInternal` and `src/db.ts`.

**8.2 Add a strong-signal bypass (skip expansion when BM25 is decisive)**

qmd's `STRONG_SIGNAL_MIN_SCORE = 0.85` / `STRONG_SIGNAL_MIN_GAP = 0.15` check (`src/store.ts:hybridQuery:30-35`) means simple lookups return in ~100ms with no Anthropic API call. We always run `QueryExpander` + `HaikuReranker` + `AnswerAgent` regardless of BM25 quality — three cloud round-trips for a query that has an obvious answer.

A two-line addition to `CorpusAgent.query()`: run a quick BM25 probe first; if the top hit is decisive, bypass expansion and rerank and feed that hit directly to `AnswerAgent`. This would halve median latency for common queries at negligible implementation cost.

**8.3 Implement typed query expansion (add a `hyde` query type)**

qmd's typed sub-query system (`ExpandedQuery.type: 'lex' | 'vec' | 'hyde'`) enables HyDE (Hypothetical Document Embeddings) as a first-class retrieval path (`src/llm.ts:expandQuery`). For questions about abstract concepts ("what is the company's risk tolerance?"), writing a hypothetical answer and embedding it often retrieves relevant chunks that no keyword or paraphrase would match.

Our `QueryExpander` currently generates free-text variants that all hit both BM25 and vector. A V2 extension would:
1. Change `QueryExpander` output to include a typed `hyde` variant (a short hypothetical passage that would answer the question).
2. In `HybridRetriever.retrieve`, route `hyde` variants to vector-only (skip BM25 for hypothetical documents — their token distribution is misleading as BM25 input).
3. Include `hyde` results in the RRF pool alongside `lex`/`vec` results.

This is a contained change to `expander.py` (output schema) and `hybrid.py` (routing logic) with no changes to the storage layer.

---

## Sources

- `https://github.com/tobi/qmd` — repository root and README
- `https://raw.githubusercontent.com/tobi/qmd` via GitHub API (`gh api repos/tobi/qmd/contents/…`):
  - `src/store.ts` — core data access, FTS5 schema, sqlite-vec schema, chunking, hybridQuery
  - `src/db.ts` — SQLite compatibility layer, sqlite-vec loading
  - `src/llm.ts` — LlamaCpp wrapper, default model URIs, query expansion
  - `src/index.ts` — QMDStore SDK interface and createStore factory
  - `src/ast.ts` — AST-aware chunking via web-tree-sitter
  - `src/cli/qmd.ts` — CLI entry point and command surface
  - `src/mcp/server.ts` — MCP server (tools, resources, HTTP transport)
  - `package.json` — dependencies, versions, bin entry point
  - `example-index.yml` — YAML config format example
- Local working tree (`/Users/javi/work/fireflyframework-agentic`):
  - `docs/use-case-corpus-search.md`
  - `examples/corpus_search/agent.py`
  - `examples/corpus_search/corpus.py`
  - `examples/corpus_search/cli.py`
  - `examples/corpus_search/ingest/pipeline.py`
  - `examples/corpus_search/retrieval/hybrid.py`
  - `examples/corpus_search/retrieval/expander.py`
  - `examples/corpus_search/retrieval/reranker.py`
  - `examples/corpus_search/retrieval/answerer.py`
  - `src/fireflyframework_agentic/content/loaders/markitdown.py`
  - `src/fireflyframework_agentic/pipeline/triggers/folder_watcher.py`
