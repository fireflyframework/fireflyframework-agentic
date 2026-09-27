# Architecture Guide

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

This document describes the high-level architecture of fireflyframework-agentic, the
relationships between its modules, and the design principles that guided its construction.

---

## Design Principles

The framework follows five guiding principles:

1. **Explicit extension contracts** -- Tools, memory stores, reasoning patterns and other
   extension points use Python protocols or abstract base classes. Configuration models,
   builders and concrete facades expose their own public APIs; implement the documented
   contract for the component you want to replace.

2. **Convention over configuration** -- Sensible defaults are provided for every setting.
   A single `FireflyAgenticConfig` object (backed by Pydantic Settings) centralises
   configuration and supports environment-variable overrides.

3. **Layered composition** -- Modules are organised into layers (Core, Security, Agent,
   Intelligence, Orchestration, plus optional Experimentation dev-tooling). These categories describe responsibilities and composition, not an enforced
   import hierarchy. Components can collaborate across them through public contracts.

4. **Optional dependencies** -- Heavy third-party libraries (embedding providers, vector
   store clients, storage backends, document-conversion tooling) are declared as extras. The
   core framework imports them lazily so that users only install what they need.

5. **Pure in-process library** -- fireflyframework-agentic is a library, not a server. It
   serves no HTTP port and consumes no message broker; the host service owns all serving,
   hosting, and inbound authentication. The framework *emits* model and agent spans and
   metrics through the OpenTelemetry API, but configuring the OTel SDK, exporters, and
   cross-service trace propagation is the host's responsibility.

---

## Application boundary

Application code uses `FireflyAgent`, `@firefly_tool` / `ToolKit`, `MemoryManager`,
and typed `ModelOptions`. Firefly resolves options against the selected provider
on every run, including per-run model overrides, and rejects unsupported controls.
`ModelSpec` and `ModelFactory` handle credential and endpoint configuration for
applications that maintain a model catalogue. Pydantic AI 2.x remains the model
transport and tool-execution engine; native settings and capabilities are advanced
integration surfaces.

Existing `openai:` / `azure:` configurations retain Chat Completions. Select
`openai-responses:` / `azure-responses:` explicitly for Responses. See
[Models](models.md) and the [migration guide](migration.md) for compatibility rules.

## Layer Diagram

Arrows below show which components invoke or use others. This is a conceptual map,
not a complete Python import graph. Optional behaviors are enabled by the host.

```mermaid
flowchart TB
    HOST["Host application<br/>configuration, credentials, serving"]
    FLOW["Pipelines and workflows<br/>routing, state, checkpoints"]
    REASON["Reasoning and review<br/>explicit multi-step execution"]
    AGENT["FireflyAgent<br/>run, run_sync, run_stream"]
    MODELS["Models<br/>ModelSpec, ModelFactory, ModelOptions"]
    PAI["Pydantic AI<br/>provider requests and tool dispatch"]
    PROVIDER["Selected provider and API"]
    TOOLS["Firefly tools<br/>schemas, guards, listeners"]
    MEMORY["MemoryManager<br/>history and scoped facts"]
    RETRIEVAL["Content, embeddings, vector stores"]
    POLICY["Configured middleware<br/>logging, guards, telemetry, caching"]
    SUPPORT["Shared services<br/>configuration, storage, registries, plugins"]
    DEV["Lab and experiments<br/>optional evaluation workflows"]

    HOST --> AGENT
    HOST --> FLOW
    FLOW --> AGENT
    FLOW --> REASON
    REASON --> AGENT
    AGENT --> MODELS
    AGENT --> PAI
    PAI --> PROVIDER
    PAI --> TOOLS
    AGENT --> MEMORY
    AGENT --> POLICY
    FLOW --> RETRIEVAL
    AGENT -. uses .-> SUPPORT
    MEMORY -. uses .-> SUPPORT
    RETRIEVAL -. uses .-> SUPPORT
    DEV --> AGENT
```

### Protocol & Class Hierarchy

The representative contracts below use structural typing: a component implements
the required members rather than inheriting a concrete framework class. Abstract
base classes provide reusable behavior where shown. Runtime protocol checks verify
member presence, not argument types or application correctness.

