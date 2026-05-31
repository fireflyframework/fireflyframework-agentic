# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

## [26.05.33] - 2026-05-31

### Removed

- **BREAKING — REST/queue exposure layer.** Deleted the `fireflyframework_agentic.exposure`
  package (FastAPI app factory, HTTP/WS controllers, health probes, SSE, CORS/rate-limit/auth
  middleware, and Kafka/RabbitMQ/Redis consumer/producer hosts), the `rest`/`kafka`/`rabbitmq`/
  `redis`/`queues` extras, the `ExposureError`/`QueueConnectionError` exceptions, and the
  REST-serving config fields `auth_api_keys`/`auth_bearer_tokens`/`cors_allowed_origins`.
  Serving/hosting is now owned by the consuming service. The framework is a pure in-process
  library: it serves no port and consumes no broker.
- **BREAKING — service/infra observability.** Removed `observability.configure_exporters`
  (global OTel SDK provider/exporter wiring), the W3C trace-context propagation helpers
  (`inject_trace_context`/`extract_trace_context`/`get_trace_context`/`set_trace_context`/
  `trace_context_scope`), the `WebhookSink`, and the `otlp_endpoint` config field. The
  framework still emits model/agent spans/metrics via the OpenTelemetry API; configuring the
  SDK/exporters and cross-service trace propagation is now the host's responsibility.

## [26.05.32] - 2026-05-31

### Fixed

- **`QdrantVectorStore.delete` is now namespace-scoped** — it deletes only points
  matching both the namespace and the requested ids (via a `FilterSelector`
  combining a `_namespace` `FieldCondition` with `HasIdCondition`), mirroring the
  namespace filter applied on search. Previously it deleted by a bare id list,
  ignoring the namespace.

### Changed

- **`scope_namespace` validates its inputs** — rejects empty components or
  components containing `/`, so distinct `(tenant_id, workspace_id)` scopes can
  never encode to a colliding namespace. The guard lives where the namespace is
  built rather than trusting callers.

## [26.05.31] - 2026-05-31

### Added

- **pgvector vector store** — `fireflyframework_agentic.vectorstores.PgVectorVectorStore`,
  an asyncpg-backed `BaseVectorStore` peer to the Chroma / Pinecone / Qdrant
  adapters. Owns its table with an HNSW cosine index, namespace-scoped storage,
  idempotent runtime schema bootstrap, and metadata filtering. Adds an
  overridable `_prepare_session(conn, *, namespace)` per-transaction hook (default
  no-op) for connection-level session setup — e.g. `SET LOCAL` for Postgres
  Row-Level Security GUCs. New optional extra `[vectorstores-pgvector]` (asyncpg);
  requires the `pgvector` extension on the server. This fills the only vector
  backend the framework was missing.
- **Tenant-scoped vector store layer** — `fireflyframework_agentic.vectorstores.scoped`:
  `ScopedVectorStore` (an explicit, fail-loud `Protocol` with required keyword-only
  `tenant_id` / `workspace_id`) and `TenantScopedVectorStore`, a backend-agnostic
  wrapper that folds `(tenant_id, workspace_id)` into the canonical
  `"t/<tenant>/w/<workspace>"` namespace (and stamps it onto document metadata),
  making **any** `VectorStoreProtocol` backend multi-tenant with one wrapper. Adds
  `scope_namespace` / `parse_scope_namespace` helpers. The existing
  single-namespace `VectorStoreProtocol` is unchanged (additive, non-breaking).

### Changed

- **`QdrantVectorStore`** now creates its collection on `initialise()` (cosine
  distance, sized to `vector_size`, idempotent) and exposes `close()`. Previously
  the collection had to be created out-of-band before the first `upsert`.

### Fixed

- **`QdrantVectorStore` search** now uses `query_points` instead of the removed
  `AsyncQdrantClient.search`, restoring compatibility with `qdrant-client`
  >= 1.12 (the method was dropped upstream).

## [26.05.30] - 2026-05-31

### Added

- **`fireflyframework_agentic.content.binary`** — a host-agnostic binary
  normalisation stack that turns uploaded files (PDF, Office, images,
  archives, emails) into consumer-ready `BinaryArtifact` rows for document
  loaders or multimodal LLMs. Plain classes + a `BinaryConfig` DTO (no DI
  framework), pluggable `OfficeConverter` (Gotenberg / LibreOffice / NoOp)
  via `build_office_converter`. New optional extra `[binary]`
  (pypdf, Pillow, pillow-heif, cairosvg, py7zr, extract-msg). This unifies
  the normalizers previously duplicated in the flycanon and flydocs services.

### Removed (BREAKING)

- **RAG subsystem** — deleted `fireflyframework_agentic.rag` (CorpusAgent,
  SqliteCorpus, StoredChunk, ChunkHit, HybridRetriever, reciprocal_rank_fusion,
  ingest/retrieval pipelines) and `tools.builtins.corpus_rag`. Consumers that
  used the corpus dataclasses / hybrid retriever should vendor them (flycanon
  now owns its `StoredChunk`/`ChunkHit`/`HybridRetriever` locally). The
  reusable `embeddings`, `vectorstores`, `content` and `storage` modules are
  unchanged.
- **MCP subsystem** — deleted `fireflyframework_agentic.exposure.mcp` (server,
  HTTP CLI, OAuth/Entra auth, transports), the `firefly-mcp-http` console
  script, and the `mcp` + `corpus-search` optional extras.
- **`corpus_search` example** and its docs (`corpus-search-overview`,
  `use-case-corpus-search`, `comparison-vs-qmd`, `deploy/mcp-corpus-auth`,
  `deploy/corpus-persistence`), the `.mcp.json.template`, and the MCP-server
  `Dockerfile`.
- **Azure deployment/infra** — removed the `deploy-mcp.yml` workflow (Azure
  Container Apps deploy of the MCP server), the Azurite / Azure-OIDC /
  Key Vault machinery from the nightly workflow, the `azure` optional extra
  (azure-identity / azure-keyvault-secrets / msal / azure-monitor exporter),
  the Application Insights / Azure Monitor OTel exporter from
  `observability.exporters` (observability stays vendor-neutral: console /
  OTLP), and the dead Entra ID config fields. **Kept** the `AzureEmbedder`
  Azure OpenAI model provider (`azure-embeddings` extra).
- **MarkItDown** — removed the Microsoft `markitdown` document converter:
  deleted `content.loaders` (`MarkitdownLoader` + the `loaders` package) and
  the `markitdown` optional extra. Services that relied on the universal
  MarkItDown loader now use native per-format loaders.
- Dead Azurite test fixture (and its `mcr.microsoft.com/azure-storage/azurite`
  image reference) and the stale corpus / MCP / Azure entries in
  `.env.template`.

### Changed

- `markdown-it-py` (used by `content.markdown_chunker`) is promoted from the
  removed `markitdown` extra to a core dependency.
- CI (`pr-gate`, `nightly`) install `--extra binary` and no longer install
  the removed `mcp` / `corpus-search` / `azure` / `markitdown` extras.

## [26.05.29] - 2026-05-29

### Added

