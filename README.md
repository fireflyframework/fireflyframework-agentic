<p align="center">
  <img src="assets/banner.svg" alt="Firefly Agentic — production-grade agents, reasoning and pipelines, built on Pydantic AI" width="100%">
</p>

<h1 align="center">Firefly Agentic</h1>

<p align="center">
  <strong>The production-grade agentic metaframework, built on <a href="https://ai.pydantic.dev/">Pydantic AI</a>.</strong>
</p>

<p align="center">
  <a href="https://github.com/fireflyframework/fireflyframework-agentic/actions/workflows/pr-gate.yml"><img src="https://github.com/fireflyframework/fireflyframework-agentic/actions/workflows/pr-gate.yml/badge.svg?branch=main" alt="PR gate"></a>
  <a href="https://github.com/fireflyframework/fireflyframework-agentic/actions/workflows/nightly.yml"><img src="https://github.com/fireflyframework/fireflyframework-agentic/actions/workflows/nightly.yml/badge.svg?branch=main" alt="Nightly"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.13%2B-blue.svg" alt="Python 3.13+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green.svg" alt="License: Apache 2.0"></a>
  <a href="https://ai.pydantic.dev/"><img src="https://img.shields.io/badge/built%20on-pydantic--ai-8b5cf6.svg" alt="Built on Pydantic AI"></a>
  <a href="https://docs.astral.sh/ruff/"><img src="https://img.shields.io/badge/linting-ruff-orange.svg" alt="Ruff"></a>
  <a href="https://microsoft.github.io/pyright/"><img src="https://img.shields.io/badge/type--checked-pyright-2c8a1c.svg" alt="Type checked: pyright"></a>
</p>

<p align="center">
  <em>Keep Pydantic AI's <code>Agent</code>, <code>Tool</code> and <code>RunContext</code> — gain lifecycle hooks, delegation, memory, reasoning patterns, validation loops, RAG, and DAG pipelines, all protocol-driven and swappable.</em>
</p>

<p align="center">
  <a href="docs/tutorial.md"><b>📘 The Tutorial</b></a> &nbsp;·&nbsp;
  <a href="#5-minute-quick-start"><b>Quick Start</b></a> &nbsp;·&nbsp;
  <a href="#why-fireflyframework-agentic">Why</a> &nbsp;·&nbsp;
  <a href="#architecture-at-a-glance">Architecture</a> &nbsp;·&nbsp;
  <a href="#feature-highlights">Features</a> &nbsp;·&nbsp;
  <a href="#learn-the-framework">Docs</a> &nbsp;·&nbsp;
  <a href="#the-firefly-ecosystem">Ecosystem</a> &nbsp;·&nbsp;
  <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <sub>Copyright 2026 Firefly Software Foundation · Licensed under the Apache License 2.0</sub>
</p>

<details>
<summary><b>Table of contents</b></summary>

