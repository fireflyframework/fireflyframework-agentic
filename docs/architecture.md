# Architecture Guide

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

This document describes the high-level architecture of fireflyframework-genai, the
relationships between its modules, and the design principles that guided its construction.

---

## Design Principles

The framework follows four guiding principles:

1. **Protocol-driven contracts** -- Public APIs are defined as Python `Protocol` classes
   or abstract base classes. This allows any module to be replaced or extended without
   modifying framework internals.

2. **Convention over configuration** -- Sensible defaults are provided for every setting.
   A single `FireflyGenAIConfig` object (backed by Pydantic Settings) centralises
   configuration and supports environment-variable overrides.

3. **Layered composition** -- Modules are organised into layers (Core, Agent, Intelligence,
   Experimentation, Exposure). Higher layers depend on lower layers but never the reverse.

4. **Optional dependencies** -- Heavy third-party libraries (FastAPI, aiokafka, aio-pika,
   redis) are declared as extras. The core framework imports them lazily so that users
   only install what they need.

---

## Layer Diagram

```mermaid
graph TD
    subgraph Exposure Layer
        REST["REST API<br/><small>create_genai_app · SSE streaming · WebSocket<br/>health · auth middleware · router · conversations<br/>RateLimiter</small>"]
        QUEUES["Message Queues<br/><small>Kafka · RabbitMQ · Redis<br/>consumers · producers · QueueRouter</small>"]
    end

    subgraph Orchestration Layer
        PIPE["Pipeline / DAG Engine<br/><small>DAG · DAGNode · DAGEdge<br/>PipelineEngine · PipelineBuilder · PipelineEventHandler<br/>AgentStep · ReasoningStep · CallableStep · BranchStep<br/>FanOutStep · FanInStep · exponential backoff + jitter</small>"]
    end

    subgraph Experimentation Layer
        EXP["Experiments<br/><small>Experiment · Variant<br/>ExperimentRunner · VariantComparator<br/>ExperimentTracker</small>"]
        LAB["Lab<br/><small>LabSession · Benchmark<br/>EvalOrchestrator · EvalDataset<br/>ModelComparison</small>"]
    end

    subgraph Intelligence Layer
        REASON["Reasoning Patterns<br/><small>ReAct · CoT · PlanAndExecute<br/>Reflexion · ToT · GoalDecomposition<br/>ReasoningPipeline</small>"]
        VAL["Validation & QoS<br/><small>OutputReviewer · OutputValidator<br/>ConfidenceScorer · ConsistencyChecker<br/>GroundingChecker · 5 rule types</small>"]
        OBS["Observability<br/><small>FireflyTracer · FireflyMetrics<br/>FireflyEvents · UsageTracker<br/>CostCalculator · @traced · @metered<br/>configure_exporters</small>"]
        EXPL["Explainability<br/><small>TraceRecorder · ExplanationGenerator<br/>AuditTrail · ReportBuilder</small>"]
    end

    subgraph Security Layer
        SEC["Security<br/><small>PromptGuard (27 patterns) · OutputGuard<br/>PromptGuardResult · OutputGuardResult<br/>injection detection · sanitisation · output scanning</small>"]
    end

    subgraph Agent Layer
        AGT["Agents<br/><small>FireflyAgent · AgentRegistry<br/>DelegationRouter · AgentLifecycle<br/>@firefly_agent · 5 templates · 8 middleware<br/>4 delegation strategies · FallbackModelWrapper<br/>ResultCache · run timeout</small>"]
        TOOLS["Tools<br/><small>BaseTool · ToolBuilder · ToolKit · CachedTool<br/>5 guards · 3 composers · tool timeout<br/>ToolRegistry · 9 built-ins</small>"]
        PROMPTS["Prompts<br/><small>PromptTemplate · PromptRegistry<br/>3 composers · PromptValidator<br/>PromptLoader</small>"]
        CONTENT["Content<br/><small>TextChunker · DocumentSplitter<br/>ImageTiler · BatchProcessor<br/>ContextCompressor · SlidingWindowManager</small>"]
        MEM["Memory<br/><small>MemoryManager · ConversationMemory<br/>WorkingMemory · TokenEstimator<br/>InMemoryStore · FileStore<br/>summarization · create_llm_summarizer<br/>export/import · async wrappers</small>"]
    end

    subgraph Core Layer
        CFG["Config<br/><small>FireflyGenAIConfig<br/>get_config · reset_config</small>"]
        TYPES["Types & Protocols<br/><small>AgentLike · 10 protocols<br/>TypeVars · type aliases</small>"]
        EXC["Exceptions<br/><small>FireflyGenAIError hierarchy<br/>18 exception classes</small>"]
        PLUG["Plugin System<br/><small>PluginDiscovery<br/>3 entry-point groups</small>"]
    end

    REST --> PIPE
    QUEUES --> PIPE
    PIPE --> AGT
    PIPE --> REASON
    PIPE --> VAL
    SEC --> AGT
    LAB --> EXP
    EXP --> AGT
    REASON --> AGT
    OBS --> AGT
    EXPL --> OBS
    VAL --> AGT
    AGT --> TOOLS
    AGT --> PROMPTS
    AGT --> CONTENT
    AGT --> MEM
    AGT --> CFG
    TOOLS --> CFG
    PROMPTS --> CFG
    CONTENT --> CFG
    MEM --> CFG
    REASON --> CFG
    VAL --> CFG
```

