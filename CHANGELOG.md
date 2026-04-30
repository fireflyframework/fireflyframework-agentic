# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

## [26.04.30] - 2026-04-30

### Added

- **Entra ID security.** Token verification and on-behalf-of (OBO) exchange
  for Azure AD authentication flows. New `[azure]` extra installs the
  required dependencies (#92).
- **MCP server.** New exposure module ships an MCP server and the
  `firefly-mcp` CLI for exposing agents over the Model Context Protocol
  (#93).
- **Hexagonal ingestion module.** New `fireflyframework_agentic/ingestion/`
  with domain models (`RawFile`, `TypedRecord`, `IngestionResult`,
  `TargetSchema`), three ports (`DataSourcePort`, `MapperPort`,
  `StructuredSinkPort`), a `SharePointSource` (Microsoft Graph, app-only
  OAuth2, deltaLink incremental sync), a `ScriptMapper`, a `DuckDBSink`,
  and a linear `IngestionService`. Adds `EnvSecretsProvider` and an
  optional `AzureKeyVaultSecretsProvider`, an `ingestion.yaml` config
  model, and a `firefly-ingest` CLI. New extras:
  `[ingestion-sharepoint]`, `[ingestion-duckdb]`,
  `[ingestion-keyvault]`, and umbrella `[ingestion]` (#84).
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
