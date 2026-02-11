```
  _____.__ _____.__
_/ ____\__|______ _____/ ____\ | ___.__.
\ __\| \_ __ \_/ __ \ __\| |< | |
 | | | || | \/\ ___/| | | |_\___ |
 |__| |__||__| \___ >__| |____/ ____|
                       \/ \/
  _____ __ /\
_/ ____\___________ _____ ______ _ _____________| | __ \ \
\ __\_ __ \__ \ / \_/ __ \ \/ \/ / _ \_ __ \ |/ / \ \
 | | | | \// __ \| Y Y \ ___/\ ( <_> ) | \/ < \ \
 |__| |__| (____ /__|_| /\___ >\/\_/ \____/|__| |__|_ \ \ \
                   \/ \/ \/ \/ \/
  ________ _____ .__
 / _____/ ____ ____ / _ \ |__|
/ \ ____/ __ \ / \ / /_\ \| |
\ \_\ \ ___/| | \/ | \ |
 \______ /\___ >___| /\____|__ /__|
        \/ \/ \/ \/
```

# fireflyframework-genai — Documentation

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](../LICENSE)
[![Version](https://img.shields.io/badge/version-26.01.01-blueviolet.svg)]()

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

---

**fireflyframework-genai** is the production-grade GenAI metaframework built on
[Pydantic AI](https://ai.pydantic.dev/). It extends the engine with six composable
layers — from core configuration through agent management, intelligent reasoning,
experimentation, pipeline orchestration, and service exposure — so that every concern
has a dedicated, protocol-driven module.

---

## Getting Started

- **[Installation](../README.md#installation)** — Install via `uv add`, `pip install`,
  or the interactive installer scripts (`install.sh` / `install.ps1`).
- **[Quick Start](../README.md#5-minute-quick-start)** — Configure a provider, define
  an agent, register a tool, and run your first prompt in 5 minutes.
- **[The Complete Tutorial](tutorial.md)** — A 20-chapter, hands-on guide covering
  every concept from zero to expert through a real-world IDP pipeline.

---

## Documentation Map

The framework is organised into six layers. Each layer depends only on the layers
below it, keeping the dependency graph acyclic and each module independently testable.

### Core Layer

| | |
|---|---|
| **[Architecture](architecture.md)** | Design principles, six-layer model, protocol hierarchy, dependency flow |

### Agent Layer

| | |
|---|---|
| **[Agents](agents.md)** | `FireflyAgent`, `AgentRegistry`, `AgentLifecycle`, delegation, `@firefly_agent` decorator |
| **[Template Agents](templates.md)** | Five factory functions: summarizer, classifier, extractor, conversational, router |
| **[Tools](tools.md)** | `ToolProtocol`, `ToolBuilder`, guards, composition patterns, 9 built-in tools |
| **[Prompts](prompts.md)** | `PromptTemplate`, `PromptRegistry`, composers, validation, loaders |
| **[Content](content.md)** | `TextChunker`, `DocumentSplitter`, `ImageTiler`, `BatchProcessor`, compression |
| **[Memory](memory.md)** | `ConversationMemory`, `WorkingMemory`, `MemoryManager`, storage backends |

### Intelligence Layer

| | |
|---|---|
| **[Reasoning Patterns](reasoning.md)** | 6 patterns (ReAct, CoT, Plan-and-Execute, Reflexion, ToT, Goal Decomposition), pipeline |
| **[Validation & QoS](validation.md)** | Rules, `OutputValidator`, `OutputReviewer`, confidence/consistency/grounding checks |

### Security

| | |
|---|---|
| **[Security](security.md)** | `PromptGuard` (27 patterns), `OutputGuard` (PII, secrets, harmful), `PromptGuardResult`, `OutputGuardResult`, injection detection, input sanitisation, output scanning |

### Observability

| | |
|---|---|
| **[Observability](observability.md)** | `FireflyTracer`, `FireflyMetrics`, `FireflyEvents`, `UsageTracker`, `CostCalculator`, `@traced`, `@metered`, `JsonFormatter`, exporters |
| **[Explainability](explainability.md)** | `TraceRecorder`, `ExplanationGenerator`, `AuditTrail`, `ReportBuilder` |

### Experimentation Layer

| | |
|---|---|
| **[Experiments](experiments.md)** | `Experiment`, `Variant`, `ExperimentRunner`, `ExperimentTracker`, `VariantComparator` |
| **[Lab](lab.md)** | `LabSession`, `Benchmark`, `EvalOrchestrator`, `EvalDataset`, `ModelComparison` |

### Orchestration Layer

| | |
|---|---|
| **[Pipeline](pipeline.md)** | `DAG`, `PipelineEngine`, `PipelineBuilder`, step types, parallel execution, retries |

### Exposure Layer

| | |
|---|---|
| **[REST Exposure](exposure-rest.md)** | `create_genai_app()`, auto-generated routes, SSE streaming, WebSocket, auth middleware, conversation CRUD, rate limiting, health checks |
| **[Queue Exposure](exposure-queues.md)** | Kafka, RabbitMQ, Redis consumers/producers, `QueueRouter` |

---

## Tutorial

**[The Complete Tutorial](tutorial.md)** is a 20-chapter, hands-on guide that teaches
every concept from zero to expert through a real-world **Intelligent Document
Processing** pipeline. It covers configuration, agents, tools, prompts, reasoning,
content processing, memory, validation, pipelines, observability, explainability,
experiments, lab, REST and queue exposure, deployment, and advanced patterns.

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

- **[Changelog](../CHANGELOG.md)** — Notable changes by version.
- **[License](../LICENSE)** — Apache License 2.0.
- **[Repository](https://github.com/fireflyframework/fireflyframework-genai)** — Source code on GitHub.
- **[Pydantic AI](https://ai.pydantic.dev/)** — The underlying agent framework.

---

*Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.*