### Protocol & Class Hierarchy

Every extension point is a `@runtime_checkable` protocol. Implement the protocol to
provide your own components; the framework discovers them via duck typing.

```mermaid
classDiagram
    class AgentLike {
        <<Protocol>>
        +run(prompt, **kwargs) Any
    }
    class ToolProtocol {
        <<Protocol>>
        +name: str
        +description: str
        +execute(**kwargs) Any
    }
    class GuardProtocol {
        <<Protocol>>
        +check(tool_name, kwargs) GuardResult
    }
    class ReasoningPattern {
        <<Protocol>>
        +execute(agent, input, **kwargs) ReasoningResult
    }
    class StepExecutor {
        <<Protocol>>
        +execute(context, inputs) Any
    }
    class DelegationStrategy {
        <<Protocol>>
        +select(agents, prompt, **kwargs) Any
    }
    class CompressionStrategy {
        <<Protocol>>
        +compress(text, max_tokens) str
    }
    class MemoryStore {
        <<Protocol>>
        +save(namespace, entry)
        +load(namespace) list
        +delete(namespace, entry_id)
        +clear(namespace)
    }
    class ValidationRule {
        <<Protocol>>
        +name: str
        +validate(value) ValidationRuleResult
    }
    class QueueConsumer {
        <<Protocol>>
        +start()
        +stop()
    }
    class QueueProducer {
        <<Protocol>>
        +publish(message)
    }

    AgentLike <|.. FireflyAgent
    AgentLike <|.. pydantic_ai.Agent
    ToolProtocol <|.. BaseTool
    ToolProtocol <|.. SequentialComposer
    ToolProtocol <|.. FallbackComposer
    ToolProtocol <|.. ConditionalComposer
    GuardProtocol <|.. ValidationGuard
    GuardProtocol <|.. RateLimitGuard
    GuardProtocol <|.. ApprovalGuard
    GuardProtocol <|.. SandboxGuard
    GuardProtocol <|.. CompositeGuard
    ReasoningPattern <|.. AbstractReasoningPattern
    ReasoningPattern <|.. ReasoningPipeline
    StepExecutor <|.. AgentStep
    StepExecutor <|.. ReasoningStep
    StepExecutor <|.. CallableStep
    StepExecutor <|.. BranchStep
    StepExecutor <|.. FanOutStep
    StepExecutor <|.. FanInStep
    DelegationStrategy <|.. RoundRobinStrategy
    DelegationStrategy <|.. CapabilityStrategy
    DelegationStrategy <|.. ContentBasedStrategy
    DelegationStrategy <|.. CostAwareStrategy
    CompressionStrategy <|.. TruncationStrategy
    CompressionStrategy <|.. SummarizationStrategy
    CompressionStrategy <|.. MapReduceStrategy
    MemoryStore <|.. InMemoryStore
    MemoryStore <|.. FileStore
    ValidationRule <|.. RegexRule
    ValidationRule <|.. FormatRule
    ValidationRule <|.. RangeRule
    ValidationRule <|.. EnumRule
    ValidationRule <|.. CustomRule
    QueueConsumer <|.. KafkaAgentConsumer
    QueueConsumer <|.. RabbitMQAgentConsumer
    QueueConsumer <|.. RedisAgentConsumer
    QueueProducer <|.. KafkaAgentProducer
    QueueProducer <|.. RabbitMQAgentProducer
    QueueProducer <|.. RedisAgentProducer
```