- **State-based pipelines, unified on `PipelineEngine`.** `PipelineBuilder`
  gains an opt-in `state=` mode: pass a Pydantic model
  (`PipelineBuilder(name, state=SomeModel)`) and nodes become
  `async (state) -> dict | None` functions over a typed shared state instead
  of port-wired DAG steps. `add_node(fn)` derives the node id from
  `fn.__name__`, the first node added is auto-detected as the entry point, and
  the legacy port-based mode is unchanged. There is a single executor:
  `PipelineEngine` runs both modes — `PipelineBuilder(state=...)` simply
  constructs an engine configured with `state_schema`, `recursion_limit`,
  `audit_log`, `checkpointer`, `event_handler`, and any routers registered via
  `.branch(...)`. State-mode runs go through a cycle-aware frontier scheduler
  and execute independent nodes concurrently (#147, #245).
- **Reducers for merge semantics.** Field-level merge is declared with
  `Annotated[T, reducer]` on the state model. Four reducers ship from
  `fireflyframework_agentic.pipeline`: `replace` (default), `append`, `extend`,
  and `merge_dict`. Each node returns a partial dict and the engine folds it
  into shared state per the declared reducer, so concurrent fan-out workers
  accumulate rather than clobber.
- **Unified branching via `.branch(source, router, mapping=None)`.** One call
  replaces the legacy `BranchStep`/`FanOutStep` (now soft-deprecated with a
  `DeprecationWarning`). With no mapping the router returns a target node id
  directly; with a mapping it returns an abstract label that resolves to a
  node. `PipelineEngine.to_mermaid()` renders branch-edge labels from the
  registered mappings, and `DAG.to_mermaid()` / `DAG.to_json()` export any DAG.
- **Cycles and `Send` fan-out for agentic loops.** State-mode DAGs are built
  with `allow_cycles=True`, so a node can route back to itself (or an earlier
  node) for ReAct loops and retry-with-critique. A `recursion_limit` kwarg
  (default `25`) bounds runaway cycles with a clean failure result via a
  per-node visit counter. A router may return `list[Send]` (`Send(target,
  payload)`) for runtime fan-out: each worker runs concurrently over its own
  payload-merged state copy and the results reduce back into shared state, with
  per-target visit counters preserved for observability.
- **Human-in-the-loop pause gates.** A node returning the `Pause(reason=...)`
  sentinel halts the pipeline cleanly and writes a paused checkpoint
  (`CheckpointRecord` gains backward-compatible `paused` / `pause_reason`
  fields). The result carries `paused` / `paused_node` / `pause_reason`, and an
  event handler can observe `on_node_pause`. Pauses are sticky: resuming
  requires `invoke(run_id=..., approve_pause=True)`, which restarts from the
  successor of the paused node; resuming without it raises `PipelineError`.
- **Checkpoint, resume, and mid-pipeline entry.** `FileCheckpointer` persists
  state after each successful node; `invoke(run_id=...)` resumes from the latest
  checkpoint, skipping completed nodes. `invoke(state, start_at=node)` jumps
  into a pipeline mid-flow with an explicit state — useful for replays and
  partial reruns.
- **Pipeline audit log.** New `pipeline/audit.py` exports a split protocol —
  `AuditLog` (write-only) and `QueryableAuditLog` (adds `list_entries`) — over
  an `AuditEntry` model, plus three concrete backends that wrap stdlib /
  framework primitives: `FileAuditLog` (JSONL per pipeline + run id,
  queryable), `LoggingAuditLog`, and `OtelAuditLog`. Every node visit is
  recorded with its status, including `paused`.
- **Unified `EventHandler` protocol and OTel spans.** A single `EventHandler`
  protocol (with `PipelineEventHandler` as the built-in implementation) covers
  both pipeline modes. State-mode spans use the `pipeline.state.*` taxonomy so
  existing observability dashboards keep working.
- **`examples/software_factory/` example.** A self-contained package that
  exercises the headline state-mode features end to end: typed state with
  reducers, router-driven branching with a `qa → codegen` cycle
  (`recursion_limit=3`), checkpoint/resume on a transient builder failure, and
  `StatePipelineEventHandler` progress output. It also ships plug-and-play
  durable backends — `checkpointers/{postgres,redis}.py` and
  `audit/postgres.py`, each a flat ~50–80 LOC class against a caller-supplied
  connection — swappable via the `FIREFLY_CKPT` env var.
- **Contradiction surfacing in the corpus answerer.** Both the fast-path and
  reasoning prompts gain a MUST rule: when two or more retrieved chunks
  disagree on the same fact, the answer must surface the conflict and cite the
  competing sources rather than silently picking one. Verified against
  contradicting fixtures (e.g. the same quarter's revenue reported as two
  different figures).

### Changed

- **Durable checkpointer / audit backends now live in examples, not the
  framework.** `PostgresCheckpointer`, `RedisCheckpointer`, and
  `PostgresAuditLog` (and the internal `PsycopgBackend` helper) have been
  dropped from the framework; the `psycopg[binary]` dependency is removed from
  the `[postgres]` extra. The `Checkpointer` and `AuditLog` protocols plus the
  framework-native `FileCheckpointer`, `FileAuditLog`, `LoggingAuditLog`, and
  `OtelAuditLog` remain. Operators who need a database-backed store implement
  the protocol against their own connection — see the ~50–80 LOC reference
  classes under `examples/software_factory/`.

### Fixed

- **`IngestLedger` now records fetch failures.** A failed fetch previously
  advanced the cursor without writing anything, so files silently disappeared
  from the ledger. Each failure is now recorded so retries and audits can
  observe it (#219).
- **`StructuredRetriever` works on cloud backends.** The retriever was
  hardcoded to `self.root / "corpus.sqlite"`, which broke on
  `AzureBlobBackend` where the SQLite database lives in blob storage. It now
  routes through `_db_store.ensure_fresh()`, materialising a local copy on
  cloud backends and remaining a no-op on `LocalBackend` (#219).
- **`firefly-mcp-http` now wires OpenTelemetry exporters at startup.** A
  `_configure_telemetry()` helper runs at the top of `main()`, before any
  framework code records a measurement, so when
  `APPLICATIONINSIGHTS_CONNECTION_STRING` is set the metrics and traces
  actually reach Application Insights. Resolves the operator-reported "App
  Insights is empty despite the connection string being set".

### Changed (dependencies)

- **`pydantic-ai` upgraded `1.75 → 1.99` and `mistralai` un-pinned.** With
  `mistralai` back on PyPI (2.4.5), the `[tool.uv.sources]` git workaround is
  removed and the `pydantic-ai` floor is lifted to `>=1.99.0`. The `Mistral`
  import now targets the 2.x layout (`mistralai.client`).

### Internal

- **Inline imports lifted to module top-level across the codebase** for
  project-rule compliance, with optional-dependency imports guarded via
  `TYPE_CHECKING` so pyright narrows correctly without importing at runtime.
  No behavioural change.
- **PR-gate CI sped up** with shallow checkout, no coverage on PRs, and a
  cached `uv` resolver across jobs (#218).
- **Cost-tracking docs** now point users at `examples/cost_tracking.py` for the
  cost-resolver override pattern.
## [26.05.21] - 2026-05-21

### Changed (BREAKING — delegation routing API)

- **`DelegationStrategy.select()` replaced by `decide() -> RoutingDecision`.**
  Strategies now return ranked, scored `Candidate` tuples plus metadata
  instead of a single agent. No deprecation shim: a shim would lock in
  the single-agent return shape we are explicitly escaping. External
  implementers get a clean `Protocol` mismatch at type-check time.
  `DelegationRouter.route()` keeps its exact current signature, so the
  common call site is unaffected. New combinators `ChainStrategy`,
  `FallbackStrategy`, and `WeightedStrategy` nest strategies without
  subclassing; `DelegationRouter.decide()` / `execute()` split selection
  from execution and emit a `firefly.routing.decision` OTel event.
- **`CapabilityStrategy` and `ContentBasedStrategy` now return empty
  decisions instead of raising / silently falling back.** Previously
  `CapabilityStrategy` raised `DelegationError` on no-match (blocking
  composition with fallback) and `ContentBasedStrategy` silently
  returned the first agent on LLM failure (hiding errors). Both now
  return empty `RoutingDecision` objects. Callers using bare
  `router.route()` still see `DelegationError("Empty routing
  decision")` from `execute()` — same exception class, different
  message.
- **`CostAwareStrategy` no longer carries a hardcoded model→tier
  table.** Cost per agent is computed via `resolve_cost` from
  `fireflyframework_agentic.observability.cost_resolvers` against a
  synthetic `CostContext` (defaults: 1000 input / 500 output tokens),
  and scores are pool-relative linear normalisations. New keyword
  arguments configure the sample tokens, the resolver chain, and the
  `on_unknown` policy (`"skip"` / `"lowest"` / `"raise"`).

### Added

- **Tool-using corpus answer agent.** `CorpusAgent` gains an
  `answer_strategy: Literal["fast", "reasoning"] = "fast"` constructor
  flag. The fast path is unchanged (one-shot expand → retrieve → rerank
  → answer); the reasoning path delegates the answer phase to a new
  `ReasoningAnswerAgent` (in `fireflyframework_agentic.rag.retrieval`)
  that runs a tool-using ReAct loop over four tools:
  `knowledge_search`, `sql_query`, `inspect_table`, and a restricted
  Python `python_compute` sandbox. Construction adds three tunables
  (`max_reasoning_tool_calls`, `max_reasoning_llm_calls`,
  `reasoning_wall_clock_seconds`). Default behaviour is unchanged.
- **`Answer.reasoning_trace`** — new optional field of type
  `ReasoningTrace | None` (default `None`). Populated by
  `ReasoningAnswerAgent` when `CorpusAgent.query(..., include_trace=True)`
  is set. Every `ActionStep` carries `tool_name + tool_args` (a plain
  dict), so a recorded trace is re-executable: see
  `tests/examples/corpus_search/test_trace_is_replayable.py`.
- **MCP `corpus_query` tool** gains two optional params, `strategy` and
  `include_trace`. `include_trace` defaults to `True` — callers that hit
  the reasoning path receive the typed `ReasoningTrace` in the response
  without opting in. The fast path never populates a trace regardless of
  the flag, so the legacy fast-path JSON shape is unchanged. Pass
  `include_trace=false` to opt out (smaller payload). Process-wide agent
  cache keys by `(corpus_id, strategy)` so both paths can coexist for the
  same corpus.
- **New optional extra `[reasoning-eval]`** pulls in `numpy>=2.0` and
  `pandas>=2.2` for the `python_compute` sandbox. The sandbox itself is
  AST-validated (denylist on dunder names, `eval`/`exec`/`compile`/
  `__import__`/`open`/`input`, attribute access to dunder names like
  `__class__`/`__bases__`), runs in a worker thread with a 5 s wall-clock
  timeout, and caps combined stdout + result rendering at 8 KB.
- **Reasoning telemetry.** Two new OTel instruments: histogram
  `firefly.rag.reasoning.tool_call_duration` (labelled by `tool_name`)
  and counter `firefly.rag.reasoning.terminal_state` (labelled by
  outcome — `answered | no_info | tool_limit | llm_limit | timeout |
  error`). The existing `firefly.rag.query` span gains a
  `firefly.rag.answer_strategy` attribute on both fast and reasoning
  paths.

### Changed (BREAKING — internal layout)

- **Per-corpus token store is now provider-agnostic in the framework.**
  `fireflyframework_agentic.security.corpus_token` exports a
  `CorpusTokenStore` Protocol plus the in-memory `CorpusTokenCache` and
  the `corpus_token_digest` helper. The Azure-specific
  `KeyVaultTokenStore` + `build_default_store` factory moved to
  `examples/corpus_search/azure_security.py` alongside the existing
  Entra/OBO code. The `firefly-mcp-http` server resolves the concrete
  store at startup via the `FIREFLY_MCP_TOKEN_STORE_FACTORY` env var
  (defaults to `examples.corpus_search.azure_security:build_default_store`)
  so existing Azure deployments keep working, and operators on a
  different back-end can swap the factory without touching the
  framework. The `firefly-mcp-token` CLI moved to
  `examples/corpus_search/firefly_mcp_token.py` and is no longer
  registered as a top-level script; invoke it as
  `python -m examples.corpus_search.firefly_mcp_token …`.

### Changed (BREAKING for clients of the auth flag)

- **`firefly-mcp-http` per-corpus auth now requires the
  `X-Firefly-Corpus-Id` header on every gated request** (in addition to
  `Authorization: Bearer …`). The middleware validates the bearer against
  Key Vault before letting any request through — including the
  JSON-RPC handshake, `tools/list`, and `list_corpora` — closing the gap
  where an outsider could enumerate tool schemas or corpus_ids by
  sending only a bearer-shaped string. Body-side `arguments.corpus_id`
  must match the header value for corpus-scoped tools. Update Claude
  Desktop / `mcp-remote` entries to pass `--header
  X-Firefly-Corpus-Id: <id>`.

### Fixed

- **SQL agent reasoning: discriminator filters, parent-level GROUP BY, and
  sibling-column scans.** The text-to-SQL retriever now annotates each
  string column in the schema context with its
  `COUNT(DISTINCT)` cardinality (e.g. `metric_line (string, 3 distinct)`)
  so the agent can spot categorical / discriminator axes and parent-vs-
  child cardinality gaps at schema-read time. The system prompt gains
  three rules and three worked examples covering: filtering on a
  discriminator before aggregating heterogeneous rows (#161), using
  `GROUP BY <parent>` when the user says "by X" / "for each X" / "per
  X" (#162), and scanning semantically-related sibling columns before
  concluding "no record" on a NULL result (#163). No new tools or
  schema-model fields.

- **`firefly-mcp-http` now loads `.env` on startup.** The CLI calls
  `load_dotenv(find_dotenv(usecwd=True))` at the top of `main()`, so a
  developer running the server from a project directory gets its
  variables (e.g. `EMBEDDING_MODEL`, `FIREFLY_MCP_KEYVAULT_URL`)
  without an explicit shell `source`. Real process env vars always win
  — `load_dotenv` defaults to `override=False` — so Azure /
  Container Apps deployments (which inject env from the manifest
  before the process starts) see no behavioural change. `python-dotenv`
  is now a core dependency (previously declared only under the
  `corpus-search` / `dev` extras); promoted so the import in `main()`
  can be unconditional rather than guarded. Resolves the `KeyError:
  'EMBEDDING_MODEL'` operators hit when running `firefly-mcp-http`
  locally with a `.env` present.

- **`firefly-mcp-http` logs unhandled asyncio task exceptions to stderr
  before the loop has a chance to die silently.** Previously, an
  exception in a task scheduled on the asyncio loop (request-cleanup
  callbacks, fire-and-forget tool work, SSE long-poll teardown) was
  routed by ``BaseEventLoop`` to the ``asyncio`` logger at ERROR — but
  uvicorn's default log config doesn't surface that logger. Operators
  saw "the server died" / "the bridge can't reconnect" with no
  traceback. The CLI now installs a loop-level exception handler that
  routes through ``logging.getLogger("…http_cli")`` (which
  ``basicConfig`` wires up at startup, level overridable via
  ``FIREFLY_MCP_LOG_LEVEL``), preserving the exception's traceback via
  ``exc_info=``. Does NOT swallow exceptions or change loop behaviour
  — only makes them visible.

- **LocalBackend corpus state now lives under `CORPUS_ROOT`, not in
  `~/.cache/`.** `DatabaseStore` previously kept its working copy at
  `~/.cache/fireflyframework_agentic/dbstore/<store_id>/db.sqlite` for
  every backend, and `LocalBackend.upload`/`download` `shutil.copyfile`'d
  between that cache and the file under `CORPUS_ROOT`. The two copies
  could drift, and a `rm -rf $CORPUS_ROOT` did **not** reset corpus state
  (the dedup ledger and embeddings stayed alive in the cache,
  re-ingestion silently skipped every file). The store now reads
  `StorageBackend.local_path` at construction; for `LocalBackend` it
  co-locates the working copy with the backend file (same inode, no
  duplicate), and every file used by a corpus — SQLite, WAL/SHM, the
  metadata sidecar, the lock sentinel — lives under the configured
  root. `LocalBackend.upload` / `download` short-circuit when source
  and destination are the same inode, so the existing call sites
  needed no changes. Remote backends (`AzureBlobBackend`) keep the
  legacy cache-dir layout because their working copy MUST be a separate
  local file. Operators upgrading should
  `rm -rf ~/.cache/fireflyframework_agentic/dbstore/corpus_search:` to
  reclaim disk; the new layout takes effect automatically on next
  startup (#170).

- **Answerer preserves diacritical marks in non-English responses.** The
  RAG answerer's instructions now tell the model to answer in the same
  language as the question and to keep correct orthography
  (`á`/`é`/`í`/`ó`/`ú`/`ñ`/`ü`/`ç`/`à`/`è`/`ê`/`ô` and equivalents)
  rather than transliterating to ASCII. Resolves the regression where
  Spanish answers came back as `produccion`/`aprobacion`/`Cual?` instead
  of `producción`/`aprobación`/`¿Cuál?` (#157).

### Added

- **`list_corpus_schemas` and `corpus_sql` MCP tools.** Two new read-only
  entrypoints that expose the structured side of a corpus directly,
  without going through the LLM-driven `corpus_query` pipeline.
  `list_corpus_schemas(corpus_id)` returns every `TargetSchema` saved by
  `ingest_corpus_structured` (column names, types, primary/foreign keys,
  units) so a host can discover what's queryable; `corpus_sql(corpus_id,
  sql, params?, limit?)` runs a single `SELECT` and returns raw rows.
  Safety: the connection is opened in SQLite `mode=ro` so writes
  physically cannot land, the SQL is parsed with sqlglot and only
  `SELECT` is accepted, and table references are whitelisted against the
  schema registry — internal tables (`chunks`, `_schemas`, `ingestions`,
  …) are rejected. Adds `sqlglot>=26.0.0` to the `corpus-search` extra.
- **Optional `unit` field on `ColumnSpec`.** Schemas can now declare the
  human-readable unit a numeric column stores (`"USD millions"`,
  `"headcount"`, `"percent"`, `"days"`, …). The SQL retriever's schema
  context surfaces it to the agent as `name (type, unit=…)`, the
  retriever's system prompt requires the agent to preserve the unit in
  SELECT results (via alias or co-selection), and the answerer is
  instructed to quote the unit alongside any numeric quantity it cites
  — or to flag the ambiguity explicitly when no unit is known, rather
  than presenting a unit-less number the user cannot verify (#158).
- **`firefly-mcp-token` CLI** for operators managing per-corpus tokens
  in Azure Key Vault. Commands: `create`, `rotate`, `revoke`, `list`,
  `show-name`. Uses `DefaultAzureCredential`; the minted token goes to
  stdout (pipe-friendly), status to stderr. Registered as a
  `[project.scripts]` entry alongside `firefly-mcp-http`.
- **Fuzzy entity matching in the SQL retriever.** The agentic inspect-loop
  gains a `find_similar` op on `inspect_table` that tokenises the user's
  value on whitespace and matches accent-folded, case-insensitive
  substrings (AND-of-LIKEs, with OR fallback). A new `unaccent_lower(col)`
  SQL UDF is registered on every connection so the LLM can write
  diacritic-tolerant filters in `run_select`. The system prompt now
  steers the LLM to probe `find_similar` for free-text entity columns
  and to retry rather than stop when an equality filter returns 0 rows.
- **`numeric_summary` op on `inspect_table` in the SQL retriever.** Returns
  total rows, non-null count, null count, sum, min, max, and *two* mean
  variants — `mean_excluding_nulls` (SQL default `AVG`) and
  `mean_blanks_as_zero` (treats NULL cells as 0). The two means diverge
  whenever the column carries NULLs, so the agent can detect the
  blank-as-zero spreadsheet convention and pick the right
  interpretation instead of silently averaging over the smaller
  non-null subset. The system prompt now steers the LLM to probe
  `numeric_summary` before averaging numeric columns, and to surface
  both interpretations when ambiguous.
- **Per-corpus capability tokens for `firefly-mcp-http`.** When
  `FIREFLY_MCP_CORPUS_AUTH_ENABLED=true`, every MCP tool call must
  present a bearer matching the `firefly-mcp-corpus-token-<corpus_id>`
  secret in the Azure Key Vault at `FIREFLY_MCP_KEYVAULT_URL`. A token
  leak now exposes one corpus, not the whole server. `list_corpora` is
  filtered to the caller's authorised corpora. Off by default; stdio
  transport and existing ingress-fronted HTTP deployments are
  unaffected. See `docs/deploy/mcp-corpus-auth.md`.

## [26.05.11] - 2026-05-11

### Changed (BREAKING)

- **Repo layout flattened.** `src/fireflyframework_agentic/` moved to
  `fireflyframework_agentic/` at the repo root. Vendor- and example-specific
  code (`cli/`, vendor backends, SharePoint source, the `corpus_search`
  reference agent's CLI) moved under `examples/corpus_search/`. The
  `storage-azure` extra and the previous top-level `[project.scripts]`
  block were removed (#134, #137).
- **`corpus_retrieve` → `knowledge_search`.** The MCP corpus retrieval tool
  was renamed for clarity (#134). Update any client code or MCP wiring that
  referenced `corpus_retrieve`.
- **`firefly-mcp-http` entry point relocated.** Now registered as
  `fireflyframework_agentic.exposure.mcp.http_cli:main` in
  `[project.scripts]`. The MCP HTTP server is a first-class deliverable of
  the package, not an example (#139). Closes #138.

### Added

- **Unified structured + unstructured ingestion in `corpus_search`.**
  `CorpusAgent.ingest_source` accepts both tabular and document sources
  through a single pipeline, with separate retrievers feeding the
  answerer's prompt (#108).
- **Schema-aware structured ingestion.** Discover-review-ingest workflow
  for tabular sources: schema discovery first, then per-column review,
  then ingest only the approved columns. Closes #117 (#118).
- **`RubricReviewer`.** Rubric-based grader loop for validation; LLM judges
  candidate outputs against an explicit rubric and feeds back deltas for
  retry. Exposed from `validation` (#130).
- **Managed SQLite storage backends.** Local-file and Azure Blob backends
  expose a uniform managed-SQLite surface for memory and other persistence
  needs (#112).
- **`list_corpora` MCP tool.** Discovery endpoint that enumerates available
  corpora; nightly e2e test added to keep it honest (#115).

### Fixed

- **Nightly auth via Key Vault + OIDC.** Replaced direct
  `${{ secrets.ANTHROPIC_API_KEY }}` injection with `azure/login` (OIDC)
  followed by `az keyvault secret show` against `kv-firefly-signature`.
  The previous wiring resolved to empty strings and broke every
  Anthropic-using test on the nightly (#120, follow-up #137). Closes #125.
- **MCP container deploy.** Repaired the `Dockerfile` `COPY` paths and
  console-script entry point so `deploy-mcp` builds and pushes again
  after the flat-layout move (#139). Closes #138.
- **Retrieval benchmark.** `runner.py` now ingests only `*.md` files; the
  25,870-row billing-ledger CSV was being fed through the markdown
  chunker, producing ~24k chunks and corrupting the SQLite-vec store.
  Smoke test updated for the 12-doc corpus (#140).
- **Structured ingest folder walks.** Filter to tabular file types so
  non-tabular files in mixed corpora don't trip the structured loader
  (#123).
- **Real-LLM e2e tests.** Switched `test_e2e_real_llm` to Azure OpenAI
  embeddings to align with the production embedder path (#119).

### Changed

- **No hardcoded VERSION constants in installers.** `install.sh`,
  `install.ps1`, and their `uninstall.*` counterparts no longer carry a
  hand-bumped `VERSION` string; the post-install verify reads
  `fireflyframework_agentic.__version__` from package metadata (#136).
- **`.python-version` removed.** `pyproject.toml`'s
  `requires-python = ">=3.13"` is the sole source of truth (#136).
- **`CLAUDE.md` gitignored.** Developer-local agent guidance is no longer
  tracked (#136).
- **Dependabot bumps.** `urllib3` 2.6.3 → 2.7.0 (#135);
  `langchain-core` 1.3.2 → 1.3.3 (#124).
- **CI hardening.** `deploy-mcp.yml` bumped `actions/checkout@v4 → @v6`
  and SHA-pinned `docker/setup-buildx-action` to v4.0.0 to clear the
  Node 20 deprecation (#137).

### Tests

- **`tests/examples/corpus_search/` consolidated.** Vendor backend tests
  and the structured-ingestion ledger test moved under the example's tree
  alongside their production code (#110, #111).
- **Benchmark smoke test** updated to assert the new 12-md corpus shape
  after the runner fix (#140).

## [26.04.30] - 2026-04-30

### Added

- **Entra ID security.** Token verification and on-behalf-of (OBO) exchange
  for Azure AD authentication flows. New `[azure]` extra installs the
  required dependencies (#92).
- **MCP server.** New exposure module ships an MCP server and the
  `firefly-mcp` CLI for exposing agents over the Model Context Protocol
  (#93).
<!--
The hexagonal ingestion module described in #84 (RawFile/TypedRecord
ports, SharePointSource, DuckDBSink, firefly-ingest CLI, [ingestion-*]
extras) did not ship in v26.04.30 -- the source tree at HEAD has no
`fireflyframework_agentic/ingestion/` package and `pyproject.toml` does
not register `firefly-ingest` as a script. Track in a follow-up release.
-->

- **Corpus-search example agent.** New `examples/corpus_search/` ships a
  folder-ingestion + hybrid-search agent: `markitdown` → chunk → embed
  (Azure OpenAI by default) → SQLite FTS5 + Chroma. Query pipeline is
  expand (Haiku) → BM25 + vector → RRF fuse → rerank (Haiku) → answer
  (Sonnet) with inline citations. Framework additions:
  `content/loaders/MarkitdownLoader` and
  `pipeline/triggers/FolderWatcher`. New extras: `[markitdown]`,
  `[watch]`, `[corpus-search]` (#82).
- **SQLite memory store.** New `SQLiteStore` provides stdlib-backed local
  persistence for memory, sitting alongside `FileStore` with the same
  surface (#87).
- **Refactored prompt manager.** New prompt implementation with template
  scheme, registry, and explicit `Prompt` type used by reasoning prompts
  (#85).
- **Nightly CI workflow.** Full test suite runs once per day under the
  `nightly` pytest marker, separated from the per-PR `pr-gate`. On
  failure, the workflow opens (or comments on) a `nightly-failure`
  tracking issue; a subsequent green run auto-closes it. README gains a
  Nightly badge alongside PR gate (#89).

### Changed

- **Security extra renamed.** `entra.py` → `azure.py`; the security manager
  now inherits from `RBACManager`. Extra `[entra]` → `[azure]` and is
  installed in the PR gate.
- **Memory store layout.** `SQLiteStore` lives in `store.py` and is aligned
  with the other stdlib backends.
- **`EmbeddingResult.usage` is now `Optional`.** Backward-compatible change
  to support embedding backends that do not report usage (#82).
- **Examples simplified.** Use bare `load_dotenv()` and source `MODEL` from
  `.env`; removed `examples/_common.py` (#81).
- **CI rename.** Workflow `ci` → `pr-gate`; triggers only on
  `pull_request`, not on `push`.

### Fixed

- **Nightly perf benchmarks.** Replaced the broken
  `benchmark(lambda: pytest.asyncio.fixture(coro))` pattern with sync
  tests driven by a shared `bench_loop` event-loop fixture (required so
  `HttpTool`'s `httpx.AsyncClient` stays bound to a single loop across
  iterations). Test classes dropped per project convention; `skipif` and
  `benchmark(group=...)` decorators moved onto each function (#91).

### Tests

- **Test tree reorganized** under `tests/unit/` for agents, memory,
  observability, pipeline, tools, resilience, and core (#88).
- **Responsible AI category** (`tests/responsible_ai/`) groups
  `output_guard` and `prompt_guard`.
- **Benchmarks moved** to `tests/performance/`, marked `nightly`, and
  renamed to `test_bench_*.py` for pytest collection.
- **Tests README** documents per-category descriptions and the nightly
  marker.

## [26.04.28] - 2026-04-28

### Changed (BREAKING)

- **Project rename: `fireflyframework-genai` → `fireflyframework-agentic`.**
  Comprehensive rebrand from `genai` to `agentic` across every public surface.
  See `MIGRATION` section below for an upgrade checklist.
  - Python module: `fireflyframework_genai` → `fireflyframework_agentic`.
  - PyPI package: `fireflyframework-genai` → `fireflyframework-agentic`.
  - Class names: `FireflyGenAI*` → `FireflyAgentic*` (covers `FireflyGenAIConfig`
    and `FireflyGenAIError`).
  - Environment-variable prefix: `FIREFLY_GENAI_*` → `FIREFLY_AGENTIC_*`.
  - REST factory: `create_genai_app()` → `create_agentic_app()`.
  - Repository URLs: `github.com/fireflyframework/fireflyframework-genai` →
    `…/fireflyframework-agentic`.
  - Brand prose: "Firefly GenAI" → "Firefly Agentic".

  Mentions of "GenAI" as a *category* (e.g. "GenAI metaframework", "GenAI
  workloads", `keywords = ["genai"]`) are intentionally preserved -- the
  framework targets the GenAI domain. References to the external
  `genai-prices` library and the `GenAIPricesCostCalculator` wrapper class
  also remain.

### Removed (BREAKING)

- **Studio extracted to its own repository.** The visual IDE, project runtime,
  scheduler, tunnel, code generation, and AI assistant now live in
  [fireflyframework-agentic-studio](https://github.com/fireflyframework/fireflyframework-agentic-studio).
  Removed from this repo:
  - `src/fireflyframework_agentic/studio/` (Python module).
  - `studio-frontend/` (SvelteKit SPA).
  - `studio-desktop/` (Tauri desktop bundle and PyInstaller spec).
  - `scripts/build_studio.py`.
  - `tests/test_studio/` (~30 test files).
  - Studio-only docs: `studio.md`, `studio-agents.md`, `api-reference.md`,
    `scheduling.md`, `tunnel-exposure.md`, `input-output-nodes.md`,
    `project-api.md`, `tutorial-bpm-pipeline.md`.
  - `examples/studio_launch.py`.
  - `.github/workflows/desktop.yml` (Tauri build pipeline).
  - `[studio]` extra in `pyproject.toml` (FastAPI, Uvicorn, Strawberry-GraphQL,
    APScheduler).
  - `firefly` CLI entry point (now ships with the studio package).
  - `frontend-build` job and studio artifact wiring in CI.

### Added

- **Pre-commit hooks.** `.pre-commit-config.yaml` with ruff (lint + format),
  file hygiene (trailing whitespace, EOF, YAML/TOML/JSON validation,
  merge-conflict markers, large-file guard, AST check), `gitleaks` for secret
  scanning, and `no-commit-to-branch` for `main`/`master`. CI gains a
  `Pre-commit` job that runs the same hooks on every PR so `--no-verify`
  bypasses are caught.

### Migration

```diff
- pip install fireflyframework-genai
+ pip install fireflyframework-agentic
```

```diff
- from fireflyframework_genai import FireflyGenAIConfig, get_config
+ from fireflyframework_agentic import FireflyAgenticConfig, get_config

- from fireflyframework_genai.exposure.rest import create_genai_app
+ from fireflyframework_agentic.exposure.rest import create_agentic_app
```

```diff
- FIREFLY_GENAI_DEFAULT_MODEL=...
+ FIREFLY_AGENTIC_DEFAULT_MODEL=...
```

For users who previously installed the embedded Studio:

```diff
- pip install "fireflyframework-genai[studio]"
+ pip install fireflyframework-agentic-studio
```

A bulk replace covers most call sites:

```bash
grep -rl 'fireflyframework_genai' . | xargs sed -i 's/fireflyframework_genai/fireflyframework_agentic/g'
grep -rl 'fireflyframework-genai' . | xargs sed -i 's/fireflyframework-genai/fireflyframework-agentic/g'
grep -rl 'FireflyGenAI'           . | xargs sed -i 's/FireflyGenAI/FireflyAgentic/g'
grep -rl 'FIREFLY_GENAI_'         . | xargs sed -i 's/FIREFLY_GENAI_/FIREFLY_AGENTIC_/g'
```

The full migration guide for Studio users lives in the
[fireflyframework-agentic-studio README](https://github.com/fireflyframework/fireflyframework-agentic-studio#migration-from-fireflyframework-agenticstudio).

### Changed

- **Middleware Protocol** -- Renamed `before`/`after` to `before_run`/`after_run`
  on `PromptCacheMiddleware` and `CircuitBreakerMiddleware` to conform to the
  `AgentMiddleware` protocol contract.
- **Exception Hierarchy** -- Renamed `MemoryError` to `FireflyMemoryError` to
  avoid shadowing the Python built-in.  A deprecated alias is kept for backwards
  compatibility.
- **Quota Defaults** -- `quota_enabled` now defaults to `False` to avoid
  unexpected enforcement on first install.
- **Cost Calculator Type** -- `cost_calculator` config field is now
  `Literal["auto", "genai_prices", "static"]`.

### Security

- **ShellTool** -- Replaced `create_subprocess_shell` with
  `create_subprocess_exec` to prevent command-injection via shell metacharacters.
- **FileSystemTool** -- Replaced `str.startswith` path check with
  `Path.is_relative_to` to prevent symlink-based path traversal.
- **RBAC Decorator** -- Fixed `require_permission` to use `inspect.signature`
  for positional argument binding and replaced `nonlocal` mutation with local
  `manager` variable.
- **Encryption** -- Each `AESEncryptionProvider.encrypt()` call now generates a
  random 16-byte salt for PBKDF2 key derivation, stored as
  `salt[16]+nonce[12]+ciphertext+tag`.
- **REST Middleware** -- `allow_credentials` is now automatically set to `False`
  when `allow_origins=["*"]`.  API key comparison uses `hmac.compare_digest`.
- **REST Router** -- Exception details are no longer exposed to clients; errors
  are logged server-side and a generic message is returned.
- **Database Store** -- Schema name is validated against `^[a-zA-Z_][a-zA-Z0-9_]*$`
  to prevent SQL injection.
- **FileStore** -- Added `Path.is_relative_to` check in `_path()` to prevent
  namespace-based path traversal.

### Fixed

- **Thread Safety** -- Added `threading.Lock` to `InMemoryStore`, `CachedTool`,
  `RateLimitGuard`, `ConversationMemory.get_turns/get_total_tokens/clear/
  clear_all/new_conversation/conversation_ids`.
- **Pipeline Engine** -- `_gather_inputs` now correctly extracts `output_key`
  from dict and object results.  `started_at` is initialised before the retry
  loop.
- **asyncio.run Crash** -- `database_store.py` and `manager.py` sync wrappers
  now detect a running event loop and offload to a `ThreadPoolExecutor` instead
  of crashing.
- **TextTool ReDoS** -- Regex operations in `_extract`, `_replace`, `_split` now
  run via `asyncio.to_thread` with a 5-second timeout.
- **SandboxGuard ReDoS** -- User-supplied patterns are compiled with a safe
  `_safe_compile` helper.
- **Observability Decorators** -- `@metered` now records latency in a `finally`
  block so it is captured even on exceptions.
- **Logging** -- `ColoredFormatter.format` now operates on a `copy.copy(record)`
  to avoid mutating shared log records.
- **SlidingWindowManager** -- Uses `collections.deque` and `_running_tokens`
  counter instead of re-estimating the entire window on every eviction.
- **PromptTemplate** -- Added `_UNSET` sentinel for `PromptVariable.default` so
  that `default=None` is correctly propagated.
- **Queue Consumers** -- Kafka, RabbitMQ, and Redis consumers now wrap
  `_process_message` in try/except to prevent one bad message from killing the
  consumer loop.
- **Goal Decomposition** -- `_execute_task` now passes `memory=memory` to the
  delegated `_task_pattern.execute()`.
- **ConversationMemory** -- `clear()` and `clear_all()` now also clear
  `_summaries` to prevent stale summary leaks.
- **Reasoning Registry** -- Six built-in patterns are auto-registered at import
  time.
- **Observability Exports** -- `extract_trace_context`, `inject_trace_context`,
  and `trace_context_scope` are now re-exported from `observability/__init__.py`.
- **UsageTracker** -- `_check_budget` exception handler now logs at DEBUG instead
  of silently passing.

## [26.02.07] - 2026-02-17

### Added

- **Multi-Provider Support Hardening** -- New `model_utils` module providing
  centralized model identity extraction (`extract_model_info`,
  `get_model_identifier`, `detect_model_family`) for uniform handling of both
  `"provider:model"` strings and `pydantic_ai.models.Model` objects across the
  framework's observability and resilience layers.

- **Cross-Provider Cost Tracking** -- `StaticPriceCostCalculator` now resolves
  pricing through proxy providers. `bedrock:anthropic.claude-3-5-sonnet-latest`
  maps to Anthropic pricing, `azure:gpt-4o` maps to OpenAI pricing, and
  `ollama:*` models report `$0.00`. Added Mistral pricing entries.

- **Bedrock Throttling Detection** -- `_is_rate_limit_error()` now detects
  AWS Bedrock `ThrottlingException` and `TooManyRequestsException` (boto3
  `ClientError` shapes) in addition to HTTP 429 and string-pattern matching.
  Also added `"throttl"` as a fallback string pattern.

- **Cross-Provider Prompt Caching** -- `PromptCacheMiddleware` now uses
  `detect_model_family()` to route caching configuration by model family
  rather than string matching. `bedrock:anthropic.claude-*` correctly routes
  to Anthropic caching; `azure:gpt-*` routes to OpenAI caching.

- **Model Object Fallback** -- `FallbackModelWrapper` now accepts
  `Sequence[str | Model]`, allowing cross-provider fallback chains with
  pre-configured `Model` objects (e.g. Azure → OpenAI → Anthropic).
  `run_with_fallback()` updates `_model_identifier` on each swap so cost
  tracking and rate-limit backoff keys remain accurate.

## [26.01.01] - 2026-02-10

### Changed

- **CalVer Migration** -- Migrated versioning scheme from `M.YY.Patch` to
  `YY.MM.Patch` for clearer calendar-based version identification. This
  release consolidates all changes from the previous `2.26.x` releases.

## [2.26.1] - 2026-02-09

### Removed

- **Studio / CLI / TUI** -- Removed the Firefly GenAI Studio package
  (`src/fireflyframework_genai/studio/`), the `flygenai` CLI entry point,
  the `[cli]` optional extra, all studio tests (`tests/test_studio/`), and
  studio documentation (`docs/studio.md`). The framework is now a pure
  library without any CLI or TUI components. Room persistence configuration
  fields have been removed from `FireflyGenAIConfig`.

## [2.26.1] - 2026-02-08

### Added

- **Database Persistence Backends** -- PostgreSQL and MongoDB support for
  production-grade conversation memory and working memory persistence.
  `PostgreSQLStore` and `MongoDBStore` implement the `MemoryStore` protocol
  with connection pooling via `asyncpg` and `motor`. Automatic schema/collection
  creation on first use. Configuration via environment variables or direct
  initialization. Install with `pip install fireflyframework-genai[postgres]`
  or `pip install fireflyframework-genai[mongodb]`.

- **Distributed Trace Correlation** -- W3C Trace Context propagation across
  service boundaries (HTTP, message queues, pipelines). Functions
  `inject_trace_context()` and `extract_trace_context()` for manual
  propagation. Automatic integration with REST API middleware, Kafka/RabbitMQ/
  Redis queue consumers, and pipeline context via `correlation_id`. Enables
  end-to-end trace correlation in distributed GenAI applications.

- **API Quota Management** -- Production-grade quota enforcement with
  `QuotaManager`, `RateLimiter`, and `AdaptiveBackoff`. Supports daily budget
  limits (USD), per-model rate limits (requests/minute), and exponential
  backoff with jitter for 429 responses. Sliding window rate limiting for
  accurate enforcement. Configuration via environment variables
  (`FIREFLY_GENAI_QUOTA_*`). Integrates with `UsageTracker` for unified cost
  and quota management.

- **Security Hardening** -- Four new security features for enterprise deployments:
  1. **RBAC** -- Role-Based Access Control with JWT authentication, role/permission
     management, multi-tenant isolation, and `@require_permission` decorator.
  2. **Encryption** -- AES-256-GCM encryption for data at rest via
     `AESEncryptionProvider` and `EncryptedMemoryStore` wrapper for transparent
     encryption of any `MemoryStore` backend.
  3. **SQL Injection Prevention** -- Automatic detection and blocking of 15+
     SQL injection patterns in `DatabaseTool` queries. Enforces parameterized
     queries and rejects string concatenation.
  4. **CORS Security** -- Restrictive CORS policy by default (no origins allowed).
     Explicit allow-list configuration for production via environment variables.

- **HTTP Connection Pooling** -- `HttpTool` now supports connection pooling via
  `httpx.AsyncClient` for 50-70% latency reduction on repeated requests.
  Configurable pool size, keepalive connections, and timeout. Automatic fallback
  to `urllib` when `httpx` not installed. Configuration via environment variables
  (`FIREFLY_GENAI_HTTP_POOL_*`). Async context manager support for cleanup.

- **Incremental Streaming** -- True token-by-token streaming mode for `FireflyAgent`.
  New `streaming_mode` parameter accepts `"buffered"` (default, chunk-based) or
  `"incremental"` (token-by-token). Incremental mode provides `stream_tokens()`
  method with optional `debounce_ms` parameter. REST API endpoints:
  `/agents/{name}/stream` (buffered) and `/agents/{name}/stream/incremental`.
  Both modes work with all middleware.

- **Batch Processing** -- `BatchLLMStep` for pipeline batch processing of multiple
  prompts through an agent concurrently. Supports both initial inputs and previous
  step outputs via flexible `prompts_key` parameter. Configurable batch size,
  completion polling, and per-batch callbacks. Automatic error handling captures
  individual prompt failures without blocking the batch. Respects all agent
  middleware including caching and circuit breakers.

- **Provider Prompt Caching** -- `PromptCacheMiddleware` enables provider-specific
  prompt caching for 90-95% cost reduction on cached tokens. Supports Anthropic
  (`cache_control`), OpenAI (`cached_content`), and Gemini (`cachedContent`)
  caching mechanisms. Automatic configuration based on model provider. Cache
  statistics tracking with hit rate and estimated savings calculation. Configurable
  system prompt caching, minimum token threshold, and TTL.

- **Circuit Breaker Pattern** -- `CircuitBreaker` and `CircuitBreakerMiddleware`
  for resilient agent execution. Three states: CLOSED (healthy), OPEN (rejecting
  requests), HALF_OPEN (testing recovery). Configurable failure threshold,
  recovery timeout, and success threshold. Prevents cascading failures and allows
  failing services time to recover. `CircuitBreakerOpenError` raised when circuit
  is open. Metrics tracking via `get_metrics()`.

- **Integration Test Suite** -- 11 comprehensive integration tests in
  `tests/integration/test_full_integration.py` covering all production features
  working together: agent with all middleware, streaming with middleware, pipeline
  with batch processing, memory persistence, circuit breaker with batch processing,
  cost guard with streaming, multiple agents sharing memory, and feature
  composition scenarios.

- **Examples and Documentation** -- Updated examples showing all features in
  production context: `examples/full_integration.py` (comprehensive production
  agent with all middleware), `examples/circuit_breaker.py` (resilience patterns),
  `examples/batch_processing.py` (batch API usage). Updated documentation in
  `docs/agents.md`, `docs/pipeline.md`, `docs/memory.md`, `docs/observability.md`,
  `docs/security.md`, and `docs/tools.md` with detailed usage examples and
  configuration guides.

### Fixed

- **Pipeline Data Flow** -- `BatchLLMStep` now correctly accesses previous step
  outputs via `context.get_node_result()` with fallback to `inputs` dict. Supports
  both node-to-node data flow and initial input patterns.

- **Streaming API** -- Fixed `UsageTracker` API usage in streaming tests (changed
  from `get_all()` to `get_summary()`). Fixed async generator cleanup to prevent
  `StopAsyncIteration` errors.

### Changed

- **Middleware Count** -- Updated documentation from "eight" to "ten" built-in
  middleware classes to include `PromptCacheMiddleware` and `CircuitBreakerMiddleware`.

- **Defence-in-Depth Example** -- Updated production middleware stack example to
  include prompt caching and circuit breaker alongside existing security and
  observability middleware.

## [2.26.0] - 2026-02-07

### Added

- **Agent Middleware System** -- Pluggable before/after hooks for agent runs via
  `AgentMiddleware` protocol and `MiddlewareChain`. Supports prompt mutation,
  result transformation, and cross-cutting concerns (audit, guardrails, logging).
- **Agent Run Timeout** -- `timeout` parameter on `FireflyAgent.run()` and
  `run_sync()` backed by `asyncio.wait_for()`.
- **Model Fallback** -- `FallbackModelWrapper` and `run_with_fallback()` for
  automatic retry with backup models on failure.
- **Result Caching** -- `ResultCache` with TTL, LRU eviction, and
  hash(model+prompt) keying for deduplicating identical agent calls.
- **Conversation Summarisation** -- `ConversationMemory` now accepts a
  `summarizer` callback; oldest turns are evicted and summarised when token
  usage exceeds the threshold.
- **JSON Structured Logging** -- `JsonFormatter` and `format_style="json"`
  option on `configure_logging()` for machine-parseable log output.
- **Prompt Injection Guard** -- `security.PromptGuard` with 10 default
  regex-based injection patterns, optional sanitisation, max-length check,
  and extensible custom patterns.
- **REST Rate Limiting** -- `RateLimiter` and `add_rate_limit_middleware()`
  for sliding-window per-client rate limiting on FastAPI/Starlette apps.
- **Async Memory I/O** -- `FileStore` gains `async_save`, `async_load`,
  `async_load_by_key`, `async_delete`, `async_clear` wrappers via
  `asyncio.to_thread()` to avoid blocking the event loop.
- **Pipeline Eager Scheduling** -- `PipelineEngine` replaced level-by-level
  `asyncio.gather()` with a task-queue approach using `asyncio.create_task()`
  and `asyncio.wait(FIRST_COMPLETED)` so nodes start as soon as their
  upstream dependencies complete.
- **Metering & Cost Tracking** -- Automatic token usage tracking, cost
  estimation, and budget enforcement across agents, reasoning patterns, and
  pipelines. `UsageTracker`, `CostCalculator` protocol with static and
  `genai-prices` backends, budget alerts and limits.
- **Streaming Usage Tracking** -- `run_stream()` wrapped in
  `_UsageTrackingStreamContext` to capture usage on `__aexit__`.
- **Pipeline Error Propagation** -- `FailureStrategy` enum (`PROPAGATE`,
  `SKIP_DOWNSTREAM`, `FAIL_PIPELINE`) on `DAGNode` with transitive
  successor skipping.
- **Thread-Safe Registries** -- `threading.Lock` added to `AgentRegistry`,
  `ToolRegistry`, `ReasoningPatternRegistry`, and `ConversationMemory`.
- **Config Cross-Validation** -- `@model_validator` on `FireflyGenAIConfig`
  enforcing budget, chunk-overlap, and QoS constraints.
- **Type Safety** -- Replaced `Any` with concrete types (`UsageSummary`,
  `FireflyAgent`, `MemoryManager`) in `pipeline/result.py`,
  `pipeline/context.py`, `agents/delegation.py`; fixed `Protocol` import
  in `pipeline/steps.py`.
- **Comprehensive Test Suite** -- 509 tests covering all modules including
  middleware, fallback, cache, config validation, JSON logging, lifecycle,
  agent/tool decorators, guards, composers, toolkit, observability
  decorators/events, pipeline builder/steps/context, plugin discovery,
  memory summarisation, prompt guard, rate limiter, and async FileStore.

## [2.25.0] - 2026-02-07

### Added

- **Logging** -- `configure_logging` function for structured framework-wide logging
  with level, format, and handler configuration.
- **Examples** -- 15 runnable example scripts in `examples/` covering agents (basic,
  conversational, summarizer, classifier, extractor, router), all six reasoning patterns
  (CoT, ReAct, Reflexion, Plan-and-Execute, ToT, Goal Decomposition), reasoning
  pipeline and memory integration, and a complex IDP pipeline.
- **IDP Pipeline Example** (`examples/idp_pipeline.py` + `idp_tools.py`) -- Full
  Intelligent Document Processing pipeline that downloads a real 33-page Unilever PDF
  and processes it through a 7-node DAG: ingest → split → classify → extract →
  validate → assemble → explain. Features LLM-powered document splitting (detects 4
  sub-documents), `create_classifier_agent` with category descriptions,
  `OutputReviewer` with custom retry prompts, `GroundingChecker` validation,
  LLM-powered explainability narrative generation, ANSI-colored pretty JSON output,
  `TraceRecorder` / `AuditTrail` / `ReportBuilder` integration, and exercises all
  major framework features together.
- **Core** -- Configuration management via Pydantic Settings, typed enumerations,
  structured exception hierarchy, and a plugin discovery system.
- **Agents** -- Pydantic AI agent wrapper with lifecycle management, a central
  registry, round-robin and capability-based delegation strategies, execution context,
  and the `@firefly_agent` decorator.
- **Tools** -- Protocol-driven tool interface, fluent `ToolBuilder`, `ToolRegistry`,
  `ToolKit` grouping, guard system (validation, rate-limiting, approval, sandboxing),
  sequential/fallback/conditional composition, `@firefly_tool` decorator, and built-in
  tools for HTTP, filesystem, search, database, and shell operations.
- **Prompts** -- Jinja2-based `PromptTemplate` engine, versioned `PromptRegistry`,
  sequential/conditional/merge composition strategies, variable validation, and
  file/directory loaders.
- **Reasoning Patterns** -- Abstract `ReasoningPattern` with Template Method design,
  `ReasoningTrace` for step-by-step audit, a pattern registry, and a composable
  pipeline. Ships six patterns: ReAct, Chain of Thought, Plan-and-Execute, Reflexion,
  Tree of Thoughts, and Goal Decomposition.
- **Observability** -- OpenTelemetry-native `FireflyTracer`, `FireflyMetrics` counter
  and histogram helpers, `FireflyEvents` event emitter, configurable exporters, and
  `@traced` / `@metered` decorators.
- **Explainability** -- `TraceRecorder` for decision-level recording, `ExplanationGenerator`
  for natural-language summaries, `AuditTrail` for compliance, and `ReportBuilder`
  for Markdown and JSON reports.
- **Experiments** -- `Experiment` and `Variant` models, `ExperimentRunner` for executing
  A/B tests, `ExperimentTracker` for persistence, and `ExperimentComparator` for
  statistical analysis.
- **Lab** -- `LabSession` for interactive exploration, `Benchmark` for performance
  measurement, `Comparison` for side-by-side evaluation, `Dataset` for test data
  management, and `Evaluator` protocol for custom scoring.
- **Exposure REST** -- FastAPI application factory, auto-generated agent routes,
  request-ID and CORS middleware, health-check endpoints, and SSE streaming.
- **Exposure Queues** -- Abstract consumer/producer model with Kafka, RabbitMQ, and
  Redis Pub/Sub implementations, plus a pattern-based message router.
- **Installation Scripts** -- Cross-platform interactive installers (`install.sh`,
  `uninstall.sh`, `install.ps1`, `uninstall.ps1`) with TUI, requirement detection,
  and remote execution support via `curl | bash` and `irm | iex`.
- **Documentation Index** -- Professional `docs/README.md` landing page with
  documentation map organized by architecture layer.

[26.01.01]: https://github.com/fireflyframework/fireflyframework-genai/releases/tag/v26.01.01
[2.26.1]: https://github.com/fireflyframework/fireflyframework-genai/releases/tag/v2.26.1
[2.26.0]: https://github.com/fireflyframework/fireflyframework-genai/releases/tag/v2.26.0
[2.25.0]: https://github.com/fireflyframework/fireflyframework-genai/releases/tag/v2.25.0