Other contracts are documented alongside their implementations: [guards and tool
listeners](tools.md), [pipeline steps](pipeline.md), [delegation](agents.md#multi-agent-delegation),
[compression](content.md), [storage](storage.md), and [validation](validation.md).

```mermaid
classDiagram
    class AgentLike {
        <<Protocol>>
        +run(prompt, **kwargs) Any
    }
    class ToolProtocol {
        <<Protocol>>
        +name str
        +description str
        +execute(**kwargs) Any
    }
    class MemoryStore {
        <<Protocol>>
        +save(namespace, entry)
        +load(namespace) list
        +load_by_key(namespace, key) MemoryEntry
        +delete(namespace, entry_id)
        +clear(namespace)
    }
    class ReasoningPattern {
        <<Protocol>>
        +execute(agent, input, **kwargs) ReasoningResult
    }
    class BaseTool {
        <<abstract>>
    }
    class AbstractReasoningPattern {
        <<abstract>>
    }
    AgentLike <|.. FireflyAgent
    ToolProtocol <|.. BaseTool
    BaseTool <|-- HttpTool
    MemoryStore <|.. InMemoryStore
    MemoryStore <|.. PostgreSQLStore
    MemoryStore <|.. MongoDBStore
    ReasoningPattern <|.. AbstractReasoningPattern
    AbstractReasoningPattern <|-- ReActPattern
    ReasoningPattern <|.. ReasoningPipeline
```

---

## Module Responsibilities

### Core Layer

The Core layer provides foundational types, configuration, exceptions, and the plugin
system. Every other module depends on at least one Core component.

- **types.py** -- The `AgentLike` protocol, generic TypeVars, shared type aliases,
  and re-exported multimodal content types. (The other extension-point
  protocols -- `ToolProtocol`, `GuardProtocol`, `ReasoningPattern`, `StepExecutor`,
  `DelegationStrategy`, `CompressionStrategy`, `MemoryStore`, `ValidationRule` -- live in
  their respective modules, not in `types.py`.)
- **config.py** -- `FireflyAgenticConfig`, a Pydantic Settings singleton that reads
  from environment variables and `.env` files. It actively rejects removed serving/exposure
  config fields (e.g. `otlp_endpoint`, `rbac_enabled`, `cors_allowed_origins`,
  `cost_calculator`) with a `ValueError`.
- **exceptions.py** -- A structured exception hierarchy of 42 classes rooted at
  `FireflyAgenticError`.
- **plugin.py** -- `PluginDiscovery` discovers and loads entry-point plugins at startup.
- **resilience/circuit_breaker.py** -- `CircuitBreaker` (with `CircuitState` and
  `CircuitBreakerOpenError`) and `CircuitBreakerMiddleware` for guarding agent runs against
  cascading failures.
- **storage/** -- `DatabaseStore` and `LocalBackend` (behind the `StorageBackend` protocol)
  for binary/large-object persistence, with `WriteSession`, `LockToken` leasing,
  `RetryPolicy`, `StorageMetadata`, and a family of storage error types.

### Security Layer

The Security layer provides input sanitisation and prompt injection defence.

- **security/prompt_guard.py** -- `PromptGuard` scans user prompts for 25 known injection
  patterns (including encoding bypass, zero-width evasion, multi-language, jailbreak,
  and system prompt extraction), reports matches, and optionally sanitises suspicious
  fragments. `default_prompt_guard` provides a shared instance.
- **security/output_guard.py** -- `OutputGuard` scans LLM responses for PII (6 patterns),
  secrets (9 patterns), harmful content (4 patterns), custom patterns, and deny
  patterns. `default_output_guard` provides a shared instance. See the
  [Security Guide](security.md).
- **security/encryption.py** -- `EncryptionProvider` protocol with `AESEncryptionProvider`,
  and `EncryptedMemoryStore(store, encryption_key, provider=None)` which transparently
  encrypts `MemoryEntry.content` at rest (keys, metadata, and timestamps stay plaintext).

> Inbound-request authorization (RBAC/JWT) is intentionally **not** part of the framework --
> it is a hosting concern owned by the host service.

### Agent Layer

The Agent layer wraps Pydantic AI's `Agent` class and adds lifecycle management,
a global registry, delegation strategies, and declarative decorators.

- **base.py** -- `FireflyAgent` wraps `pydantic_ai.Agent` with metadata, hooks,
  middleware chain, run timeout, and streaming usage tracking.
- **registry.py** -- `AgentRegistry` is a thread-safe singleton that maps names to agents.
- **lifecycle.py** -- `AgentLifecycle` handles init, warmup, and shutdown hooks.
- **delegation.py** -- Multi-agent delegation. Strategies return
  `RoutingDecision` objects (ranked, scored `Candidate` tuples plus
  metadata). Built-ins: `RoundRobinStrategy`, `CapabilityStrategy`,
  `ContentBasedStrategy` (LLM routing), and `CostAwareStrategy` (priced
  via the cost resolver chain, pool-relative normalisation).
  Combinators `ChainStrategy`, `FallbackStrategy`, and `WeightedStrategy`
  nest strategies without subclassing. `DelegationRouter` separates
  `decide()` (pure, emits the `firefly.routing.decision` OTel event)
  from `execute()` (runs the chosen agent, forks memory); `route()`
  remains the one-call convenience.
- **context.py** -- `AgentContext` carries request-scoped data through an agent run.
- **decorators.py** -- `@firefly_agent` registers an agent declaratively.
- **middleware.py** -- `AgentMiddleware` protocol, `MiddlewareContext`, and `MiddlewareChain`
  for pluggable before/after hooks on every agent run.
- **builtin_middleware.py** -- The concrete middleware stack: `LoggingMiddleware`,
  `PromptGuardMiddleware`, `CostGuardMiddleware`, `ObservabilityMiddleware`,
  `ExplainabilityMiddleware`, `CacheMiddleware`, `OutputGuardMiddleware`,
  `ValidationMiddleware`, and `RetryMiddleware`. Two more live elsewhere:
  `PromptCacheMiddleware` (`prompt_cache.py`) and `CircuitBreakerMiddleware`
  (`resilience/`) -- 11 concrete middleware in total. By default `FireflyAgent` auto-wires
  `LoggingMiddleware` always, and `ObservabilityMiddleware` when `config.observability_enabled`
  is set; the rest are opt-in. (Rate-limit retry is handled inside `FireflyAgent.run()`
  rather than by `RetryMiddleware`.)
- **prompt_cache.py** -- `PromptCacheMiddleware` and `CacheStatistics` for prompt-level
  response caching.
- **fallback.py** -- `FallbackModelWrapper` and `run_with_fallback()` for
  automatic model failover. Accepts both `str` and `Model` objects for
  cross-provider fallback chains.
- **model_utils.py** -- Centralized model identity extraction
  (`extract_model_info`, `get_model_identifier`, `detect_model_family`) for
  uniform handling of both `"provider:model"` strings and `Model` objects
  across the framework's observability and resilience layers.
- **cache.py** -- `ResultCache` with TTL, LRU eviction, and thread-safe access.
- **templates/** -- Pre-built template agents (summarizer, classifier, extractor,
  conversational, router) available as factory functions. See the
  [Template Agents Guide](templates.md).

### Intelligence Layer

- **reasoning/** -- Pluggable reasoning patterns (ReAct, Chain of Thought, etc.)
  with a pipeline for chaining patterns sequentially.
- **observability/** -- Emits OpenTelemetry spans (`FireflyTracer`), custom metrics
  (`FireflyMetrics`), and events (`FireflyEvents`) through the OTel API; `UsageTracker`
  rolls up token usage, cost is resolved via the resolver chain (`resolve_cost`,
  `genai_prices_cost`, `provider_reported_cost`, `DEFAULT_RESOLVERS`; gated by the
  `cost_strict` config flag), and `BudgetGate` enforces budgets. Configuring the OTel SDK
  and exporters is the host service's responsibility.
- **explainability/** -- Decision recording (`TraceRecorder.record(category, ...)` with a
  `.records` property), natural-language explanation generation (`ExplanationGenerator`),
  audit trails (`AuditTrail.append(actor, action, ...)`), and report building
  (`ReportBuilder(title=...).build(records)`).

### Memory Layer

- **memory/conversation.py** -- `ConversationMemory`: token-aware, per-conversation
  chat history wrapping pydantic-ai's `message_history` mechanism.
- **memory/working.py** -- `WorkingMemory`: scoped key-value scratchpad for session
  facts, entities, and intermediate state.
- **memory/store.py** -- `MemoryStore` protocol with `InMemoryStore`, `FileStore`, and
  `SQLiteStore` backends for working facts. `memory/database_store.py` adds
  `PostgreSQLStore` and `MongoDBStore` with an owning driver loop and explicit close.
  Conversation history remains in process; use export/import to persist snapshots.
  `memory/summarization.py` provides `create_llm_summarizer`.
- **memory/manager.py** -- `MemoryManager` facade composing conversation and working
  memory, with `fork()` for multi-agent scope isolation.

### Embeddings & Vector Store Layer

These modules are reusable building blocks for retrieval-augmented workflows; the framework
ships no turnkey corpus/RAG agent, but `RetrievalStep` and `EmbeddingStep` (orchestration)
let you assemble retrieval pipelines.

- **embeddings/** -- `BaseEmbedder` (the `EmbeddingProtocol`), `EmbedderRegistry`, similarity
  helpers (`cosine_similarity`, `dot_product`, `euclidean_distance`), and 8 provider backends
  under `embeddings/providers/`: OpenAI, Azure, Cohere, Google, Mistral, Voyage, Bedrock,
  and Ollama.
- **vectorstores/** -- `BaseVectorStore` (the `VectorStoreProtocol`), `VectorStoreRegistry`,
  `VectorDocument`, `SearchFilter`/`SearchResult`, and 6 backends: `InMemoryVectorStore`,
  `ChromaVectorStore`, `PineconeVectorStore`, `QdrantVectorStore`, `PgVectorVectorStore`,
  and `SqliteVecVectorStore`. The scoped layer (`ScopedVectorStore`,
  `TenantScopedVectorStore`, `scope_namespace`, `parse_scope_namespace`) partitions a
  shared store by tenant/scope.

### Content Layer

- **content/chunking.py** -- `TextChunker`, `DocumentSplitter`, `ImageTiler`, and
  `BatchProcessor` for splitting large inputs into model-friendly chunks.
- **content/markdown_chunker.py** -- `MarkdownChunker` for structure-aware Markdown splitting.
- **content/compression.py** -- `ContextCompressor` with pluggable strategies
  (`TruncationStrategy`, `SummarizationStrategy`, `MapReduceStrategy`) and
  `SlidingWindowManager`. `ContextCompressor.compress(...)` is async.
- **content/binary/** (the `[binary]` extra) -- A document-conversion subsystem.
  `BinaryNormalizer` (configured by `BinaryConfig`) turns uploaded files into
  `BinaryArtifact`s: `sniff_media_type` detects the type, office documents are converted via
  `build_office_converter` (`GotenbergConverter` / `LibreOfficeConverter` /
  `NoOpOfficeConverter`, all implementing `OfficeConverter`), `PdfGuard` rejects encrypted or
  corrupt PDFs, `ImageNormalizer` standardises images, and `ArchiveUnpacker` / `EmailUnpacker`
  expand archives and email attachments.

### Validation Layer

- **validation/rules.py** -- Composable validation rules (`RegexRule`, `FormatRule`,
  `RangeRule`, `EnumRule`, `CustomRule`), `FieldValidator`, `OutputValidator`, and
  `ValidationReport`.
- **validation/qos.py** -- `ConfidenceScorer`, `ConsistencyChecker`,
  `GroundingChecker`, and `QoSGuard` (returning `QoSResult`) for post-generation quality
  checks.
- **validation/reviewer.py** -- `OutputReviewer` and `RubricReviewer` (LLM-as-judge, with
  `from_rubric_file(...)`) for criteria-based review, returning `ReviewResult` with
  `RetryAttempt` history.

### Orchestration Layer

- **pipeline/dag.py** -- `DAG`, `DAGNode`, `DAGEdge` with topological sort, cycle
  detection, execution-level grouping, and per-node `FailureStrategy`.
- **pipeline/engine.py** -- `PipelineEngine` runs DAGs with eager scheduling, concurrency,
  retries, timeouts, condition gates, and failure strategy enforcement.
- **pipeline/builder.py** -- Fluent `PipelineBuilder` for constructing pipelines.
- **pipeline/steps.py** -- Step executors implementing the `StepExecutor` protocol:
  `AgentStep`, `ReasoningStep`, `CallableStep`, `BranchStep`, `FanOutStep`, `FanInStep`,
  `BatchLLMStep`, `EmbeddingStep`, and `RetrievalStep`
  (`RetrievalStep(store, *, embedder=None, top_k=5, input_key="input")`).
- **pipeline/context.py** -- `PipelineContext` shared data bus, with state reducers
  (`append`, `extend`, `merge_dict`, `replace`) and control signals (`Pause`, `Send`).
- **pipeline/result.py** -- `NodeResult`, `PipelineResult`, and `ExecutionTraceEntry`.
- **pipeline checkpointing & audit** -- `Checkpointer` / `FileCheckpointer` (recording
  `CheckpointRecord`s) for resumable runs, and the audit-log family `AuditLog` /
  `FileAuditLog` / `LoggingAuditLog` / `OtelAuditLog` / `QueryableAuditLog` (emitting
  `AuditEntry`s). Event hooks are wired via `EventHandler` / `PipelineEventHandler`.

### Experimentation Layer (optional dev-tooling)

These are optional, leaf dev-tooling modules; the core framework never imports them.

- **experiments/** -- Define experiments with named variants, run them through an
  `ExperimentRunner(experiment, agent_factory, *, context=None)`, track metrics with
  `ExperimentTracker(storage_path=...)`, and compare results with `VariantComparator`.
- **lab/** -- Interactive sessions, benchmarks, datasets, side-by-side comparisons,
  and pluggable evaluators.

---

## Request Flow

This is the successful `run()` path. Tools execute only when requested by the model.
Reasoning patterns, output review, and explainability recording are explicit choices;
an ordinary run does not automatically invoke those components. Model failures call
configured error hooks before propagating the exception.

```mermaid
sequenceDiagram
    participant Caller
    participant Agent as FireflyAgent
    participant MW as Middleware chain
    participant Memory as ConversationMemory
    participant Options as ModelOptions resolver
    participant PAI as Pydantic AI agent
    participant Tools as Firefly tools

    Caller->>Agent: await run(prompt, conversation_id=cid)
    Agent->>MW: before_run in registration order
    alt Cache middleware supplies a result
        Agent->>MW: after_run in reverse order
    else Model invocation
        opt Memory attached and no explicit message_history
            Agent->>Memory: get_message_history(cid)
            Memory-->>Agent: typed provider messages
        end
        Agent->>Options: merge and validate settings for effective model
        Agent->>PAI: run(prompt, history, settings)
        opt Model requests function tools
            PAI->>Tools: execute arguments through guards and listeners
            Tools-->>PAI: tool result
        end
        PAI-->>Agent: run result
        opt Completed output and conversation_id supplied
            Agent->>Memory: add_turn with new_messages()
        end
        Agent->>Agent: record usage when cost tracking is enabled
        Agent->>MW: after_run in reverse order
    end
    Agent-->>Caller: result with output and messages
```

### Pipeline Execution Flow

For an acyclic graph without runtime routers, `PipelineEngine` schedules each node
as soon as its dependencies are resolved; it does not wait for a whole level. Cycles
and runtime routers use a frontier scheduler with a recursion limit. Port-based
steps implement `StepExecutor`; state-based nodes return updates merged by reducers.

```mermaid
flowchart TD
    BUILD["PipelineBuilder or PipelineEngine builder"] --> DAG["Nodes, edges and optional state schema"]
    DAG --> START["engine.run: new run or checkpoint resume"]
    START --> MODE{"Cycle or runtime router?"}
    MODE -->|no| READY["Schedule nodes whose dependencies are resolved"]
    READY --> RUN["Execute ready nodes concurrently"]
    RUN --> SAVE["Record results, state updates and checkpoints"]
    SAVE --> MORE{"Pending nodes?"}
    MORE -->|yes| READY
    MODE -->|yes| FRONTIER["Follow runtime frontier with recursion_limit"]
    FRONTIER --> STEP["Execute node or Send fan-out"]
    STEP --> ROUTE["Apply reducers and choose next targets"]
    ROUTE --> CONTINUE{"Continue?"}
    CONTINUE -->|yes| FRONTIER
    CONTINUE -->|no| RESULT["PipelineResult"]
    MORE -->|no| RESULT
    STEP -->|Pause returned| PAUSED["Checkpoint and return paused result"]
```

### Memory Architecture

`MemoryManager` composes process-local `ConversationMemory` and `WorkingMemory`.
Only working facts use the configured `MemoryStore`; selecting a database backend
does not persist chat history. The host stores and restores conversation snapshots.

```mermaid
flowchart TD
    MM["MemoryManager"] --> CM["ConversationMemory<br/>process-local typed messages"]
    MM --> WM["WorkingMemory<br/>scoped facts"]
    CM --> BUDGET["Token budget and optional summarization"]
    CM <-->|export and import| SNAPSHOT["Conversation snapshot<br/>host persists it"]
    WM --> STORE["MemoryStore contract"]
    STORE --> LOCAL["InMemoryStore, FileStore, SQLiteStore"]
    STORE --> DB["PostgreSQLStore, MongoDBStore"]
    DB --> LOOP["Shared database worker loop<br/>driver connections and cleanup"]
```

### Reasoning Pattern Architecture

All six reasoning patterns extend `AbstractReasoningPattern`, which provides a
template-method loop with an early-stop check after `_reason`, an iteration limit,
and optional final review. The diagram shows that base loop; Tree of Thoughts and
Goal Decomposition override `execute()` with their own flows while reusing helper
methods. See [Reasoning](reasoning.md) for each pattern's behavior.

```mermaid
flowchart TD
    CALL["Explicit pattern.execute or agent.run_with_reasoning"] --> INIT["Initialize trace and optional memory scope"]
    INIT --> THINK["_reason"]
    THINK --> STOP{"_should_stop?"}
    STOP -->|yes| OUTPUT["_extract_output"]
    STOP -->|no| ACT["_act"]
    ACT --> OBSERVE["_observe"]
    OBSERVE --> AGAIN{"_should_continue?"}
    AGAIN -->|no| OUTPUT
    AGAIN -->|yes| LIMIT{"Below max_steps?"}
    LIMIT -->|yes| THINK
    LIMIT -->|no| ERROR["ReasoningStepLimitError"]
    OUTPUT --> REVIEW["Optional reviewer"]
    REVIEW --> RESULT["Persist final working-memory fact<br/>return ReasoningResult"]
```

---

## Multi-Provider Support

The framework is **provider-agnostic**: it never re-implements a provider client.
Firefly normalizes model aliases and resolves factory configuration, then delegates
provider requests to Pydantic AI. Providers Pydantic AI supports — OpenAI, Anthropic, Google/Gemini, Groq, Bedrock, Mistral, Cohere,
DeepSeek, xAI, OpenRouter, Azure, Ollama, … — are selected with either a
`"provider:model"` string or a pydantic-ai `Model` object to any agent. Everything
the framework adds on top is built to be provider-uniform:

- **Identity normalisation** — `model_utils` (`get_model_identifier`,
  `extract_model_info`, `detect_model_family`) turns both `"provider:model"`
  strings and `Model` objects (reading the provider from the model's own
  `_provider.name`) into a canonical `provider:model` string. This single key feeds
  cost lookup, quota/backoff, and usage grouping, so a model object never "drops"
  its provider.
- **Cost** — pricing keys off that identifier across all providers, with
  provider-aware nuances: Gemini `thoughts_tokens` are counted (OpenAI/Anthropic
  fold reasoning into output), Bedrock vendor-prefixed ids get a retry on the bare
  model name, and an authoritative provider cost (OpenRouter `usage.cost`) wins when
  available. See [Observability → Cost Resolution](observability.md#cost-resolution).
- **Prompt caching** — routed by model *family*: Anthropic writes `cache_control`
  breakpoints, OpenAI supplies a routing key (its caching is automatic), Gemini uses
  `cachedContent`; Claude **via Bedrock/OpenRouter is skipped with a warning**
  (those backends cache differently). See [Agents → PromptCacheMiddleware](agents.md#promptcachemiddleware).
- **Tool schemas** — real `python_type`s keep tool schemas portable, with one
  caveat: **Gemini rejects free-form `dict[str, Any]` object schemas** — use a JSON
  string or a nested model instead. See [Tools](tools.md#full-fidelity-schemas-runcontext).
- **Failover & rate limits** — `FallbackModelWrapper` / `run_with_fallback` fail over
  across providers, and rate-limit backoff prefers a provider's structured retry hint
  (e.g. Gemini `retry_delay`) before falling back to exponential backoff.

The test suite includes controlled SDK-boundary tests for Chat Completions and
Responses, plus credential-gated live OpenAI and Anthropic tests. A passing offline
contract test does not establish availability in a provider account; see
[tests/README](https://github.com/fireflyframework/fireflyframework-agentic/blob/main/tests/README.md).

---

## Plugin System

Plugins are discovered via Python entry points under three well-known groups:
`fireflyframework_agentic.agents`, `fireflyframework_agentic.tools`, and
`fireflyframework_agentic.reasoning_patterns`. The `PluginDiscovery` class scans
these groups and loads the referenced objects into a `DiscoveryResult`. Discovery
does not automatically register returned objects; the host registers them, or an
imported plugin module may do so as an explicit side effect.

```mermaid
flowchart LR
    PACKAGE["Installed package entry points<br/>agents, tools, reasoning_patterns"] --> DISCOVERY["PluginDiscovery<br/>loads referenced objects"]
    DISCOVERY --> RESULT["DiscoveryResult<br/>successful objects and load errors"]
    RESULT --> HOST["Host selects and registers components"]
    HOST --> AGENTS["AgentRegistry"]
    HOST --> TOOLS["ToolRegistry"]
    HOST --> REASON["Reasoning registry"]
```

To create a plugin, add entry points in your package's `pyproject.toml`:

```toml
[project.entry-points."fireflyframework_agentic.agents"]
my_agent = "my_package.agents:MyAgent"

[project.entry-points."fireflyframework_agentic.tools"]
my_tool = "my_package.tools:MyTool"
```

Then call discovery at startup:

```python
from fireflyframework_agentic.plugin import PluginDiscovery

result = PluginDiscovery.discover_all()
print(f"Loaded {len(result.successful)} plugins, {len(result.failed)} failed")
```

---

## Configuration

All configuration is managed through `FireflyAgenticConfig`, which reads values from
environment variables prefixed with `FIREFLY_AGENTIC_`. For example:

```bash
export FIREFLY_AGENTIC_DEFAULT_MODEL=openai-responses:gpt-6-luna
export FIREFLY_AGENTIC_LOG_LEVEL=DEBUG
export FIREFLY_AGENTIC_OBSERVABILITY_ENABLED=true
export FIREFLY_AGENTIC_NATIVE_INSTRUMENTATION_ENABLED=true  # native pydantic-ai GenAI spans (see observability.md)
export FIREFLY_AGENTIC_REASONING_OUTPUT_MODE=prompted  # reasoning structured-output strategy (see reasoning.md)
```

> The framework emits telemetry through the OpenTelemetry API but does **not** configure the
> OTel SDK or any exporter. Wiring up the SDK/exporter endpoint (including any OTLP endpoint)
> is the host service's responsibility; `config.observability_enabled` only gates whether the
> framework emits spans and metrics. Supplying removed serving/exposure fields (e.g.
> `otlp_endpoint`, `rbac_enabled`, `cors_allowed_origins`) raises a `ValueError`.

The configuration singleton is available via:

```python
from fireflyframework_agentic import FireflyAgenticConfig

config = FireflyAgenticConfig()
print(config.default_model)
```

A host with its own configuration tree (a PyFly `pyfly.yaml`, a settings service) builds the
instance itself and hands it to the framework instead of exporting variables:

```python
from fireflyframework_agentic.config import set_config

set_config(FireflyAgenticConfig(default_model="anthropic:claude-opus-5", usage_tracker_max_records=1))
```

`set_config` installs the instance `get_config()` returns from then on — and tells whatever
was built from the previous one: the process usage tracker
(`observability.default_usage_tracker`, created when `agents.base` is imported) takes the new
`usage_tracker_max_records` and `budget_limit_usd` at once, so the install may follow the
imports, where it naturally sits. Anything else built at import time from `get_config()`
subscribes the same way with `on_config_installed(hook)`.

An agent may also carry a config of its own — `FireflyAgent(config=...)` — which scopes it to
that agent without touching the singleton, so a test harness or a multi-tenant host can build
two agents from two settings objects. What the scoped config governs: the default middleware,
`max_retries`, `default_temperature`, the cost gate (`cost_tracking_enabled`, `cost_strict`)
and the rate-limit back-off. What it does not: the process usage ledger, which every agent
shares and only `set_config` sizes. An agent that must record into a ledger of its own — one
per tenant, one per test — is given one:

```python
from fireflyframework_agentic.observability import UsageTracker

cfg = FireflyAgenticConfig(usage_tracker_max_records=1_000, budget_limit_usd=5.0)
agent = FireflyAgent("tenant-a", config=cfg, usage_tracker=UsageTracker.for_config(cfg))
agent.usage_tracker.get_summary()   # this agent's runs only
```