---

## Module Responsibilities

### Core Layer

The Core layer provides foundational types, configuration, exceptions, and the plugin
system. Every other module depends on at least one Core component.

- **types.py** -- Enumerations for model providers, agent states, and log levels.
- **config.py** -- `FireflyGenAIConfig`, a Pydantic Settings singleton that reads
  from environment variables and `.env` files.
- **exceptions.py** -- A structured exception hierarchy rooted at `FireflyGenAIError`.
- **plugin.py** -- `PluginDiscovery` discovers and loads entry-point plugins at startup.

### Security Layer

The Security layer provides input sanitisation and prompt injection defence.

- **security/prompt_guard.py** -- `PromptGuard` scans user prompts for 27 known injection
  patterns (including encoding bypass, zero-width evasion, multi-language, jailbreak,
  and system prompt extraction), reports matches, and optionally sanitises suspicious
  fragments.
- **security/output_guard.py** -- `OutputGuard` scans LLM responses for PII (6 patterns),
  secrets (9 patterns), harmful content (4 patterns), custom patterns, and deny
  patterns. See the [Security Guide](security.md).

### Agent Layer

The Agent layer wraps Pydantic AI's `Agent` class and adds lifecycle management,
a global registry, delegation strategies, and declarative decorators.

- **base.py** -- `FireflyAgent` wraps `pydantic_ai.Agent` with metadata, hooks,
  middleware chain, run timeout, and streaming usage tracking.
- **registry.py** -- `AgentRegistry` is a thread-safe singleton that maps names to agents.
- **lifecycle.py** -- `AgentLifecycle` handles init, warmup, and shutdown hooks.
- **delegation.py** -- Multi-agent delegation via `RoundRobinStrategy`,
  `CapabilityStrategy`, `ContentBasedStrategy` (LLM routing), and
  `CostAwareStrategy` (cheapest model), coordinated by `DelegationRouter`.
- **context.py** -- `AgentContext` carries request-scoped data through an agent run.
- **decorators.py** -- `@firefly_agent` registers an agent declaratively.
- **middleware.py** -- `AgentMiddleware` protocol and `MiddlewareChain` for
  pluggable before/after hooks on every agent run.
- **fallback.py** -- `FallbackModelWrapper` and `run_with_fallback()` for
  automatic model failover.