- [Why Firefly Agentic?](#why-fireflyframework-agentic)
- [Key Principles](#key-principles)
- [Architecture at a Glance](#architecture-at-a-glance)
- [Feature Highlights](#feature-highlights)
- [The Firefly Ecosystem](#the-firefly-ecosystem)
- [Requirements](#requirements)
- [Installation](#installation)
- [5-Minute Quick Start](#5-minute-quick-start)
- [Using in Jupyter Notebooks](#using-in-jupyter-notebooks)
- [Learn the Framework](#learn-the-framework)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

</details>

---

## Why fireflyframework-agentic?

[Pydantic AI](https://ai.pydantic.dev/) provides an excellent foundation: type-safe,
model-agnostic agents with structured output. But a production agentic system demands
far more than a single agent call. You need to orchestrate multi-step reasoning,
validate and retry LLM outputs against schemas, manage conversation memory across
turns, observe every call with traces and metrics, and run A/B experiments to compare
models — all without coupling your domain logic to infrastructure concerns.

**fireflyframework-agentic is the production framework built on top of Pydantic AI.**
It extends the engine with composable layers — from core configuration through
agent management, intelligent reasoning, experimentation, and pipeline orchestration —
so that every concern has a dedicated, protocol-driven module.
You write your business logic; the framework provides the architecture.

**What "metaframework" means in practice:**

- You keep Pydantic AI's familiar `Agent`, `Tool`, and `RunContext` APIs unchanged.
- The framework wraps them with lifecycle hooks, registries, delegation routers,
  memory managers, reasoning patterns, validation loops, and DAG pipelines — all
  optional, all composable, all swappable through Python protocols.
- No vendor lock-in: switch models, swap memory backends, or replace components
  without touching your agent code.

---

## Key Principles

1. **Protocol-driven contracts** — Every extension point is defined as a
   `@runtime_checkable` `Protocol` or abstract base class. The framework ships **28**
   such protocols across every layer — `AgentLike`, `ToolProtocol`, `GuardProtocol`,
   `AgentMiddleware`, `DelegationStrategy`, `ReasoningPattern`, `ValidationRule`,
   `StepExecutor`, `Checkpointer`, `Chunker`, `MemoryStore`, `EmbeddingProtocol`,
   `VectorStoreProtocol`, plus the new workflow ports (`AgentRunner`, `JournalBackend`,
   `ModelSelectionStrategy`) and more — so you can swap or extend any component without
   modifying framework internals.

2. **Convention over configuration** — Sensible defaults everywhere.
   `FireflyAgenticConfig` is a Pydantic Settings singleton that reads from environment
   variables prefixed with `FIREFLY_AGENTIC_` and `.env` files. One config object
   governs model defaults, retry counts, token limits, telemetry emission
   (`observability_enabled`), strict-cost mode (`cost_strict`), memory backends, and
   validation thresholds — override only what you need.

3. **Layered composition** — Layers with strict top-down dependency flow:
   **Core → Agent → Intelligence → Experimentation → Orchestration**.
   Higher layers depend on lower layers but never the reverse, keeping the
   dependency graph acyclic and each module independently testable.

4. **Optional dependencies** — Heavy libraries (`chromadb`, `pinecone`, `openai`,
   `asyncpg`) are declared as pip extras (`[openai-embeddings]`,
   `[vectorstores-chroma]`, `[postgres]`, `[all]`). The core framework imports them
   lazily inside factory functions so that you install only what your deployment requires.

---

## Architecture at a Glance

<p align="center">
  <img src="assets/architecture.svg" alt="Firefly Agentic architecture: one front door (pip install fireflyframework-agentic, @firefly_agent) over five layers — Orchestration, Experimentation, Intelligence, Agent, Core — on the Pydantic AI engine." width="100%">
</p>

### Protocol Hierarchy

Every extension point is a `@runtime_checkable` protocol. Implement the protocol to
create your own components; the framework discovers them via duck typing.

<p align="center">
  <img src="assets/protocols.svg" alt="The twelve runtime-checkable protocols — AgentLike, ToolProtocol, GuardProtocol, ReasoningPattern, StepExecutor, DelegationStrategy, CompressionStrategy, MemoryStore, ValidationRule, Chunker, EmbeddingProtocol, VectorStoreProtocol — each with its swappable implementations." width="100%">
</p>

---

## Feature Highlights

- **Agents** — `FireflyAgent` wraps `pydantic_ai.Agent` with metadata, lifecycle hooks,
  and automatic registration. `AgentRegistry` provides singleton name-based discovery.
  `DelegationRouter` routes prompts across agent pools via seven strategies
  (`RoundRobinStrategy`, `CapabilityStrategy`, `ContentBasedStrategy`,
  `CostAwareStrategy`, `ChainStrategy`, `FallbackStrategy`, `WeightedStrategy`).
  A composable middleware stack (`MiddlewareChain` over `AgentMiddleware`) wraps every
  run — `LoggingMiddleware` is always wired and `ObservabilityMiddleware` is added when
  `observability_enabled`, with `PromptGuardMiddleware`, `OutputGuardMiddleware`,
  `CostGuardMiddleware`, `CacheMiddleware`, `PromptCacheMiddleware`,
  `ExplainabilityMiddleware`, `ValidationMiddleware`, `RetryMiddleware`, and `CircuitBreakerMiddleware` available to
  add. `FallbackModelWrapper` / `run_with_fallback` provide automatic model failover, and
  `ResultCache` / `CacheStatistics` back response caching. The `@firefly_agent`
  decorator defines an agent in one statement. Five template factories
  (`create_summarizer_agent`, `create_classifier_agent`, `create_extractor_agent`,
  `create_conversational_agent`, `create_router_agent`) cover common use cases out of
  the box.

<p align="center">
  <img src="assets/agent-anatomy.svg" alt="Anatomy of an agent run: a FireflyAgent wrapping pydantic_ai.Agent inside a ten-stage middleware chain, with delegation, fallback, caching and memory." width="100%">
</p>

- **Tools** — `ToolProtocol` (duck-typed) and `BaseTool` (inheritance) let you choose
  your extensibility style. `ToolBuilder` provides a fluent API for building tools
  without subclassing. Five guard types (`ValidationGuard`, `RateLimitGuard`,
  `ApprovalGuard`, `SandboxGuard`, `CompositeGuard`) intercept calls before execution.
  Three composition patterns (`SequentialComposer`, `FallbackComposer`,
  `ConditionalComposer`) build higher-order tools. `ToolKit` groups tools for
  bulk registration. Nine built-in tools (calculator, datetime, filesystem, HTTP,
  JSON, search, shell, text, database) are ready to attach to any agent.

- **Prompts** — `PromptTemplate` renders Jinja2 templates with variable validation
  and token estimation. `PromptRegistry` maps names to versioned templates.
  Three composers (`SequentialComposer`, `ConditionalComposer`, `MergeComposer`)
  combine templates at render time. `PromptValidator` enforces token limits and
  required sections. `PromptLoader` loads templates from strings, files, or
  entire directories.

- **Reasoning** — Six pluggable patterns implement `AbstractReasoningPattern`'s
  template-method loop (`_reason` → `_act` → `_observe` → `_should_continue`):
  **ReAct** (observe-think-act), **Chain of Thought** (step-by-step),
  **Plan-and-Execute** (goal → plan → steps with optional replanning),
  **Reflexion** (execute → critique → retry), **Tree of Thoughts** (branch →
  evaluate → select), and **Goal Decomposition** (goal → phases → tasks).
  All produce structured `ReasoningResult` with `ReasoningTrace`. Prompts are
  slot-overridable. `OutputReviewer` can validate final outputs. `ReasoningPipeline`
  chains patterns sequentially.

<p align="center">
  <img src="assets/reasoning.svg" alt="Six reasoning patterns — ReAct, Chain of Thought, Plan-and-Execute, Reflexion, Tree of Thoughts, Goal Decomposition — on one reason/act/observe loop." width="100%">
</p>

- **Content** — `TextChunker` splits by tokens, sentences, or paragraphs with
  configurable overlap; `MarkdownChunker` chunks structure-aware on Markdown
  headings. `DocumentSplitter` detects page breaks and section
  separators. `ImageTiler` computes tile coordinates for VLM processing.
  `BatchProcessor` runs chunks through an agent concurrently with a semaphore.
  `ContextCompressor` delegates to pluggable strategies (`TruncationStrategy`,
  `SummarizationStrategy`, `MapReduceStrategy`) — `ContextCompressor.compress` is
  async. `SlidingWindowManager` maintains a rolling token-budgeted context window.
  The `[binary]`-gated `content.binary` submodule normalises uploaded files into
  consumer-ready artifacts: `BinaryNormalizer` (with `BinaryConfig`) produces
  `BinaryArtifact`s, `sniff_media_type` detects formats, `build_office_converter`
  selects an `OfficeConverter` (`GotenbergConverter`, `LibreOfficeConverter`,
  `NoOpOfficeConverter`), and `PdfGuard`, `ImageNormalizer`, `ArchiveUnpacker`, and
  `EmailUnpacker` handle PDFs, images, archives, and emails.

- **Memory** — `ConversationMemory` stores per-conversation turn history with
  token-budget enforcement (newest-first FIFO eviction). `WorkingMemory` provides
  a scoped key-value scratchpad backed by `MemoryStore` (`InMemoryStore`, `FileStore`,
  or `SQLiteStore`). `MemoryManager` composes both behind a unified API and supports
  `fork()` for isolating working memory in delegated agents or pipeline branches
  while sharing conversation context. `create_llm_summarizer` builds an LLM-backed
  history summarizer for long conversations.

- **Validation** — Five composable rules (`RegexRule`, `FormatRule`, `RangeRule`,
  `EnumRule`, `CustomRule`) feed into `FieldValidator` and `OutputValidator`.
  `OutputReviewer` wraps agent calls with parse-then-validate retry logic: on
  failure it builds a feedback prompt and retries up to N times. `RubricReviewer`
  adds LLM-as-judge grading against a rubric (`RubricReviewer.from_rubric_file`).
  QoS guards (`ConfidenceScorer`, `ConsistencyChecker`, `GroundingChecker`, plus
  the `QoSGuard` aggregator returning a `QoSResult`) detect hallucinations and
  low-quality extractions before they propagate downstream.

- **Pipeline** — `DAG` holds `DAGNode` and `DAGEdge` objects with cycle detection
  and topological sort. `PipelineEngine` executes nodes level-by-level via
  `asyncio.gather` for maximum concurrency, with per-node condition gates, retries,
  and timeouts. `PipelineBuilder` offers a fluent API (`add_node` / `add_edge` /
  `chain`). Step types adapt agents, patterns, and functions to DAG nodes:
  `AgentStep`, `ReasoningStep`, `CallableStep`, `FanOutStep`, `FanInStep`,
  `BranchStep`, `BatchLLMStep`, `EmbeddingStep`, and `RetrievalStep`. State reducers
  (`append`, `extend`, `merge_dict`, `replace`) merge fan-out results, and control
  signals (`Pause`, `Send`) drive branching and human-in-the-loop pauses.
  `Checkpointer` / `FileCheckpointer` (with `CheckpointRecord`) persist and resume
  long runs, and a pluggable audit-log family (`AuditLog`, `FileAuditLog`,
  `LoggingAuditLog`, `OtelAuditLog`, `QueryableAuditLog` over `AuditEntry`) records
  execution traces.

<p align="center">
  <img src="assets/pipeline.svg" alt="A typed DAG pipeline: a seven-phase IDP flow with fan-out/fan-in, a human-in-the-loop pause, checkpointing and an audit log." width="100%">
</p>

- **Workflows** — `@workflow` / `@subworkflow` define a **code-defined, deterministic
  orchestration DSL** over your agents — a complement to the declarative `pipeline` DAG,
  both living in the Orchestration layer. Compose async primitives — `agent()`,
  `parallel()`, `pipeline()`, `stream()`, `phase()`, `human()` (human-in-the-loop),
  `map_agents()` and `log()` — inside a `WorkflowContext` that carries a `WorkflowBudget`
  (concurrency, agent-count and token/cost ceilings), a `Journal` (`JournalBackend` /
  `FileJournalBackend`) for **deterministic resume**, and a pluggable `AgentRunner`.
  `FireflyAgentRunner` (the default) runs every sub-agent call through a full
  `FireflyAgent` (middleware, guards, budget, model fallback); `DefaultAgentRunner` is the
  lightweight path. `SmartRoutingRunner` selects the cheapest capable model via a
  `ModelSelectionStrategy` (`ComplexityHeuristicStrategy`, `CostFloorStrategy`), and
  verification helpers (`cascade`, `adversarial_verify`, `judge_panel`, `loop_until_dry`)
  add refute-by-default quality gates. See [docs/workflows.md](docs/workflows.md).

<p align="center">
  <img src="assets/workflows.svg" alt="Dynamic Workflows: the @workflow DSL primitives (agent, parallel, pipeline, stream, phase, human, map_agents, log) over a WorkflowContext carrying runner, journal, budget and routing, with verification helpers." width="100%">
</p>

- **Observability** — `FireflyTracer` creates OpenTelemetry spans scoped to agents,
  tools, and reasoning steps. `FireflyMetrics` records tokens (total, prompt,
  completion), latency, cost, errors, and reasoning depth via the OTel metrics API.
  `FireflyEvents` emits structured log records. `@traced` and `@metered` decorators
  instrument any function with one line. The framework emits model and agent
  telemetry purely through the OpenTelemetry API; the host application owns OTel
  SDK and exporter configuration. `UsageTracker` automatically records token usage, cost
  estimates, and latency for every agent run, reasoning step, and pipeline
  execution. Cost is computed through a resolver chain (`resolve_cost`,
  `genai_prices_cost`, `provider_reported_cost`, `DEFAULT_RESOLVERS`); set
  `cost_strict` to raise `UnknownModelCostError` when no price is found. `BudgetGate`
  enforces token/cost budgets per scope (`BudgetRule`, `BudgetMode`, `BudgetWindow`),
  and a pluggable sink family (`LoggingSink`, `JSONLFileSink`, `OTelMetricsSink`,
  `EventBusSink`, `CostSink`) routes usage records wherever you need them.

- **Explainability** — `TraceRecorder` captures every LLM call, tool invocation,
  and reasoning step as `DecisionRecord` objects. `ExplanationGenerator` turns
  records into human-readable narratives. `AuditTrail` provides an append-only,
  immutable log with JSON export for compliance. `ReportBuilder` produces
  Markdown and JSON reports with statistics.

- **Security** — `PromptGuard` scans inbound prompts for injection and jailbreak
  patterns; `OutputGuard` redacts secrets and PII from model output
  (`default_prompt_guard` / `default_output_guard` provide ready-to-use instances).
  At-rest protection comes from `AESEncryptionProvider` (behind the
  `EncryptionProvider` protocol) and `EncryptedMemoryStore`, which encrypts
  `MemoryEntry.content` while leaving keys, metadata, and timestamps in plaintext.
  Inbound request authentication and authorization are a hosting concern, not the
  framework's.

- **Resilience** — `CircuitBreaker` trips after a configurable failure threshold
  and rejects calls with `CircuitBreakerOpenError` while open, transitioning through
  `CircuitState` (closed → open → half-open). `CircuitBreakerMiddleware` plugs it
  into the agent middleware chain so a failing model is short-circuited before it
  drains your budget.

- **Storage** — `StorageBackend` abstracts blob/object storage with `LocalBackend`
  out of the box; `DatabaseStore` persists artifacts with leasing
  (`WriteSession`, `LockToken`), a configurable `RetryPolicy`, and `StorageMetadata`.
  Typed errors (`StorageUploadError`, `StorageDownloadError`, `StorageLeaseError`,
  `StorageTransientError`, `StoreUnavailableError`) make failure handling explicit.

- **Experiments** — `Experiment` defines variants with model, temperature, and
  prompt overrides. `ExperimentRunner` executes all variants against a dataset via
  an `agent_factory` callable. `ExperimentTracker` persists results with optional
  JSON export. `VariantComparator` computes latency, output length, and comparison
  summaries.

- **Lab** — `LabSession` manages interactive agent sessions with history.
  `Benchmark` runs agents against standardised inputs and reports p95 latency.
  `EvalOrchestrator` scores agent outputs with pluggable `Scorer` functions.
  `EvalDataset` loads/saves test cases from JSON. `ModelComparison` runs the
  same prompts across multiple agents for side-by-side analysis.

  > **Optional developer tooling.** `fireflyframework_agentic.experiments` (A/B
  > experiments) and `fireflyframework_agentic.lab` (offline evaluation /
  > benchmarking) are leaf modules — nothing in the core imports them and they add
  > no third-party dependencies. Import them only if you run experiments or
  > evaluations; agent-building consumers can ignore them.

- **Embeddings** — `EmbeddingProtocol` (duck-typed) and `BaseEmbedder`
  (inheritance with auto-batching) provide provider-agnostic text embedding.
  Eight providers ship out of the box: **OpenAI**, **Azure OpenAI**, **Cohere**,
  **Google**, **Mistral**, **Voyage AI**, **AWS Bedrock**, and **Ollama** (local).
  `EmbedderRegistry` manages named instances. Built-in similarity utilities
  (`cosine_similarity`, `euclidean_distance`, `dot_product`) compare vectors
  without external dependencies. Configuration via `embedding_batch_size`,
  `embedding_max_retries`, and `default_embedding_model`.

- **Vector Stores** — `VectorStoreProtocol` and `BaseVectorStore` provide
  pluggable storage and retrieval with six backends: **InMemoryVectorStore**
  (zero-dependency, brute-force cosine), **ChromaVectorStore**, **PineconeVectorStore**,
  **QdrantVectorStore**, **PgVectorVectorStore** (Postgres + pgvector), and
  **SqliteVecVectorStore** (embedded sqlite-vec). A multi-tenant isolation layer
  (`ScopedVectorStore`, `TenantScopedVectorStore`, plus `scope_namespace` /
  `parse_scope_namespace` helpers) namespaces documents per tenant or scope.
  Auto-embedding upserts documents without pre-computed vectors. `search_text`
  embeds a query string and searches in one call, and `SearchFilter` narrows results
  by metadata. Namespace scoping isolates document collections. `VectorStoreRegistry`
  manages named instances. `EmbeddingStep` and `RetrievalStep` integrate directly
  into DAG pipelines for retrieval-augmented workflows.

<p align="center">
  <img src="assets/rag.svg" alt="Retrieval-augmented generation: eight embedding providers and six vector-store backends behind the EmbeddingProtocol and VectorStoreProtocol." width="100%">
</p>

- **Studio** — moved to its own repository:
  [fireflyframework-agentic-studio](https://github.com/fireflyframework/fireflyframework-agentic-studio).
  A browser-based visual IDE for building agent pipelines (drag-and-drop
  canvas, code generation, AI assistant, time-travel debugging). Install
  with `pip install fireflyframework-agentic-studio` and launch with
  `firefly studio`.

---

## The Firefly Ecosystem

Firefly Agentic is the **agentic member** of the [Firefly Framework](https://github.com/fireflyframework) — a polyglot platform that brings one cohesive programming model to many runtimes. Each member shares the same firefly-in-the-dark identity, recolored per language.

<p align="center">
  <img src="assets/ecosystem.svg" alt="The Firefly Framework family: Java/Spring Boot, .NET, PyFly (Python), Rust, Go, the Angular frontend, and Firefly Agentic — around a shared core." width="100%">
</p>

- **[PyFly](https://github.com/fireflyframework/fireflyframework-pyfly)** — the Python implementation (Spring-Boot DX, async-native).
- **[Firefly for Rust](https://github.com/fireflyframework/fireflyframework-rust)** — reactive, `tokio` + `axum` microservices.
- **[Firefly Studio](https://github.com/fireflyframework/fireflyframework-agentic-studio)** — a browser-based visual IDE for building agent pipelines.

---

## Requirements

**Runtime:**

- **Python 3.13** or later
- [Git](https://git-scm.com/) for cloning the repository
- [UV](https://docs.astral.sh/uv/) package manager (recommended) or pip

**Core dependencies** (installed automatically):

- [pydantic-ai](https://ai.pydantic.dev/) `>=1.99.0` — Agent engine (model calls, tool dispatch, streaming)
- [pydantic](https://docs.pydantic.dev/) `>=2.10.0` — Data validation and settings
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) `>=2.7.0` — Environment-based configuration
- [Jinja2](https://jinja.palletsprojects.com/) `>=3.1.0` — Prompt template engine
- [httpx](https://www.python-httpx.org/) `>=0.28.0` — Async HTTP client (built-in HTTP tool, Gotenberg converter)
- [OpenTelemetry API](https://opentelemetry.io/docs/languages/python/) `>=1.29.0` — Tracing and metrics
- [OpenTelemetry SDK](https://opentelemetry.io/docs/languages/python/) `>=1.29.0` — Telemetry primitives
- [genai-prices](https://pypi.org/project/genai-prices/) `>=0.0.1` — LLM pricing data for cost resolution
- [markdown-it-py](https://pypi.org/project/markdown-it-py/) `>=3.0` — Structure-aware Markdown chunking
- [python-dotenv](https://pypi.org/project/python-dotenv/) `>=1.0.0` — `.env` loading for example scripts

**Optional dependencies** (installed via extras):

- `[embeddings]` — [numpy](https://numpy.org/) for fast in-memory vector math
- `[openai-embeddings]` — [openai](https://github.com/openai/openai-python) `>=1.0.0` for OpenAI/Azure embeddings
- `[vectorstores-chroma]` — [chromadb](https://www.trychroma.com/) `>=0.5.0`
- `[vectorstores-pinecone]` — [pinecone](https://www.pinecone.io/) `>=5.0.0`
- `[vectorstores-qdrant]` — [qdrant-client](https://qdrant.tech/) `>=1.12.0`
- `[vectorstores-pgvector]` — [asyncpg](https://magicstack.github.io/asyncpg/) `>=0.30.0` for Postgres + pgvector
- `[vectorstores-sqlite-vec]` — [sqlite-vec](https://github.com/asg017/sqlite-vec) `>=0.1.6` for embedded vector search
- `[binary]` — pypdf, Pillow, pillow-heif, cairosvg, py7zr, extract-msg for `content.binary`
- `[all]` — Everything (memory backends, security, all embedding providers, all vector stores, watch, binary)

**LLM provider keys** (at least one):

- `OPENAI_API_KEY` for OpenAI models
- `ANTHROPIC_API_KEY` for Anthropic models
- `GEMINI_API_KEY` for Google Gemini models
- `GROQ_API_KEY` for Groq models
- Or any [Pydantic AI-supported provider](https://ai.pydantic.dev/models/)

---

## Installation

### One-Line Installer (Recommended)

The interactive installer detects your platform, checks Python and UV, lets you
choose extras, and installs everything with progress indicators and verification.

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/install.ps1 | iex
```

Both installers support non-interactive mode for CI/CD:

```bash
# macOS / Linux — install with all extras, no prompts
curl -fsSL https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/install.sh | bash
```

```powershell
# Windows — install with all extras, no prompts
.\install.ps1 -NonInteractive -Extras all
```

### Install from Source

```bash
git clone https://github.com/fireflyframework/fireflyframework-agentic.git
cd fireflyframework-agentic
uv sync --all-extras # or: pip install -e ".[all]"
```

### Optional Extras

| Extra | What it adds | When you need it |
|---|---|---|
| `postgres` | asyncpg, SQLAlchemy | PostgreSQL memory / storage persistence |
| `mongodb` | motor, pymongo | MongoDB memory persistence |
| `security` | cryptography | At-rest encryption (`EncryptedMemoryStore`, `AESEncryptionProvider`) |
| `embeddings` | numpy | Fast in-memory vector math |
| `openai-embeddings` | openai | OpenAI / Azure text embeddings |
| `cohere-embeddings` | cohere | Cohere text embeddings |
| `google-embeddings` | google-generativeai | Google text embeddings |
| `mistral-embeddings` | mistralai | Mistral text embeddings |
| `voyage-embeddings` | voyageai | Voyage AI text embeddings |
| `azure-embeddings` | openai | Azure OpenAI text embeddings |
| `bedrock-embeddings` | boto3 | AWS Bedrock text embeddings |
| `ollama-embeddings` | httpx | Ollama local text embeddings |
| `vectorstores-chroma` | chromadb | ChromaDB vector store backend |
| `vectorstores-pinecone` | pinecone | Pinecone vector store backend |
| `vectorstores-qdrant` | qdrant-client | Qdrant vector store backend |
| `vectorstores-pgvector` | asyncpg | Postgres + pgvector vector store backend |
| `vectorstores-sqlite-vec` | sqlite-vec | Embedded sqlite-vec vector store backend |
| `binary` | pypdf, Pillow, pillow-heif, cairosvg, py7zr, extract-msg | `content.binary` file normalisation |
| `watch` | watchfiles | File-watching for content sources |
| `all` | Everything above | Full install with all integrations |

### Verify Installation

```bash
python -c "import fireflyframework_agentic; print(fireflyframework_agentic.__version__)"
```

### Uninstall

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/uninstall.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/uninstall.ps1 | iex
```

Or manually remove the cloned directory and its virtual environment.

---

## 5-Minute Quick Start

### 1. Configure

Create a `.env` file (or set environment variables):

```bash
# Provider API key (Pydantic AI reads these automatically)
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GEMINI_API_KEY=...
# GROQ_API_KEY=gsk_...

# Framework settings
FIREFLY_AGENTIC_DEFAULT_MODEL=openai:gpt-4o
FIREFLY_AGENTIC_DEFAULT_TEMPERATURE=0.3
```

The model string format is `"provider:model_name"` — e.g. `"openai:gpt-4o"`,
`"anthropic:claude-sonnet-4-20250514"`, `"google:gemini-2.0-flash"`. Pydantic AI resolves
the matching API key from environment variables automatically. For programmatic credential
management (Azure, Bedrock, custom endpoints), pass a Pydantic AI `Model` object directly
to `FireflyAgent(model=...)` — see the [tutorial](docs/tutorial.md#model-providers--authentication).

### 2. Define an Agent

```python
from fireflyframework_agentic.agents import firefly_agent

@firefly_agent(name="assistant", model="openai:gpt-4o")
def assistant_instructions(ctx):
    return "You are a helpful conversational assistant."
```

### 3. Register a Tool

```python
from fireflyframework_agentic.tools import firefly_tool

@firefly_tool(name="lookup", description="Look up a term")
async def lookup(query: str) -> str:
    return f"Result for {query}"
```

### 4. Add Memory for Multi-Turn Conversations

```python
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.memory import MemoryManager

memory = MemoryManager(max_conversation_tokens=32_000)
agent = FireflyAgent(name="bot", model="openai:gpt-4o", memory=memory)

cid = memory.new_conversation()
result = await agent.run("Hello!", conversation_id=cid)
result = await agent.run("What did I just say?", conversation_id=cid)
```

### 5. Apply a Reasoning Pattern

```python
from fireflyframework_agentic.reasoning import ReActPattern

react = ReActPattern(max_steps=5)
result = await react.execute(agent, "What is the weather in London?")
print(result.output)
```

### 6. Validate Output

```python
from pydantic import BaseModel
from fireflyframework_agentic.validation import OutputReviewer

class Answer(BaseModel):
    answer: str
    confidence: float

reviewer = OutputReviewer(output_type=Answer, max_retries=2)
result = await reviewer.review(agent, "What is 2+2?")
print(result.output) # Answer(answer="4", confidence=0.99)
```

### 7. Wire a Pipeline

```python
from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.steps import AgentStep, CallableStep

pipeline = (
    PipelineBuilder("my-pipeline")
    .add_node("classify", AgentStep(classifier_agent))
    .add_node("extract", AgentStep(extractor_agent))
    .add_node("validate", CallableStep(validate_fn))
    .chain("classify", "extract", "validate")
    .build()
)
result = await pipeline.run(inputs="Process this document")
```

### 8. Embed and Search (RAG)

```python
from fireflyframework_agentic.embeddings.providers import OpenAIEmbedder
from fireflyframework_agentic.vectorstores import InMemoryVectorStore, VectorDocument

embedder = OpenAIEmbedder(model="text-embedding-3-small")
store = InMemoryVectorStore(embedder=embedder)

# Upsert documents (auto-embedded)
await store.upsert([
    VectorDocument(id="1", text="Python is great for AI"),
    VectorDocument(id="2", text="Rust is fast and safe"),
])

# Search by text
results = await store.search_text("machine learning languages", top_k=1)
print(results[0].document.text)  # Python is great for AI
```

## Using in Jupyter Notebooks

firefly-agentic works seamlessly in Jupyter notebooks and JupyterLab.
Since the framework is async-first, use `await` directly in notebook cells
(Jupyter provides a running event loop automatically).

### Setup

```bash
# From your clone directory
cd fireflyframework-agentic
source .venv/bin/activate # activate the venv created by the installer
pip install ipykernel # install Jupyter kernel support
python -m ipykernel install --user --name fireflyagentic --display-name "Firefly Agentic"
jupyter lab # or: jupyter notebook
```

Then select the **Firefly Agentic** kernel when creating a new notebook.

### Example Notebook

```python
# Cell 1 — configure
import os
os.environ["OPENAI_API_KEY"] = "sk-..." # or set in .env
os.environ["FIREFLY_AGENTIC_DEFAULT_MODEL"] = "openai:gpt-4o"
```

```python
# Cell 2 — create an agent
from fireflyframework_agentic.agents import FireflyAgent

agent = FireflyAgent(name="notebook-bot", model="openai:gpt-4o")
result = await agent.run("Explain quantum entanglement in two sentences.")
print(result.output)
```

```python
# Cell 3 — use memory for multi-turn conversations
from fireflyframework_agentic.memory import MemoryManager

memory = MemoryManager(max_conversation_tokens=32_000)
agent_with_mem = FireflyAgent(name="chat", model="openai:gpt-4o", memory=memory)

cid = memory.new_conversation()
result = await agent_with_mem.run("My name is Alice.", conversation_id=cid)
print(result.output)

result = await agent_with_mem.run("What is my name?", conversation_id=cid)
print(result.output) # Alice
```

```python
# Cell 4 — reasoning patterns
from fireflyframework_agentic.reasoning import ReActPattern

react = ReActPattern(max_steps=5)
result = await react.execute(agent, "What are the top 3 uses of Python in 2026?")
print(result.output)
```

```python
# Cell 5 — structured output with validation
from pydantic import BaseModel
from fireflyframework_agentic.validation import OutputReviewer

class Summary(BaseModel):
    title: str
    bullet_points: list[str]
    confidence: float

reviewer = OutputReviewer(output_type=Summary, max_retries=2)
result = await reviewer.review(agent, "Summarize the benefits of async Python.")
result.output # displays the structured Summary object in the notebook
```

> **Tip:** You do not need `asyncio.run()` or `nest_asyncio` in Jupyter — `await`
> works at the top level of any cell because Jupyter runs its own event loop.

---

## Learn the Framework

### The Complete Tutorial ("The Bible")

**[docs/tutorial.md](docs/tutorial.md)** is an 18-chapter, hands-on guide that teaches
every concept from zero to expert through a real-world **Intelligent Document Processing**
pipeline. Start here if you want to learn the framework thoroughly.

### Use Case: IDP Pipeline

**[docs/use-case-idp.md](docs/use-case-idp.md)** is a focused walkthrough of building a
7-phase IDP pipeline that ingests, splits, classifies, extracts, validates, assembles,
and explains data from corporate documents — using agents, reasoning, document splitting,
content processing, validation, explainability, and pipelines.

### Module Reference

Detailed guides for each module:

- [Architecture](docs/architecture.md) — Design principles and layer diagram
- [Agents](docs/agents.md) — Lifecycle, registry, delegation, decorators
- [Template Agents](docs/templates.md) — Summarizer, classifier, extractor, conversational, router
- [Tools](docs/tools.md) — Protocol, builder, guards, composition, built-ins
- [Prompts](docs/prompts.md) — Templates, versioning, composition, validation
- [Reasoning Patterns](docs/reasoning.md) — 6 patterns, structured outputs, custom patterns
- [Content](docs/content.md) — Chunking, compression, batch processing
- [Memory](docs/memory.md) — Conversation history, working memory, storage backends
- [Validation](docs/validation.md) — Rules, QoS guards, output reviewer
- [Embeddings](docs/embeddings.md) — 8 providers, auto-batching, similarity, registry
- [Vector Stores](docs/vectorstores.md) — 6 backends, tenant scoping, auto-embedding, search_text, namespaces
- [Pipeline](docs/pipeline.md) — DAG orchestrator, parallel execution, checkpointing, audit log, retries
- [Dynamic Workflows](docs/workflows.md) — Code-defined orchestration DSL over agents: `@workflow`, `agent`/`parallel`/`pipeline`/`stream`, budgets, journal resume, smart routing, sub-workflows, HITL, `FireflyAgentRunner`
- [Observability](docs/observability.md) — Tracing, metrics, events, cost resolvers, budget gates
- [Explainability](docs/explainability.md) — Decision recording, audit trails, reports
- [Security](docs/security.md) — Prompt/output guards, at-rest encryption
- [Secure Script Execution](docs/execution.md) — Deny-by-default Monty sandbox, static safety pre-screen, `SecureScriptRunner`, Firefly Code Mode
- [Experiments](docs/experiments.md) — A/B testing, variant comparison
- [Lab](docs/lab.md) — Benchmarks, datasets, evaluators
- Studio — moved to [fireflyframework-agentic-studio](https://github.com/fireflyframework/fireflyframework-agentic-studio)
---

## Development

```bash
git clone https://github.com/fireflyframework/fireflyframework-agentic.git
cd fireflyframework-agentic
uv sync --all-extras
```

```bash
uv run pytest # Run the test suite
uv run ruff check fireflyframework_agentic/ tests/ # Lint
uv run pyright fireflyframework_agentic/ # Type check
```

**Dev dependencies** (installed with `uv sync`):
[pytest](https://docs.pytest.org/) `>=8.3.0`,
[pytest-asyncio](https://pytest-asyncio.readthedocs.io/) `>=0.24.0`,
[pytest-cov](https://pytest-cov.readthedocs.io/) `>=6.0.0`,
[ruff](https://docs.astral.sh/ruff/) `>=0.9.0`,
[pyright](https://microsoft.github.io/pyright/) `>=1.1.0`,
[httpx](https://www.python-httpx.org/) `>=0.28.0`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for notable changes.

## License

Apache License 2.0. See [LICENSE](LICENSE) for the full text.
