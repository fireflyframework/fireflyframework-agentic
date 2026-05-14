# CorpusAgent + ContentSource Abstraction

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

| | |
|---|---|
| Status | **Approved (design)** |
| Date | 2026-05-05 |
| Branch | to be created off `main` (`javi/corpus-agent-content-source`) |
| Replaces | `tools/builtins/sharepoint_rag.py` introduced in [PR #103](https://github.com/fireflyframework/fireflyframework-agentic/pull/103) |
| Author | Sam Lee-Valle |

---

## 1. Goal

Replace the parallel RAG stack introduced in PR #103
(`tools/builtins/sharepoint_rag.py`) with a thin composition over the
existing `CorpusAgent` and `ContentSource` Protocol. After this work:

- `CorpusAgent` lives in the library and accepts any `ContentSource`
  (filesystem or SharePoint today; S3 / Confluence / GDrive in the future
  with no changes to consumers).
- The MCP tool surface is four small wrappers that construct a
  `CorpusAgent` per call, build the requested source, and delegate.
- A single underlying ingest pipeline (chunker, embedder, vector store,
  ledger) serves both filesystem and SharePoint — no duplication, no
  drift.

## 2. Non-goals

- Replacing `SqliteCorpus` / `SqliteVecVectorStore` with a managed vector
  database.
- Push-based SharePoint watching via Microsoft Graph webhook
  subscriptions.
- Completing the `S3Source` stub. It stays a stub.
- Changes to the auth model (managed identity → Graph for SharePoint
  remains as in PR #103).
- Multi-tenant / RBAC isolation between corpora.

## 3. State of the world (verified 2026-05-05)

- **`ContentSource` Protocol** ships in `main` (PR #101): `list_changed`,
  `fetch`, `current_cursor`, `pending_cursor`, `commit_delta`. Live
  implementations: `SharePointSource`. Stub: `S3Source`. No
  `LocalFolderSource` yet.
- **`CorpusAgent`** ships at `examples/corpus_search/agent.py` (PR #102).
  It owns chunker (`MarkdownChunker`), loader (`MarkitdownLoader`),
  embedder (Azure or OpenAI), vector store (`SqliteVecVectorStore`),
  corpus (`SqliteCorpus`), ledger, and the full retrieval stack
  (expander, hybrid retriever, reranker, answerer). Its ingest API today
  is `Path`-based (`ingest_one`, `ingest_folder`, `watch`); it has no
  notion of `ContentSource`.
- **Retrieval components** already live under
  `src/fireflyframework_agentic/rag/retrieval/` (`expander.py`,
  `hybrid.py`, `reranker.py`). Only `answerer.py` is still under
  `examples/corpus_search/retrieval/`.
- **PR #103 (`deploy/azure-mcp`, open)** introduces
  `tools/builtins/sharepoint_rag.py`, which:
  - Reimplements ingest using `TextChunker` + `InMemoryVectorStore` —
    objectively worse than `MarkdownChunker` + `SqliteVecVectorStore`.
  - Caches per-corpus state in a process-global `_CORPORA: dict`. A
    fresh process answers `query_corpus` with `"corpus not found"` even
    if the SQLite file is on disk.
  - Pins `SqliteCorpus` to `/tmp/firefly/corpora/<corpus_id>.db` —
    Container Apps `/tmp` is per-replica and ephemeral on restart.
  - Hardcodes SharePoint as the only source.
  - Returns raw hits with no expander, reranker, or answerer.

## 4. File moves and new components

| Action | Path | Notes |
|---|---|---|
| Move | `examples/corpus_search/agent.py` → `src/fireflyframework_agentic/rag/agent.py` | `CorpusAgent` becomes a library component. |
| Move | `examples/corpus_search/retrieval/answerer.py` → `src/fireflyframework_agentic/rag/retrieval/answerer.py` | Joins the rest of the retrieval stack. |
| New | `src/fireflyframework_agentic/content/sources/local_folder.py` | `LocalFolderSource` implementing `ContentSource`. |
| New | `src/fireflyframework_agentic/tools/builtins/corpus_rag.py` | Four MCP tools, replaces `sharepoint_rag.py`. |
| Delete | `src/fireflyframework_agentic/tools/builtins/sharepoint_rag.py` | Plus its side-effect import in `cli/mcp_http.py`. |
| Update | `examples/corpus_search/{__main__.py,cli.py}` and tests | Import `CorpusAgent` from the library. |
| Update | `src/fireflyframework_agentic/content/sources/__init__.py` | Export `LocalFolderSource`, `LocalFolderSourceConfig`. |
| New | `docs/deploy/corpus-persistence.md` | Operator guide for durable storage. |

The example becomes a thin demo: it constructs a `CorpusAgent` from the
library, optionally adds CLI flags / Azure Monitor wiring on top, and
nothing else.

## 5. `CorpusAgent` reshape

```python
class CorpusAgent:
    def __init__(self, *, root: Path, embed_model: str, embed_dimension: int = 1536,
                 expansion_model: str, answer_model: str, rerank_model: str,
                 rerank_pool: int = 20,
                 _embedder: Any | None = None, _vector_store: Any | None = None) -> None: ...

    # ----- ingest (single underlying pipeline) -----
    async def ingest_source(self, source: ContentSource) -> IngestSummary: ...
    async def ingest_folder(self, folder: Path) -> IngestSummary: ...   # wraps LocalFolderSource(folder)
    async def ingest_one(self, path: Path) -> IngestionResult: ...      # unchanged

    # ----- retrieval (split) -----
    async def retrieve(self, question: str, *, top_k: int = 5,
                       rerank: bool = True) -> list[Hit]: ...            # no LLM answer
    async def query(self, question: str, *, top_k: int = 5) -> Answer: ...   # full pipeline w/ citations

    # ----- watch -----
    def watch_source(self, source: ContentSource, *,
                     interval: float = 60.0) -> AsyncIterator[IngestionResult]: ...
    def watch(self, folder: Path) -> AsyncIterator[IngestionResult]: ...     # inotify fast path (kept)
```

`ingest_source` is the canonical ingest API. `ingest_folder` becomes a
one-line wrapper that constructs a `LocalFolderSource(folder)` and
delegates — keeping the example, CLI, and existing tests working
unchanged. `ingest_one(path)` likewise stays for single-file callers.

`retrieve` runs expand → hybrid retrieval → (optional) rerank, returning
typed `Hit` objects. `query` calls `retrieve` then `AnswerAgent.answer`,
returning an `Answer` with citations. The expander, reranker, and
answerer stay lazily constructed (existing pattern) so the ingest path
does not require `ANTHROPIC_API_KEY`.

`watch_source` polls `list_changed(cursor)` on a timer and yields
`IngestionResult` per file. `watch(folder)` keeps the inotify-based
fast path unchanged for local-folder use cases that need sub-second
latency.

`IngestSummary` wraps the per-file results plus aggregate counts so
existing callers that iterate results keep working:

```python
@dataclass(slots=True)
class IngestSummary:
    results: list[IngestionResult]
    cursor: str | None
    @property
    def ingested(self) -> int: ...
    @property
    def skipped(self) -> int: ...
    @property
    def failed(self) -> int: ...
```

`ingest_source`, `ingest_folder`, and `watch_source` all return / yield
into this shape. `ingest_one(path)` keeps its single-`IngestionResult`
return for the single-file case. The example CLI / `__main__` are
updated accordingly.

## 6. `LocalFolderSource` (v1)

```python
class LocalFolderSourceConfig(BaseModel):
    folder: Path
    include_hidden: bool = False     # reuses FolderWatcher.is_hidden filter

class LocalFolderSource:
    # list_changed(since): yields RawFile per file under folder.
    #   - In v1, `since` is ignored; every call lists everything.
    #     IngestLedger dedupes by content hash so this is cheap.
    # source_id: f"local:{folder}/{relpath}"
    # mime_type: derived from the suffix (mimetypes.guess_type)
    # etag: f"{stat.st_mtime_ns}:{stat.st_size}"
    # fetched_at: datetime.now(UTC) per yield
    # fetch(raw): returns the path as-is (no copy needed)
    # current_cursor / pending_cursor / commit_delta: no-ops returning None
```

Delta-since-cursor (e.g. mtime > cursor_timestamp) is a future
enhancement and out of scope for this spec. The Protocol is satisfied;
a future implementation can swap in real cursor semantics without
changing consumers.

## 7. MCP tool surface (`corpus_rag.py`)

```python
@firefly_tool("ingest_corpus_filesystem", tags=("rag", "ingest", "filesystem"))
async def ingest_corpus_filesystem(corpus_id: str, root_path: str) -> dict: ...

@firefly_tool("ingest_corpus_sharepoint", tags=("rag", "ingest", "sharepoint"))
async def ingest_corpus_sharepoint(corpus_id: str, drive_id: str,
                                   root_folder: str | None = None) -> dict: ...

@firefly_tool("corpus_retrieve", tags=("rag", "query"))
async def corpus_retrieve(corpus_id: str, question: str, top_k: int = 5) -> dict: ...

@firefly_tool("corpus_query", tags=("rag", "query"))
async def corpus_query(corpus_id: str, question: str, top_k: int = 5) -> dict: ...
```

Each call:

1. Resolves `root = CORPUS_ROOT/<corpus_id>` (env `CORPUS_ROOT`, default
   `/tmp/firefly/corpora`).
2. Constructs `CorpusAgent(root=root, embed_model=..., ...)`. Models
   come from env: `EMBEDDING_MODEL`, `EXPANSION_MODEL`, `ANSWER_MODEL`,
   `RERANK_MODEL`. Same conventions as the example CLI.
3. Builds the source:
   - filesystem → `LocalFolderSource(folder=root_path)`
   - sharepoint → `SharePointSource(SharePointSourceConfig(drive_id,
     root_folder, cache_dir=root/"sharepoint"/"cache",
     delta_file=root/"sharepoint"/"delta.json"),
     token_provider=managed_identity_graph_token)`
4. For ingest: `await agent.ingest_source(source)`; returns the summary.
5. For retrieve / query: if `${CORPUS_ROOT}/<corpus_id>/corpus.sqlite`
   does not exist, raise `CorpusNotFoundError` immediately. Otherwise
   open the agent, run the call, and return hits or answer + citations.
   The existence check is the precise definition of "unknown corpus":
   no SQLite file means nothing has been ingested.

No process-global registry. The `_CORPORA` dict is removed; on-disk
state and `IngestLedger` carry continuity across requests and across
replicas (subject to §9 deployment caveats).

`cli/mcp_http.py`'s side-effect import changes from `sharepoint_rag` to
`corpus_rag`.

## 8. Error handling

- **Per-file ingest failures**: logged, counted in `IngestSummary`,
  ledger marks `failed`. The cursor advances only after the iterator
  drains successfully — a crash mid-batch leaves the cursor at the
  previous value so the next run reprocesses the dropped items.
  (Existing `ContentSource` contract.)
- **Source-level failures** (auth, 5xx, cursor file tampering): bubble
  up as MCP tool errors. No silent fallbacks.
- **Unknown `corpus_id` on `corpus_retrieve` / `corpus_query`**: raise
  `CorpusNotFoundError` (`tools.exceptions`) → surfaced as an MCP
  protocol error to the caller. The current
  `{hits: [], warning: "corpus not found"}` shape is removed: it
  conflates "no relevant chunks" with "no such corpus", which is
  exactly the silent-error pattern the project guardrails forbid.
- **LLM failures** (expand / rerank / answer): bubble up; the MCP
  client decides retry policy. Network-level retries belong to the
  HTTP clients in those modules, not to `CorpusAgent`.

## 9. Persistence and deployment

The framework keeps writing to `${CORPUS_ROOT}/<corpus_id>/corpus.sqlite`
(co-resident chunks + FTS5 + vec0 + ledger, per the SqliteVec design).
`CORPUS_ROOT` defaults to `/tmp/firefly/corpora`. **Operators are
expected to override it for any non-toy deployment.**

A new operator guide at `docs/deploy/corpus-persistence.md` will cover:

1. Why `/tmp` is unsafe on Azure Container Apps (per-replica, wiped on
   restart, not shared).
2. Provisioning an Azure Files share and mounting it on the
   `firefly-mcp` Container App, following Microsoft's storage-mounts
   guide
   ([learn.microsoft.com/azure/container-apps/storage-mounts](https://learn.microsoft.com/azure/container-apps/storage-mounts)).
   Concrete `az` commands live in the operator guide, not this spec, so
   they don't drift as the Azure CLI surface evolves.
3. Setting `CORPUS_ROOT=/mnt/corpora` on the Container App.
4. **Multi-replica caveat**: `SqliteCorpus` is single-writer
   (`vec0` + FTS5 + ledger in one file). Two replicas writing the same
   corpus will corrupt the index. Either pin `--max-replicas 1` for
   the ingest path, or arrange that a given `corpus_id` is only
   written by one replica (e.g. partition routing in the calling
   agent). Reads are safe to fan out.

## 10. Testing

- **Unit — `LocalFolderSource`**: yield set matches a fixture tree,
  hidden-file filter respected, etag stable across calls when files
  unchanged, etag changes on mtime / size mutation, cursor methods
  return `None`.
- **Unit — `CorpusAgent.ingest_source`**: round-trips through
  `LocalFolderSource` and through a fake in-memory `ContentSource`.
  Ledger dedupes a second pass to zero new ingests.
- **Unit — `CorpusAgent.retrieve` vs `query`**: `retrieve` does not
  invoke `AnswerAgent`; `query` does. Mocked embedder + LLMs.
- **Unit — `CorpusAgent.ingest_folder` parity**: confirms the
  `LocalFolderSource` wrapper produces the same set of ingested
  documents as the previous direct-`rglob` implementation against a
  fixture tree.
- **Integration — example e2e**: existing `examples/corpus_search/`
  end-to-end run (PR #102) ported to library imports, must still pass
  on the operator corpus with no quality regression.
- **Integration — MCP**: new
  `tests/integration/cli/test_corpus_rag_mcp.py` exercises the four
  MCP tools end-to-end. Filesystem ingest uses a fixture tree;
  SharePoint path uses a stub `ContentSource` injected via a test
  hook (no real Graph traffic).
- **Regression — error model**: `corpus_retrieve` / `corpus_query`
  raise `CorpusNotFoundError` for an unknown `corpus_id` (asserted via
  `pytest.raises`).

## 11. Telemetry

Existing `_telemetry.py` spans use the `corpus_search.` prefix
(`corpus_search.ingest_folder`, `corpus_search.query`, per-stage
histograms) inherited from when the code lived under
`examples/corpus_search/`. Now that it's library code, the prefix
should become `firefly.rag.` to match the surrounding convention.

This rename is **optional and may be deferred** to a follow-up — the
abstraction work in this spec stands without it. If deferred, capture
it as a separate task and update the AppInsights spec
(`docs/superpowers/specs/2026-05-04-corpus-search-e2e-appinsights-design.md`)
and any saved KQL queries together. If included, do it as the last
commit of the same PR so the dashboard updates ship atomically.

## 12. Out of scope (recap)

Managed vector DB; Graph webhook subscriptions; S3Source completion;
auth-model changes; multi-tenant RBAC. Each of those is a separate
spec.

## 13. Open questions

None at design time.