- **cache.py** -- `ResultCache` with TTL, LRU eviction, and thread-safe access.
- **templates/** -- Pre-built template agents (summarizer, classifier, extractor,
  conversational, router) available as factory functions. See the
  [Template Agents Guide](templates.md).

### Intelligence Layer

- **reasoning/** -- Pluggable reasoning patterns (ReAct, Chain of Thought, etc.)
  with a pipeline for chaining patterns sequentially.
- **observability/** -- OpenTelemetry tracing, custom metrics, event emission,
  usage tracking, cost calculation, and budget enforcement.
- **explainability/** -- Decision recording, natural-language explanation generation,
  audit trails, and report building.

### Experimentation Layer

- **experiments/** -- Define experiments with named variants, run them, track metrics,
  and compare results with statistical tests.
- **lab/** -- Interactive sessions, benchmarks, datasets, side-by-side comparisons,
  and pluggable evaluators.

### Memory Layer

- **memory/conversation.py** -- `ConversationMemory`: token-aware, per-conversation
  chat history wrapping pydantic-ai's `message_history` mechanism.
- **memory/working.py** -- `WorkingMemory`: scoped key-value scratchpad for session
  facts, entities, and intermediate state.
- **memory/store.py** -- `MemoryStore` protocol with `InMemoryStore` and `FileStore`.
- **memory/manager.py** -- `MemoryManager` facade composing conversation and working
  memory, with `fork()` for multi-agent scope isolation.

### Content Layer

- **content/chunking.py** -- `TextChunker`, `DocumentSplitter`, `ImageTiler`, and
  `BatchProcessor` for splitting large inputs into model-friendly chunks.
- **content/compression.py** -- `ContextCompressor` with pluggable strategies
  (truncation, summarisation, map-reduce) and `SlidingWindowManager`.

### Validation Layer

- **validation/rules.py** -- Composable validation rules (`Regex`, `Format`, `Range`,
  `Enum`, `Custom`), `FieldValidator`, `OutputValidator`, and `ValidationReport`.
- **validation/qos.py** -- `ConfidenceScorer`, `ConsistencyChecker`,
  `GroundingChecker`, and `QoSGuard` for post-generation quality checks.

### Orchestration Layer

- **pipeline/dag.py** -- `DAG`, `DAGNode`, `DAGEdge` with topological sort, cycle
  detection, execution-level grouping, and per-node `FailureStrategy`.
- **pipeline/engine.py** -- `PipelineEngine` runs DAGs with eager scheduling, concurrency,
  retries, timeouts, condition gates, and failure strategy enforcement.
- **pipeline/builder.py** -- Fluent `PipelineBuilder` for constructing pipelines.
- **pipeline/steps.py** -- Step executors: `AgentStep`, `ReasoningStep`,
  `CallableStep`, `FanOutStep`, `FanInStep`.
- **pipeline/context.py** -- `PipelineContext` shared data bus.
- **pipeline/result.py** -- `NodeResult`, `PipelineResult`, `ExecutionTraceEntry`.

### Exposure Layer

- **exposure/rest/** -- FastAPI application factory that auto-generates REST endpoints
  for every registered agent, with rate limiting, authentication middleware,
  WebSocket support, and conversation CRUD endpoints.
- **exposure/queues/** -- Abstract consumer/producer with Kafka, RabbitMQ, and Redis
  implementations and a pattern-based message router.

---

## Request Flow

The following diagram shows the typical lifecycle of a request entering through the
REST exposure layer, being processed by an agent with reasoning, and producing
observability and explainability artefacts.

```mermaid
sequenceDiagram
    participant Client
    participant REST as REST API<br/>(create_genai_app)
    participant MW as Middleware<br/>(CORS · RequestID)
    participant Reg as AgentRegistry
    participant Agent as FireflyAgent
    participant Mem as MemoryManager
    participant Reason as ReasoningPattern
    participant Tool as BaseTool / Guard
    participant Val as OutputReviewer
    participant OBS as FireflyTracer<br/>FireflyMetrics
    participant EXPL as TraceRecorder<br/>AuditTrail

    Client->>REST: POST /agents/{name}/run
    REST->>MW: apply middleware chain
    MW->>Reg: agent_registry.get(name)
    Reg-->>MW: FireflyAgent instance
    MW->>Agent: agent.run(prompt, conversation_id)
    Agent->>OBS: tracer.start_span("agent.run")
    Agent->>Mem: load conversation history
    Mem-->>Agent: message_history
    Agent->>Reason: pattern.execute(agent, prompt)
    loop Reasoning iterations (_reason → _act → _observe)
        Reason->>Agent: LLM call via pydantic_ai.Agent
        Reason->>Tool: guard.check() → tool.execute()
        Tool-->>Reason: tool result
        Reason->>OBS: metrics.record_tokens() · tracer.add_event()
        Reason->>EXPL: recorder.record_decision()
    end
    Reason-->>Agent: ReasoningResult(output, trace)
    Agent->>Val: reviewer.review(output)
    Val-->>Agent: validated output (retry on failure)
    Agent->>Mem: save conversation turn
    Agent->>OBS: tracer.end_span() · metrics.record_latency()
    Agent->>EXPL: audit_trail.append()
    Agent-->>REST: AgentResponse
    REST-->>Client: JSON response (or SSE stream)
```

### Pipeline Execution Flow

When agents are orchestrated through a `DAG` pipeline, `PipelineEngine` executes
nodes level-by-level. Each node wraps a `StepExecutor` implementation.

```mermaid
sequenceDiagram
    participant Caller
    participant Builder as PipelineBuilder
    participant DAG as DAG<br/>(topological sort)
    participant Engine as PipelineEngine
    participant Ctx as PipelineContext
    participant S1 as AgentStep
    participant S2 as ReasoningStep
    participant S3 as FanOutStep
    participant S4 as FanInStep
    participant S5 as CallableStep

    Caller->>Builder: .add_node() · .add_edge() · .chain()
    Builder->>DAG: build DAG with nodes and edges
    Caller->>Engine: engine.run(dag, inputs)
    Engine->>DAG: topological_sort() → execution levels
    Engine->>Ctx: create PipelineContext(inputs)
    loop For each execution level
        Engine->>Engine: asyncio.gather(nodes in level)
        Note over Engine: condition gate check per node
        alt AgentStep node
            Engine->>S1: execute(context, inputs)
            S1-->>Engine: agent output
        else ReasoningStep node
            Engine->>S2: execute(context, inputs)
            S2-->>Engine: reasoning result
        else FanOut → FanIn
            Engine->>S3: fan-out to parallel branches
            S3-->>Engine: branch outputs
            Engine->>S4: fan-in / aggregate
            S4-->>Engine: merged result
        else CallableStep node
            Engine->>S5: execute(context, inputs)
            S5-->>Engine: function output
        end
        Engine->>Ctx: store node results
    end
    Engine-->>Caller: PipelineResult(node_results, trace)
```

### Memory Architecture

`MemoryManager` composes `ConversationMemory` and `WorkingMemory`, delegating
persistence to a pluggable `MemoryStore` backend.

```mermaid
graph TD
    subgraph MemoryManager
        MM["MemoryManager<br/><small>new_conversation · fork<br/>get_working · get_conversation</small>"]
    end

    subgraph Conversation
        CM["ConversationMemory<br/><small>add_turn · get_history<br/>token budget · FIFO eviction</small>"]
        TE["TokenEstimator<br/><small>estimate_tokens</small>"]
    end

    subgraph Working
        WM["WorkingMemory<br/><small>set · get · delete<br/>scoped namespaces</small>"]
    end

    subgraph Backends
        IMS["InMemoryStore<br/><small>dict-backed</small>"]
        FS["FileStore<br/><small>JSON file per namespace</small>"]
    end

    MM --> CM
    MM --> WM
    CM --> TE
    WM -->|MemoryStore protocol| IMS
    WM -->|MemoryStore protocol| FS

    style MM fill:#4a90d9,color:#fff
    style CM fill:#7eb8da,color:#000
    style WM fill:#7eb8da,color:#000
```

### Reasoning Pattern Architecture

All six reasoning patterns extend `AbstractReasoningPattern`, which provides a
template-method loop: `_reason` → `_act` → `_observe` → `_should_continue`.

```mermaid
graph TD
    subgraph AbstractReasoningPattern
        EX["execute(agent, input)"]
        R["_reason()"]
        A["_act()"]
        O["_observe()"]
        SC["_should_continue()"]
        EX --> R --> A --> O --> SC
        SC -->|yes| R
        SC -->|no| OUT["ReasoningResult"]
    end

    subgraph Concrete Patterns
        REACT["ReActPattern<br/><small>observe → think → act</small>"]
        COT["ChainOfThoughtPattern<br/><small>step-by-step reasoning</small>"]
        PAE["PlanAndExecutePattern<br/><small>plan → execute → replan</small>"]
        REF["ReflexionPattern<br/><small>execute → critique → retry</small>"]
        TOT["TreeOfThoughtsPattern<br/><small>branch → evaluate → select</small>"]
        GD["GoalDecompositionPattern<br/><small>goal → phases → tasks</small>"]
    end

    subgraph Pipeline
        RP["ReasoningPipeline<br/><small>chains patterns sequentially</small>"]
    end

    REACT --> EX
    COT --> EX
    PAE --> EX
    REF --> EX
    TOT --> EX
    GD --> EX
    RP --> REACT
    RP --> COT
    RP --> PAE

    style EX fill:#e67e22,color:#fff
    style OUT fill:#27ae60,color:#fff
```

---

## Plugin System

Plugins are discovered via Python entry points under three well-known groups:
`fireflyframework_genai.agents`, `fireflyframework_genai.tools`, and
`fireflyframework_genai.reasoning_patterns`. The `PluginDiscovery` class scans
these groups and loads the referenced objects so they can self-register with
their respective registries.

```mermaid
flowchart LR
    subgraph Package pyproject.toml
        EP1["fireflyframework_genai.agents<br/><small>my_agent = my_pkg:MyAgent</small>"]
        EP2["fireflyframework_genai.tools<br/><small>my_tool = my_pkg:MyTool</small>"]
        EP3["fireflyframework_genai.reasoning_patterns<br/><small>my_pattern = my_pkg:MyPattern</small>"]
    end

    PD["PluginDiscovery<br/><small>discover_all() · discover_group()</small>"]

    subgraph Registries
        AR["AgentRegistry<br/><small>register · get · list_agents</small>"]
        TR["ToolRegistry<br/><small>register · get · list_tools</small>"]
        RR["Reasoning Registry<br/><small>(pattern catalog)</small>"]
    end

    EP1 --> PD
    EP2 --> PD
    EP3 --> PD
    PD --> AR
    PD --> TR
    PD --> RR
```

To create a plugin, add entry points in your package's `pyproject.toml`:

```toml
[project.entry-points."fireflyframework_genai.agents"]
my_agent = "my_package.agents:MyAgent"

[project.entry-points."fireflyframework_genai.tools"]
my_tool = "my_package.tools:MyTool"
```

Then call discovery at startup:

```python
from fireflyframework_genai.plugin import PluginDiscovery

result = PluginDiscovery.discover_all()
print(f"Loaded {len(result.successful)} plugins, {len(result.failed)} failed")
```

---

## Configuration

All configuration is managed through `FireflyGenAIConfig`, which reads values from
environment variables prefixed with `FIREFLY_GENAI_`. For example:

```bash
export FIREFLY_GENAI_DEFAULT_MODEL=openai:gpt-4o
export FIREFLY_GENAI_LOG_LEVEL=DEBUG
export FIREFLY_GENAI_OTEL_ENDPOINT=http://localhost:4317
```

The configuration singleton is available via:

```python
from fireflyframework_genai.core import FireflyGenAIConfig

config = FireflyGenAIConfig()
print(config.default_model)
```
