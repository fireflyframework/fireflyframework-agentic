# fireflyframework-agentic — Documentation

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](../LICENSE)

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

---

**fireflyframework-agentic** is the production-grade GenAI metaframework built on
[Pydantic AI](https://ai.pydantic.dev/). It extends the engine with composable
layers — from core configuration through agent management, intelligent reasoning,
experimentation, and pipeline orchestration — so that every concern
has a dedicated, protocol-driven module.

---

## Getting Started

- **[Installation](../README.md#installation)** — Install via `uv add`, `pip install`,
  or the interactive installer scripts (`install.sh` / `install.ps1`).
- **[Quick Start](../README.md#5-minute-quick-start)** — Configure a provider, define
  an agent, register a tool, and run your first prompt in 5 minutes.
- **[The Complete Tutorial](tutorial.md)** — An 18-chapter, hands-on guide covering
  every concept from zero to expert through a real-world IDP pipeline.

---

## Documentation Map

The framework is organised into layered modules. Each layer depends only on the layers
below it, keeping the dependency graph acyclic and each module independently testable.

### Core Layer

| | |
|---|---|
| **[Architecture](architecture.md)** | Design principles, layered model, protocol hierarchy, dependency flow |

### Agent Layer

| | |
|---|---|
| **[Agents](agents.md)** | `FireflyAgent`, `AgentRegistry`, `AgentLifecycle`, `@firefly_agent` decorator, middleware stack (`AgentMiddleware`, `MiddlewareChain`, `Logging`/`PromptGuard`/`CostGuard`/`Observability`/`Explainability`/`Cache`/`OutputGuard`/`Validation`/`Retry`/`PromptCache` middleware), 7 delegation strategies (round-robin, capability, content-based, cost-aware, chain, fallback, weighted), `FallbackModelWrapper` / `run_with_fallback`, `ResultCache` |
| **[Template Agents](templates.md)** | Five factory functions: summarizer, classifier, extractor, conversational, router |
| **[Tools](tools.md)** | `ToolProtocol`, `BaseTool`, `ToolBuilder`, guards, composition, caching, 9 built-in tools; full-fidelity schemas via `ParameterSpec(python_type=…)`, `RunContext` opt-in (`takes_ctx`), `ToolKit.as_toolset()` + re-exported native combinators (`FilteredToolset`, `WrapperToolset`, `ApprovalRequiredToolset`, …); human-in-the-loop tool approval (`requires_approval` / `is_deferred` / `deferred_tool_results` / `approval_handler`) |
| **[Prompts](prompts.md)** | `PromptTemplate`, `PromptRegistry`, composers, validation, loaders |
| **[Content](content.md)** | `TextChunker`, `MarkdownChunker`, `DocumentSplitter`, `ImageTiler`, `BatchProcessor`, compression; binary normalization (`content.binary`, `[binary]` extra: `BinaryNormalizer`, office/PDF/image/archive/email converters) |
| **[Memory](memory.md)** | `ConversationMemory`, `WorkingMemory`, `MemoryManager`, `InMemoryStore` / `FileStore` / `SQLiteStore` backends, `MemoryScope`, LLM summarisation |

### Embeddings & Vector Stores

| | |
|---|---|
| **[Embeddings](embeddings.md)** | `BaseEmbedder`, 8 providers (OpenAI, Azure, Cohere, Google, Mistral, Voyage, Bedrock, Ollama), auto-batching, similarity utilities, `EmbedderRegistry` |
| **[Vector Stores](vectorstores.md)** | `BaseVectorStore`, 6 backends (In-Memory, ChromaDB, Pinecone, Qdrant, pgvector, sqlite-vec), auto-embedding, `search_text`, namespaces, `ScopedVectorStore` / `TenantScopedVectorStore` multi-tenant scoping, `VectorStoreRegistry` |

### Intelligence Layer

| | |
|---|---|
| **[Reasoning Patterns](reasoning.md)** | 6 patterns (ReAct, CoT, Plan-and-Execute, Reflexion, ToT, Goal Decomposition), pipeline |
| **[Validation & QoS](validation.md)** | Rules, `OutputValidator`, `OutputReviewer`, `RubricReviewer` (LLM-as-judge), `QoSGuard`, confidence/consistency/grounding checks |

### Security

| | |
|---|---|
| **[Security](security.md)** | `PromptGuard` (25 patterns), `OutputGuard` (PII, secrets, harmful), encryption (`AESEncryptionProvider`, `EncryptedMemoryStore`), injection detection, input sanitisation, output scanning |
| **[Secure Script Execution](execution.md)** | `ExecutionEnvironment` protocol, `MontyEnvironment` (deny-by-default Rust sandbox, `[script-execution]` extra), `SecureScriptRunner` (validate→execute→capture), `analyze_code` / `SafetyPolicy` AST pre-screen, `ExecutionLimits`, Firefly Code Mode (`toolkit_external_functions`) |

### Observability

| | |
|---|---|
| **[Observability](observability.md)** | `FireflyTracer`, `FireflyMetrics`, `FireflyEvents`, `UsageTracker`, provider-agnostic cost resolvers (`resolve_cost`, `genai_prices_cost`, `provider_reported_cost`; provider-aware reasoning tokens), `BudgetGate`, `@traced`, `@metered`, opt-in native pydantic-ai instrumentation (`native_instrumentation_enabled` — GenAI spans per model request/tool call, nested under the agent span) — emits model/agent spans & metrics via the OpenTelemetry API (the host owns OTel SDK/exporter configuration) |
| **[Resilience](resilience.md)** | `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN state machine), `CircuitBreakerMiddleware` (records failures via the agent error lifecycle), `CircuitBreakerOpenError`, `CircuitState` |
| **[Storage](storage.md)** | Managed-SQLite-file durable layer — `StorageBackend`, `LocalBackend`, `DatabaseStore`, `WriteSession`, `LockToken` leasing, atomic writes |
| **[Explainability](explainability.md)** | `TraceRecorder`, `ExplanationGenerator`, `AuditTrail`, `ReportBuilder` |

### Experimentation Layer

| | |
|---|---|
| **[Experiments](experiments.md)** | `Experiment`, `Variant`, `ExperimentRunner`, `ExperimentTracker`, `VariantComparator` |
| **[Lab](lab.md)** | `LabSession`, `Benchmark`, `EvalOrchestrator`, `EvalDataset`, `ModelComparison` |

> **Optional developer tooling.** `experiments` and `lab` are leaf modules — nothing
> in the core imports them and they add no third-party dependencies. Import them only
> if you run experiments or evaluations; agent-building consumers can ignore them.

### Orchestration Layer

| | |
|---|---|
| **[Pipeline](pipeline.md)** | `DAG`, `PipelineEngine`, `PipelineBuilder`, step types (`AgentStep`, `ReasoningStep`, `CallableStep`, `FanOutStep`/`FanInStep`, `BranchStep`, `BatchLLMStep`, `EmbeddingStep`, `RetrievalStep`), parallel execution, retries, `Checkpointer` / `FileCheckpointer`, audit logs (`AuditLog`, `FileAuditLog`, `OtelAuditLog`, `QueryableAuditLog`), state reducers (`append`, `extend`, `merge_dict`, `replace`), `Pause` / `Send` control signals |
| **[Dynamic Workflows](workflows.md)** | Code-defined orchestration DSL over pydantic-ai agents — `@workflow`, `agent`/`parallel`/`pipeline`/`stream`/`phase`/`log`/`map_agents`; typed `Workflow[OutputT]`; `WorkflowBudget` (concurrency / agent-count / **token & USD cost / wall-clock** ceilings); `Journal` deterministic resume + durable `JournalBackend`/`FileJournalBackend`; `FireflyAgentRunner` (default — sub-agents get the full FireflyAgent stack) with `agent(..., using=)` multi-model targeting; `SmartRoutingRunner` + `cascade` cost optimization; `subworkflow`, `human` (HITL); verify combinators (`adversarial_verify`, `judge_panel`, `loop_until_dry`); `workflow_registry`, `run_workflow` |

### Runtime & Infrastructure

| | |
|---|---|
| **Resilience** (`fireflyframework_agentic.resilience`) | `CircuitBreaker`, `CircuitBreakerMiddleware`, `CircuitState`, `CircuitBreakerOpenError` — in-process circuit breaking for model/tool calls |
| **Storage** (`fireflyframework_agentic.storage`) | `StorageBackend`, `LocalBackend`, `DatabaseStore`, `WriteSession`, `LockToken` (leasing), `RetryPolicy`, `StorageMetadata` — pluggable binary/blob persistence with leasing and retries |

### Studio

Studio (visual IDE, project API, scheduling, tunnel exposure, BPM tutorial)
lives in a separate repository:
[fireflyframework-agentic-studio](https://github.com/fireflyframework/fireflyframework-agentic-studio).

---

## Tutorial

**[The Complete Tutorial](tutorial.md)** is an 18-chapter, hands-on guide that teaches
every concept from zero to expert through a real-world **Intelligent Document
Processing** pipeline. It covers configuration, agents, tools, prompts, reasoning,
content processing, memory, validation, pipelines, observability, explainability,
experiments, lab, multi-agent delegation, the plugin system, and advanced patterns.

---

## Use Cases

- **[IDP Pipeline](use-case-idp.md)** — A focused walkthrough of building a 7-phase
  Intelligent Document Processing pipeline that ingests, splits, classifies, extracts,
  validates, assembles, and explains data from corporate documents — including
  LLM-powered document splitting and explainability.

---

## Contributing

See the [Contributing Guide](../CONTRIBUTING.md) for development setup, coding
standards, testing, and the pull request process.

---

## Additional Resources

- **[Migration Guide](migration.md)** — Breaking & behavioural changes (tool `python_type`, `RunContext`, `FireflyAgentRunner` default) and how to update.
- **[Changelog](../CHANGELOG.md)** — Notable changes by version.
- **[License](../LICENSE)** — Apache License 2.0.
- **[Repository](https://github.com/fireflyframework/fireflyframework-agentic)** — Source code on GitHub.
- **[Pydantic AI](https://ai.pydantic.dev/)** — The underlying agent framework.

---

*Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.*
