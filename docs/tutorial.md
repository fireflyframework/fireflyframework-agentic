# The Firefly GenAI Framework — Complete Tutorial

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

> **From Zero to Expert** — This tutorial walks you through every module in
> fireflyframework-genai by building a real project from scratch: an **Intelligent
> Document Processing (IDP)** pipeline that classifies, digitises, extracts, validates,
> and assembles data from invoices.
>
> Each chapter introduces a concept, explains *why* it exists, shows *how* it works
> with architecture diagrams, and immediately applies it to the IDP pipeline. By
> Chapter 20 you will have a production-grade GenAI application that uses agents,
> tools, prompts, reasoning patterns, content processing, memory, validation, pipelines,
> observability, explainability, experiments, a REST API, message-queue consumers **and
> producers** (Kafka, RabbitMQ, Redis), multi-agent delegation, template agents, and
> a plugin system — all wired together.

---

## Table of Contents

**Part I — Foundation**
1. [Introduction](#chapter-1-introduction) — What, who, why, design principles, running example
2. [Installation & Project Setup](#chapter-2-installation--project-setup) — UV, extras, `FireflyGenAIConfig`, model providers
3. [Your First Agent](#chapter-3-your-first-agent) — `FireflyAgent`, `@firefly_agent`, registry, context, lifecycle *(diagram)*
4. [Tools](#chapter-4-tools) — `@firefly_tool`, `ToolBuilder`, guards, composition, built-ins, `ToolKit`, attaching tools to agents *(diagram)*
5. [Prompts](#chapter-5-prompts) — Jinja2 templates, versioning, composition, validation, file loading

**Part II — Intelligence**

6. [Reasoning Patterns](#chapter-6-reasoning-patterns) — ReAct, CoT, Plan-and-Execute, Reflexion, Tree of Thoughts, Goal Decomposition, custom patterns *(diagram)*
7. [Content Processing](#chapter-7-content-processing) — Chunking, batch processing, compression, sliding window
8. [Memory](#chapter-8-memory) — Conversation memory, working memory, backends, `MemoryManager`, forking, integration points *(diagram)*
9. [Validation & Quality of Service](#chapter-9-validation--quality-of-service) — Rules, `OutputValidator`, QoS checks, `OutputReviewer`

**Part III — Orchestration & Operations**

10. [Pipeline](#chapter-10-pipeline) — DAG engine, step executors, fan-out/fan-in, retries, `PipelineContext` *(diagram)*
11. [Observability](#chapter-11-observability) — Tracing, metrics, events, OpenTelemetry exporters
12. [Explainability](#chapter-12-explainability) — Decisions, explanations, audit trail, reports

**Part IV — Experimentation & Deployment**

13. [Experiments](#chapter-13-experiments) — A/B testing, variant comparison, tracking
14. [Lab](#chapter-14-lab) — Interactive sessions, benchmarks, model comparison, eval datasets
15. [Exposure: REST API](#chapter-15-exposure-rest-api) — FastAPI factory, SSE streaming, health probes, CORS
16. [Exposure: Message Queues](#chapter-16-exposure-message-queues) — Consumers + producers for Kafka, RabbitMQ, Redis *(diagram)*

**Part V — Advanced**

17. [Template Agents](#chapter-17-template-agents) — Summariser, classifier, extractor, conversational, router
18. [Multi-Agent Delegation](#chapter-18-multi-agent-delegation) — Delegation router, strategies, memory forking *(diagram)*
19. [Plugin System](#chapter-19-plugin-system) — Entry-point discovery, packaging agents/tools/patterns
20. [Putting It All Together](#chapter-20-putting-it-all-together) — Full IDP implementation, project structure, production checklist *(full system diagram)*

---

# Part I — Foundation

---

## Chapter 1: Introduction

### What Is fireflyframework-genai?

fireflyframework-genai is a **GenAI metaframework** — it sits on top of
[Pydantic AI](https://ai.pydantic.dev/) and provides the structure, patterns, and
production-grade plumbing that Pydantic AI deliberately leaves to the application developer.

Think of Pydantic AI as the engine and fireflyframework-genai as the car around it:
the steering, brakes, GPS, dashboard, and everything else you need to actually drive
to your destination.

### Who Is It For?

- **Backend engineers** building GenAI features into existing applications.
- **ML/AI engineers** who want structured reasoning, validation, and observability out
  of the box.
- **Platform teams** who need a standard way to expose agents via REST APIs and queues.

### The Four Design Principles

The framework is guided by four principles that show up in every module:

1. **Protocol-driven contracts** — Public APIs are Python `Protocol` classes or abstract
   base classes. You can swap or extend any component without touching framework internals.
2. **Convention over configuration** — Sensible defaults everywhere. One `FireflyGenAIConfig`
   object (backed by Pydantic Settings) centralises every knob and reads from environment
   variables automatically.
3. **Layered composition** — Modules are organised into six layers (Core, Agent,
   Intelligence, Experimentation, Orchestration, Exposure). Higher layers depend on
   lower layers, never the reverse.
4. **Optional dependencies** — Heavy libraries (FastAPI, aiokafka, aio-pika, redis) are
   declared as extras. The core framework imports them lazily so you only install what
   you use.

### The Running Example: Intelligent Document Processing

Throughout this tutorial we build an **IDP pipeline** that processes invoices:

```
Raw Document → Classify → Digitise (OCR) → Extract Fields → Validate → Assemble Result
```

Every chapter teaches a framework concept and immediately applies it to a phase of this
pipeline. By Chapter 20 you will have the complete, production-ready system.

---

## Chapter 2: Installation & Project Setup

### Prerequisites

- **Python 3.13** or later.
- **UV** (recommended for dependency management): <https://docs.astral.sh/uv/>

### Creating a New Project

```bash
mkdir idp-service && cd idp-service
uv init
uv add fireflyframework-genai
```

This installs the core framework with its minimal dependencies: `pydantic-ai`,
`pydantic`, `pydantic-settings`, `jinja2`, and `opentelemetry-api/sdk`.

### Installing Extras

The framework provides optional extras for additional capabilities:

```bash
# REST API support (FastAPI + Uvicorn + SSE)
uv add "fireflyframework-genai[rest]"

# Individual message queue backends
uv add "fireflyframework-genai[kafka]"
uv add "fireflyframework-genai[rabbitmq]"
uv add "fireflyframework-genai[redis]"

# All queue backends at once
uv add "fireflyframework-genai[queues]"

# Everything (REST + all queues)
uv add "fireflyframework-genai[all]"
```

For our IDP project we will eventually use REST and queues, so install everything:

```bash
uv add "fireflyframework-genai[all]"
```

### Configuration with `FireflyGenAIConfig`

All framework settings live in a single Pydantic Settings class that reads from
environment variables prefixed with `FIREFLY_GENAI_`:

```python
from fireflyframework_genai import FireflyGenAIConfig, get_config

# get_config() returns a thread-safe singleton
config = get_config()
print(config.default_model) # "openai:gpt-4o"
print(config.default_temperature) # 0.7
print(config.max_retries) # 3
```

Override any setting via environment variables or a `.env` file:

```bash
# .env

# --- Provider API keys (read by Pydantic AI automatically) ---
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GEMINI_API_KEY=...
# GROQ_API_KEY=gsk_...
# DEEPSEEK_API_KEY=...

# --- Framework settings ---
FIREFLY_GENAI_DEFAULT_MODEL=openai:gpt-4o
FIREFLY_GENAI_DEFAULT_TEMPERATURE=0.3
FIREFLY_GENAI_LOG_LEVEL=DEBUG
FIREFLY_GENAI_OBSERVABILITY_ENABLED=true
```

Here are the most commonly used configuration fields:

- `default_model` — LLM model string (e.g. `"openai:gpt-4o"`, `"anthropic:claude-3-5-sonnet"`).
- `default_temperature` — Sampling temperature (0.0–1.0).
- `max_retries` — Default retry count for agent runs.
- `observability_enabled` — Toggle OpenTelemetry instrumentation.
- `otlp_endpoint` — OTLP exporter endpoint (default: console).
- `prompt_templates_dir` — Directory for Jinja2 prompt files.
- `default_chunk_size` / `default_chunk_overlap` — Content chunking defaults.
- `max_context_tokens` — Maximum context window (default 128,000).
- `validation_enabled` — Enable/disable output validation.
- `cost_tracking_enabled` — Enable/disable usage and cost tracking.
- `budget_limit_usd` / `budget_alert_threshold_usd` — Budget thresholds.
- `cost_calculator` — `"auto"`, `"static"`, or `"genai_prices"`.
- `memory_backend` — `"in_memory"` or `"file"`.
- `memory_max_conversation_tokens` — Token budget per conversation.

The singleton is created once and cached for the process lifetime. Call `reset_config()`
in tests to force re-creation.

### Model Providers & Authentication

Before you can run an agent against a real LLM, you need credentials for your model
provider. fireflyframework-genai delegates model communication entirely to
[Pydantic AI](https://ai.pydantic.dev/), which supports multiple providers out of the box.

#### Approach 1: Environment Variables (Recommended)

The simplest method — set the appropriate API key as an environment variable and use the
`"provider:model_name"` string format:

| Provider | Env Variable | Model String Example |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `"openai:gpt-4o"` |
| Anthropic | `ANTHROPIC_API_KEY` | `"anthropic:claude-sonnet-4-20250514"` |
| Google Gemini | `GEMINI_API_KEY` | `"google:gemini-2.0-flash"` |
| Groq | `GROQ_API_KEY` | `"groq:llama-3.3-70b"` |
| DeepSeek | `DEEPSEEK_API_KEY` | `"deepseek:deepseek-chat"` |
| Mistral | `MISTRAL_API_KEY` | `"mistral:mistral-large-latest"` |
| AWS Bedrock | `AWS_*` credentials | `"bedrock:anthropic.claude-3-5-sonnet-latest"` |
| Ollama (local) | *(none required)* | `"ollama:llama3.2"` |

Pydantic AI reads these variables automatically — you do not need to pass them to the
framework. Just set the key and use the model string:

```bash
# .env
OPENAI_API_KEY=sk-...
FIREFLY_GENAI_DEFAULT_MODEL=openai:gpt-4o
```

```python
from fireflyframework_genai.agents import FireflyAgent

# Uses OPENAI_API_KEY from the environment
agent = FireflyAgent(name="my-agent", model="openai:gpt-4o")
```

To switch providers, change the model string and API key — no code changes required:

```bash
# .env — switch to Anthropic
ANTHROPIC_API_KEY=sk-ant-...
FIREFLY_GENAI_DEFAULT_MODEL=anthropic:claude-sonnet-4-20250514
```

#### Approach 2: Programmatic Model Objects

For scenarios that require explicit credential management — Azure OpenAI, AWS Bedrock,
custom endpoints, or when you don't want to use environment variables — construct a
Pydantic AI `Model` object and pass it directly to `FireflyAgent`:

```python
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from fireflyframework_genai.agents import FireflyAgent

# Explicit API key (e.g. loaded from a vault)
model = OpenAIChatModel(
    "gpt-4o",
    provider=OpenAIProvider(api_key="sk-...")
)
agent = FireflyAgent(name="my-agent", model=model)
```

**Azure OpenAI:**

```python
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider

model = OpenAIChatModel(
    "my-gpt4o-deployment",
    provider=AzureProvider(
        azure_endpoint="https://my-resource.openai.azure.com",
        api_version="2025-03-01-preview",
        api_key="...", # or use DefaultAzureCredential
    ),
)
agent = FireflyAgent(name="azure-agent", model=model)
```

**Anthropic with explicit key:**

```python
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

model = AnthropicModel(
    "claude-sonnet-4-20250514",
    provider=AnthropicProvider(api_key="sk-ant-...")
)
agent = FireflyAgent(name="claude-agent", model=model)
```

**AWS Bedrock:**

```python
from pydantic_ai.models.bedrock import BedrockConverseModel

model = BedrockConverseModel(
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    region_name="us-east-1",
)
agent = FireflyAgent(name="bedrock-agent", model=model)
```

The framework's observability layer automatically detects Bedrock-hosted
models and resolves them to the correct model family for cost tracking
(Anthropic pricing), prompt caching (Anthropic cache configuration), and
rate-limit retry (Bedrock `ThrottlingException` detection).

**OpenAI-compatible endpoints** (e.g. Ollama, vLLM, LiteLLM):

```python
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

model = OpenAIChatModel(
    "llama3.2",
    provider=OpenAIProvider(
        base_url="http://localhost:11434/v1",
        api_key="ollama", # Ollama doesn't require a real key
    ),
)
agent = FireflyAgent(name="local-agent", model=model)
```

#### Which Approach Should I Use?

- **Environment variables** for standard cloud providers (OpenAI, Anthropic, Google,
  Groq, DeepSeek). This is the simplest path and works well in most deployments.
- **Programmatic `Model` objects** for Azure OpenAI, AWS Bedrock, self-hosted models,
  OpenAI-compatible servers, or when API keys are loaded from a secrets manager at
  runtime.

Both approaches work identically with every framework feature — tools, reasoning
patterns, pipelines, REST exposure, queue consumers, cost tracking, prompt caching,
and all other modules. The framework's `model_utils` module normalizes model
identity from both strings and `Model` objects, so observability and resilience
features work uniformly across all providers.

#### IDP Tie-In

For our IDP project, we will use environment variables. Make sure your `.env` contains the
API key for whichever provider you choose:

```bash
# .env
OPENAI_API_KEY=sk-...
FIREFLY_GENAI_DEFAULT_MODEL=openai:gpt-4o
FIREFLY_GENAI_DEFAULT_TEMPERATURE=0.3
FIREFLY_GENAI_OBSERVABILITY_ENABLED=true
```

---

## Chapter 3: Your First Agent

Every GenAI application starts with a single question: *"How do I talk to the model?"*
In raw Pydantic AI you create an `Agent`, give it a system prompt, and call `run()`.
That works great for scripts — but the moment you need to register agents by name,
share them across REST endpoints and queue consumers, attach lifecycle hooks, or plug
them into reasoning patterns and pipelines, you need a thin coordination layer on top.

That is exactly what `FireflyAgent` is. It wraps a Pydantic AI `Agent` and adds three
things the framework relies on: a **global registry** (so any module can look up an
agent by name), **lifecycle management** (init → warmup → shutdown), and **metadata**
(tags, descriptions, correlation IDs). The underlying Pydantic AI agent does all the
heavy lifting — model calls, tool dispatch, streaming — while `FireflyAgent` provides
the scaffolding that makes it a team player in a larger system.

### Agent System Architecture

The following diagram shows how `FireflyAgent` sits on top of Pydantic AI and connects
to the rest of the framework:

```mermaid
graph TB
    subgraph Application Code
        DEC["@firefly_agent decorator"]
        CLS["FireflyAgent class"]
    end

    subgraph Agent Layer
        FA["FireflyAgent"]
        PAI["pydantic_ai.Agent\n(model calls, tool dispatch, streaming)"]
        REG["AgentRegistry\n(singleton name → agent map)"]
        CTX["AgentContext\n(correlation_id, metadata, trace)"]
        LC["AgentLifecycle\n(init → warmup → shutdown)"]
    end

    subgraph Consumers
        REST["REST / API"]
        QUEUE["Queue Consumers"]
        PIPE["Pipelines"]
        DELEG["Delegation Router"]
        REASON["Reasoning Patterns"]
    end

    DEC -->|creates + registers| FA
    CLS -->|creates| FA
    FA -->|wraps| PAI
    FA -->|registers in| REG
    FA -->|carries| CTX
    FA -->|hooks| LC
    REG -->|lookup by name| REST
    REG -->|lookup by name| QUEUE
    REG -->|lookup by name| PIPE
    REG -->|lookup by name| DELEG
    REG -->|lookup by name| REASON
```

### Creating an Agent with the Decorator

The fastest way to create and register an agent is with the `@firefly_agent` decorator.
You write a function that returns the system prompt, and the framework takes care of
creating the agent, wiring the prompt, and registering it — all in one step:

```python
from fireflyframework_genai.agents import firefly_agent

# The decorator creates a FireflyAgent, uses this function as the dynamic
# instructions provider, and registers the agent in the global AgentRegistry.
@firefly_agent(name="greeter", model="openai:gpt-4o")
def greeter_instructions(ctx):
    # This function is called at the start of every run.
    # You can inspect `ctx` to customise the prompt per-request.
    return "You are a friendly greeter. Say hello and ask how you can help."
```

What happens behind the scenes:

1. A `FireflyAgent` named `"greeter"` is created with model `"openai:gpt-4o"`.
2. The decorated function becomes the agent's **dynamic instructions provider** — it is
   called at the start of every run and can use the context to customise the system prompt.
3. The agent is automatically registered in the global `AgentRegistry`, so any module
   (REST endpoints, pipelines, delegation routers) can look it up by name.

### Creating an Agent with the Class

When you need full control — custom output types, explicit tool lists, or you prefer
not to use decorators — instantiate `FireflyAgent` directly and register it yourself:

```python
from fireflyframework_genai.agents import FireflyAgent
from fireflyframework_genai.agents.registry import agent_registry

# Create the agent with a static instructions string and a typed output.
# The `output_type` tells Pydantic AI to validate the LLM's response as a dict.
classifier = FireflyAgent(
    name="document_classifier",
    model="openai:gpt-4o",
    instructions=(
        "You are a document classification expert. "
        "Given a document, determine its type (invoice, receipt, contract, form), "
        "language, and page count. Return JSON with keys: doc_type, language, page_count."
    ),
    output_type=dict,
)

# Register it so other parts of the framework (REST, queues, pipelines) can find it.
agent_registry.register(classifier)
```

### Running an Agent

Every agent supports three execution modes — pick the one that fits your context:

```python
# Async — the standard choice for production services.
result = await classifier.run("Classify this document: Invoice from Acme Corp...")
print(result.output) # {"doc_type": "invoice", "language": "en", "page_count": 1}

# Synchronous — handy for scripts, notebooks, and quick experiments.
result = classifier.run_sync("Classify this document: ...")
print(result.output)

# Streaming — for real-time UI feedback where you want tokens as they arrive.
async with classifier.run_stream("Classify this document: ...") as stream:
    async for chunk in stream:
        print(chunk, end="", flush=True)
```

### The Agent Registry

The `AgentRegistry` is a process-wide singleton that maps agent names to `FireflyAgent`
instances. This is the glue that lets any module — REST endpoints, queue consumers,
delegation routers, pipelines, reasoning patterns — discover and invoke agents without
importing them directly:

```python
from fireflyframework_genai.agents.registry import agent_registry

# Retrieve an agent by name — returns the FireflyAgent or raises KeyError.
agent = agent_registry.get("document_classifier")

# Check existence before retrieval.
if agent_registry.has("document_classifier"):
    print("Agent is registered")

# List all registered agents (useful for admin dashboards / health checks).
for info in agent_registry.list_agents():
    print(f"{info.name} ({info.model})")
```

### Agent Context

When a request arrives, you often need to carry metadata along the entire execution
path — who sent the request, which experiment is active, what trace ID to log.
`AgentContext` is that bag of request-scoped data:

```python
from fireflyframework_genai.agents.context import AgentContext

# Create a context with a correlation ID and arbitrary metadata.
# This context will be available in instructions providers and tool functions.
ctx = AgentContext(
    correlation_id="req-abc-123",
    metadata={"tenant": "acme-corp", "source": "email-inbox"},
)
```

The context is available inside dynamic instructions providers and tool functions,
allowing you to tailor behaviour per-request without global state.

### Lifecycle Management

Real-world agents often depend on external resources — database connections, model
caches, file handles. `AgentLifecycle` gives you three hooks to manage them cleanly:
**init** (one-time setup), **warmup** (pre-heat caches), and **shutdown** (release
resources):

```python
from fireflyframework_genai.agents.lifecycle import AgentLifecycle

lifecycle = AgentLifecycle()

# Each hook accepts a sync or async callable.
lifecycle.on_init(lambda: print("Loading resources..."))
lifecycle.on_warmup(lambda: print("Warming up model cache..."))
lifecycle.on_shutdown(lambda: print("Releasing resources..."))

# In your application startup/shutdown sequence:
await lifecycle.run_init()
await lifecycle.run_warmup()
# ... application serves requests ...
await lifecycle.run_shutdown()
```

### IDP Tie-In: The Document Classifier Agent

Time to build the first piece of our IDP pipeline. The document classifier receives
a raw document (text or scanned image) and outputs structured metadata — document type,
language, page count, and orientation. Every subsequent stage depends on this output.

```python
from fireflyframework_genai.agents import FireflyAgent

# The classifier is our pipeline's entry point — it decides how the document
# will be routed through digitisation, extraction, and validation.
classifier_agent = FireflyAgent(
    name="document_classifier",
    model="openai:gpt-4o",
    instructions=(
        "You are a document classification expert. Given a document (text or image), "
        "determine its type, language, and page count. "
        "Return JSON: {doc_type, language, page_count, orientation}."
    ),
    output_type=dict, # Pydantic AI will validate the LLM output as a dict
)
```

For multimodal input (e.g. scanned images), the framework provides typed content
wrappers that ensure the LLM receives the content in the right format:

```python
from fireflyframework_genai.types import ImageUrl

# Pass a list of mixed content — text instructions + an image.
# The framework converts ImageUrl into the provider-specific multimodal format.
result = await classifier_agent.run([
    "Classify this document:",
    ImageUrl(url="data:image/png;base64,<base64-data>"),
])
```

Other supported types include `AudioUrl`, `DocumentUrl`, and `VideoUrl`.

---

## Chapter 4: Tools

LLMs are powerful reasoners, but they cannot check a database, call an API, or read a
file on their own. **Tools** bridge that gap: they are functions the model can call
during a conversation to fetch data, trigger side-effects, or run computations.

Pydantic AI already supports tool functions, but fireflyframework-genai wraps them with
a richer layer: a **protocol-based type system** (`ToolProtocol` → `BaseTool`),
**guards** that enforce validation, rate-limiting, sandboxing, and approval policies
before a tool executes, **composition** primitives (sequential, fallback, conditional),
a **global registry** for discovery, and a **ToolKit** that can convert framework tools
into Pydantic AI tools for injection into any agent.

### Tool System Architecture

The following diagram shows the full tool stack — from how you create tools at the top,
through the guard chain, to how they reach an agent at the bottom:

```mermaid
graph TB
    subgraph "Tool Creation"
        DEC["@firefly_tool decorator"]
        BLD["ToolBuilder (fluent API)"]
        BLT["Built-in Tools\n(Http, FileSystem, DateTime, JSON, ...)"]
    end

    subgraph "Tool Protocol Layer"
        TP["ToolProtocol"]
        BT["BaseTool\n(name, description, execute)"]
    end

    subgraph "Guard Chain"
        CG["CompositeGuard"]
        VG["ValidationGuard"]
        RG["RateLimitGuard"]
        SG["SandboxGuard"]
        AG["ApprovalGuard"]
    end

    subgraph "Composition"
        SEQ["SequentialComposer"]
        FB["FallbackComposer"]
        COND["ConditionalComposer"]
    end

    subgraph "Registration & Bridging"
        TR["ToolRegistry\n(global catalog)"]
        TK["ToolKit\n(group + as_pydantic_tools)"]
    end

    subgraph "Agent Integration"
        FA["FireflyAgent(tools=[...])"]
        PAI["pydantic_ai.Agent\n(calls tools during LLM run)"]
    end

    DEC --> BT
    BLD --> BT
    BLT --> BT
    BT --> TR
    BT -.->|"guarded"| CG
    CG --> VG
    CG --> RG
    CG --> SG
    CG --> AG
    BT -.->|"compose"| SEQ
    BT -.->|"compose"| FB
    BT -.->|"compose"| COND
    TR --> TK
    TK -->|"as_pydantic_tools"| FA
    FA -->|"tools list"| PAI
```

### Creating a Tool with the Decorator

The fastest path — one decorator does everything:

```python
from fireflyframework_genai.tools import firefly_tool

# @firefly_tool creates a BaseTool, registers it in the global ToolRegistry,
# and makes it discoverable by name for ToolKit grouping and agent bridging.
@firefly_tool(name="lookup_vendor", description="Look up vendor details by name")
async def lookup_vendor(vendor_name: str) -> str:
    # In production, this would query a database or API.
    vendors = {"Acme Corp": "ID-001", "Globex": "ID-002"}
    return vendors.get(vendor_name, "Unknown vendor")
```

### Creating a Tool with the Builder

When you need more control — or want to build tools programmatically at runtime —
use the fluent `ToolBuilder`:

```python
from fireflyframework_genai.tools import ToolBuilder

async def fetch_exchange_rate(currency: str) -> float:
    """Simulated exchange rate lookup."""
    rates = {"USD": 1.0, "EUR": 0.85, "GBP": 0.73}
    return rates.get(currency, 0.0)

# The builder pattern lets you set each property explicitly.
# Call .build() to produce the final BaseTool instance.
exchange_tool = (
    ToolBuilder("exchange_rate")
    .description("Get exchange rate for a currency code")
    .parameter("currency", "str", description="Three-letter currency code")
    .handler(fetch_exchange_rate)
    .build()
)
```

### Tool Guards

In production, you rarely want a tool to run unconditionally. Guards are decorators
that wrap a tool's execution with policy checks — input validation, rate-limiting,
filesystem sandboxing, or human-in-the-loop approval. They run **before** the handler
(and optionally after), and they stack via `CompositeGuard`.

#### Validation Guard

Ensures that all required parameters are present before the tool handler runs:

```python
from fireflyframework_genai.tools import firefly_tool, guarded
from fireflyframework_genai.tools.guards import ValidationGuard

# The guard checks that all listed keys are present in kwargs.
@guarded(ValidationGuard(required_keys=["vendor_name"]))
@firefly_tool(name="lookup_vendor", description="Look up vendor")
async def lookup_vendor(vendor_name: str) -> str:
    ...
```

#### Rate Limit Guard

Prevents a tool from being called too frequently — essential for expensive or metered
external APIs:

```python
from fireflyframework_genai.tools.guards import RateLimitGuard

# Token-bucket limiter: 10 calls per 60-second sliding window.
@guarded(RateLimitGuard(max_calls=10, period_seconds=60))
@firefly_tool(name="web_search", description="Search the web")
async def web_search(query: str) -> str:
    ...
```

#### Sandbox Guard

Restricts tool arguments via allow/deny regex patterns — useful for preventing path
traversal, secret leakage, or access to dangerous locations:

```python
from fireflyframework_genai.tools.guards import SandboxGuard

# Allow paths under /tmp/uploads, deny path traversal (..) and .env files.
@guarded(SandboxGuard(
    allowed_patterns=[r"^/tmp/uploads"],
    denied_patterns=[r"\.\.", r"\.env"],
))
@firefly_tool(name="read_file", description="Read a file")
async def read_file(path: str) -> str:
    ...
```

#### Approval Guard

Requires explicit approval before execution — useful for destructive operations.
You provide an async callback that receives the tool name and kwargs and returns
`True` to approve:

```python
from fireflyframework_genai.tools.guards import ApprovalGuard

async def require_admin_approval(tool_name: str, kwargs: dict) -> bool:
    """In production, this would check a queue, Slack webhook, or admin UI."""
    print(f"Approve {tool_name} with {kwargs}? (auto-approved in dev)")
    return True

@guarded(ApprovalGuard(callback=require_admin_approval))
@firefly_tool(name="delete_record", description="Delete a database record")
async def delete_record(record_id: str) -> str:
    ...
```

### Composing Guards

Chain multiple guards with `CompositeGuard` — all must pass (AND semantics, evaluated
in order, first failure short-circuits):

```python
from fireflyframework_genai.tools.guards import CompositeGuard, ValidationGuard, RateLimitGuard

guard = CompositeGuard(guards=[
    ValidationGuard(required_keys=["query"]),
    RateLimitGuard(max_calls=5, period_seconds=30),
])
```

### Retryable Tools

The `@retryable` decorator wraps a tool's `execute` method with exponential-backoff
retry logic — useful for tools that call flaky external APIs:

```python
from fireflyframework_genai.tools import firefly_tool, retryable

@retryable(max_retries=3, backoff=1.0)
@firefly_tool(name="call_erp", description="Fetch data from the ERP API")
async def call_erp(query: str) -> str:
    # On failure, retries up to 3 times with 1s → 2s → 4s backoff
    ...
```

`@retryable` stacks with `@guarded` — guards run first, then retries wrap the handler:

```python
@retryable(max_retries=2)
@guarded(RateLimitGuard(max_calls=10, period_seconds=60))
@firefly_tool(name="web_search", description="Search the web")
async def web_search(query: str) -> str:
    ...
```

### Tool Composition

Combine tools into higher-level operations:

```python
from fireflyframework_genai.tools import SequentialComposer, FallbackComposer, ConditionalComposer

# Sequential: output of one becomes the `input` kwarg to the next.
# First positional arg is the composed tool's name.
pipeline = SequentialComposer(
    "fetch-parse-validate",
    [fetch_tool, parse_tool, validate_tool],
    description="Fetch, parse, then validate",
)

# Fallback: try tools in order until one succeeds; raise if all fail.
resilient = FallbackComposer(
    "resilient-api",
    [primary_api, secondary_api, cache_lookup],
)

# Conditional: a router_fn receives kwargs and returns a key into tool_map.
def select_parser(**kwargs) -> str:
    return "json" if kwargs.get("format") == "json" else "text"

router = ConditionalComposer(
    "format-router",
    router_fn=select_parser,
    tool_map={"json": json_parser, "text": text_parser},
)
```

### Built-In Tools

The framework ships with nine ready-to-use tools in `tools/builtins/`:

```python
from fireflyframework_genai.tools.builtins import (
    DateTimeTool, # Current date/time, timezone conversion
    JsonTool, # Parse, validate, extract, format JSON
    TextTool, # Word count, regex extract, truncate, replace
    CalculatorTool, # Safe math via AST parsing (no eval)
)

# Each tool follows ToolProtocol and can be registered and guarded
datetime_tool = DateTimeTool(default_timezone="America/New_York")
result = await datetime_tool.execute(action="now")

calculator = CalculatorTool()
result = await calculator.execute(expression="sqrt(144) + pi")
```

The full list: **HttpTool**, **FileSystemTool**, **SearchTool**, **DatabaseTool**,
**ShellTool**, **DateTimeTool**, **JsonTool**, **TextTool**, **CalculatorTool**.

### The Tool Registry

```python
from fireflyframework_genai.tools.registry import tool_registry

tool_registry.register(my_tool)
tool = tool_registry.get("my_tool")
all_tools = tool_registry.list_tools()
```

### ToolKit

A `ToolKit` groups related tools and can convert them to Pydantic AI tools for
direct injection into an agent:

```python
from fireflyframework_genai.tools import ToolKit
from fireflyframework_genai.tools.builtins import DateTimeTool, CalculatorTool

datetime_tool = DateTimeTool()
calculator = CalculatorTool()

kit = ToolKit("utility-tools", [datetime_tool, calculator], description="Common utilities")

# Register all tools in the toolkit at once
from fireflyframework_genai.tools import tool_registry
kit.register_all(tool_registry)
```

### Attaching Tools to Agents

The Firefly tool system (ToolRegistry, `@firefly_tool`, ToolKit) is a separate layer
from the Pydantic AI tool system baked into each agent. Here is how they connect:

**Approach 1: Pass Pydantic AI tool functions directly to `FireflyAgent`**

The `tools` parameter on `FireflyAgent` accepts any objects that Pydantic AI
recognises as tools — plain functions, `pydantic_ai.Tool` objects, etc.:

```python
from fireflyframework_genai.agents import FireflyAgent

async def lookup_vendor(ctx, vendor_name: str) -> str:
    return f"Details for {vendor_name}"

agent = FireflyAgent(
    name="extractor",
    model="openai:gpt-4o",
    tools=[lookup_vendor], # Pydantic AI tool functions
)
```

**Approach 2: Register tools after creation with decorator proxies**

`FireflyAgent` exposes `.tool()` and `.tool_plain()` decorator proxies that delegate
to the underlying Pydantic AI agent:

```python
agent = FireflyAgent(name="assistant", model="openai:gpt-4o")

@agent.tool_plain
async def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression)) # simplified example

@agent.tool
async def get_user(ctx, user_id: str) -> str:
    """Look up a user by ID (receives RunContext)."""
    return f"User {user_id}"
```

**Approach 3: Bridge Firefly tools via `ToolKit.as_pydantic_tools()`**

Firefly `BaseTool` instances (created with `@firefly_tool`, `ToolBuilder`, or built-ins)
live in the `ToolRegistry`. To feed them into an agent, convert via `as_pydantic_tools()`:

```python
from fireflyframework_genai.tools import ToolKit
from fireflyframework_genai.tools.builtins import DateTimeTool, JsonTool
from fireflyframework_genai.agents import FireflyAgent

kit = ToolKit("utilities", [DateTimeTool(), JsonTool()])

agent = FireflyAgent(
    name="helper",
    model="openai:gpt-4o",
    tools=kit.as_pydantic_tools(), # Convert to Pydantic AI tools
)
```

> **Key distinction:** `ToolRegistry` is a framework-level catalog for discovery and
> metadata. An agent only calls tools that are in its own Pydantic AI tools list.
> Use `ToolKit.as_pydantic_tools()` or `agent.tool()` to bridge between the two.

### IDP Tie-In: OCR and Vendor Lookup Tools

For our IDP pipeline, we need tools the extraction agent can call. We define them
with `@firefly_tool`, group them into a `ToolKit`, and attach them to the agent
via `as_pydantic_tools()`. This is the pattern you will see end-to-end in
Chapter 6 (reasoning patterns) and Chapter 20 (full IDP application).

**Step 1 — Define the tools:**

```python
from fireflyframework_genai.tools import firefly_tool, guarded
from fireflyframework_genai.tools.guards import RateLimitGuard

@guarded(RateLimitGuard(max_calls=100, period_seconds=60))
@firefly_tool(name="ocr_extract", description="Extract text from a document image via OCR")
async def ocr_extract(image_data: str) -> str:
    """In production, call an OCR service like AWS Textract or Google Vision."""
    return "Invoice #INV-2026-001\nVendor: Acme Corp\nAmount: $1,234.56\nDate: 2026-01-15"

@firefly_tool(name="vendor_lookup", description="Look up vendor details from the ERP system")
async def vendor_lookup(vendor_name: str) -> str:
    vendors = {
        "Acme Corp": '{"id": "V-001", "tax_id": "US-12345", "payment_terms": "NET30"}',
        "Globex": '{"id": "V-002", "tax_id": "US-67890", "payment_terms": "NET60"}',
    }
    return vendors.get(vendor_name, '{"error": "Vendor not found"}')
```

**Step 2 — Group into a ToolKit and attach to the extraction agent:**

```python
from fireflyframework_genai.tools import ToolKit
from fireflyframework_genai.tools.builtins import CalculatorTool
from fireflyframework_genai.agents import FireflyAgent

extraction_kit = ToolKit(
    "idp-extraction",
    [ocr_extract, vendor_lookup, CalculatorTool()],
    description="Tools for IDP invoice extraction",
)

extractor_agent = FireflyAgent(
    name="extractor",
    model="openai:gpt-4o",
    instructions="You are an invoice data extraction specialist.",
    tools=extraction_kit.as_pydantic_tools(), # Bridge Firefly tools → Pydantic AI
)
```

> **What happens next:** In Chapter 6 we pass `extractor_agent` (with its tools
> already attached) to reasoning patterns like Plan-and-Execute and Reflexion.
> The pattern calls `agent.run()` internally — the tools are available because
> they were bound here. Chapter 20 shows the complete production module
> (`idp/tools.py`) with retries, guards, and the full ToolKit.

---

## Chapter 5: Prompts

If tools are an agent's hands, prompts are its brain. The exact wording of a system
prompt can mean the difference between extracting 60% of invoice fields and 98%. In
production you need to **version** prompts (so you can A/B test), **compose** them
(system + context + task), **validate** them (catch missing variables before runtime),
and **load** them from files (so non-engineers can edit them).

The Prompts module provides all of this through a Jinja2-based template engine. Every
template is a first-class object with a name, a version, typed variables, and a render
method — not just a raw string.

### Creating a Prompt Template

```python
from fireflyframework_genai.prompts import PromptTemplate

extraction_prompt = PromptTemplate(
    "invoice_extraction",
    "You are an invoice data extraction specialist.\n\n"
    "Extract the following fields from the document text below:\n"
    "- invoice_number\n"
    "- vendor_name\n"
    "- total_amount (numeric)\n"
    "- due_date (ISO format)\n"
    "- line_items (list of {description, quantity, unit_price})\n\n"
    "Document text:\n{{ document_text }}\n\n"
    "Return valid JSON matching the schema above.",
    version="1.0.0",
)

rendered = extraction_prompt.render(document_text="Invoice #INV-001 from Acme Corp...")
```

Templates use Jinja2 syntax — `{{ variable }}`, `{% if %}`, `{% for %}`, filters, and
macros all work.

### Versioning

The `PromptRegistry` supports multiple versions of the same template. This is crucial
for A/B testing different prompt strategies:

```python
from fireflyframework_genai.prompts import PromptRegistry

registry = PromptRegistry()
registry.register(extraction_prompt_v1)
registry.register(extraction_prompt_v2)

# Get the latest version
latest = registry.get("invoice_extraction")

# Get a specific version
v1 = registry.get("invoice_extraction", "1.0.0")
```

### Composition

Templates can be composed using three strategies:

#### Sequential Composition

Render templates in order and join them — useful for building system + context + task prompts:

```python
from fireflyframework_genai.prompts.composer import SequentialComposer

# By default, templates are joined with "\n\n". Override with `separator=`.
composer = SequentialComposer(
    templates=[system_prompt, context_prompt, task_prompt],
    separator="\n\n",
)
full_prompt = composer.render(document_text="Invoice #INV-001...")
```

#### Conditional Composition

Select a template based on a runtime condition. The `condition_fn` receives the
render kwargs and returns a string key that maps into `template_map`:

```python
from fireflyframework_genai.prompts.composer import ConditionalComposer

# The condition function inspects the kwargs and returns a template key.
composer = ConditionalComposer(
    condition_fn=lambda **kwargs: "invoice" if kwargs.get("doc_type") == "invoice" else "generic",
    template_map={
        "invoice": invoice_prompt,
        "generic": generic_prompt,
    },
)
rendered = composer.render(doc_type="invoice", document_text="...")
```

#### Merge Composition

Render templates and merge with a custom function — full control over how pieces
combine:

```python
from fireflyframework_genai.prompts.composer import MergeComposer

# The merge_fn receives a list of rendered strings and returns the combined result.
composer = MergeComposer(
    templates=[header, body, footer],
    merge_fn=lambda parts: "\n---\n".join(parts),
)
full_prompt = composer.render(document_text="...")
```

### Validation

The `PromptValidator` checks rendered prompts against configurable constraints —
token limits and required sections — catching problems before they reach the LLM:

```python
from fireflyframework_genai.prompts import PromptValidator

# Validate that the rendered prompt fits within 4,000 tokens
# and contains the required "Return valid JSON" section.
validator = PromptValidator(max_tokens=4000, required_sections=["Return valid JSON"])
rendered = extraction_prompt.render(document_text="Invoice #INV-001 from Acme Corp...")
result = validator.validate(rendered)
if not result.valid:
    print(f"Prompt issues: {result.errors}")
```

### Using Prompts with Agents

So far we've created templates, versioned them, and composed them — but none of that
is useful until the rendered text reaches an agent. Here is how the two systems connect.

**Direct rendering → `agent.run()`** — The simplest path. Render a template and pass
the result as the prompt:

```python
from fireflyframework_genai.agents import FireflyAgent
from fireflyframework_genai.prompts import PromptTemplate

extraction_prompt = PromptTemplate(
    "invoice_extraction",
    "Extract invoice_number, vendor_name, total_amount, due_date from:\n\n"
    "{{ document_text }}\n\nReturn valid JSON.",
)

agent = FireflyAgent(name="extractor", model="openai:gpt-4o", output_type=dict)

# Render the template, then feed the result to the agent.
rendered = extraction_prompt.render(document_text=ocr_output)
result = await agent.run(rendered)
print(result.output) # {"invoice_number": "INV-001", ...}
```

**Composed prompts → `agent.run()`** — Use a composer when you need to assemble
multiple templates (system instructions + context + task) into one prompt:

```python
from fireflyframework_genai.prompts.composer import SequentialComposer

system = PromptTemplate("system", "You are a precise data extraction assistant.")
context = PromptTemplate("context", "Document type: {{ doc_type }}")
task = PromptTemplate("task", "Extract fields from:\n{{ document_text }}")

composer = SequentialComposer(templates=[system, context, task])
full_prompt = composer.render(doc_type="invoice", document_text=ocr_output)
result = await agent.run(full_prompt)
```

**Reasoning patterns use prompts internally** — Every reasoning pattern (Chapter 6)
has named prompt slots backed by `PromptTemplate` instances. When a ReAct pattern
calls `agent.run()`, it first renders its `"thought"` template, passes the result
to the agent, and records the output in the trace. You can override any slot:

```python
from fireflyframework_genai.reasoning import ReActPattern

# Override the built-in thought prompt with your own template.
custom = PromptTemplate("my:thought", "Think about: {{ context }}")
pattern = ReActPattern(prompts={"thought": custom})
```

See Chapter 6 → *Configurable Prompts* for the full list of prompt slots per pattern.

### Loading from Files

For large prompts or team workflows, store templates as files:

```python
from fireflyframework_genai.prompts import PromptLoader

loader = PromptLoader()

# Load a single file (.txt, .md, or .jinja2)
template = loader.load_file("prompts/invoice_extraction.jinja2")

# Load an entire directory
all_templates = loader.load_directory("prompts/")
```

The loader infers the template name from the filename (e.g. `invoice_extraction.jinja2`
becomes `"invoice_extraction"`).

### IDP Tie-In: Versioned Extraction Prompts

For our IDP pipeline, we create versioned prompts that can be A/B tested later:

```python
from fireflyframework_genai.prompts import PromptTemplate, PromptRegistry

prompt_registry = PromptRegistry()

# Version 1: Simple extraction
extraction_v1 = PromptTemplate(
    "idp_extraction",
    "Extract these fields from the invoice:\n"
    "- invoice_number, vendor_name, total_amount, due_date, line_items\n\n"
    "Text: {{ document_text }}\n\n"
    "Return valid JSON.",
    version="1.0.0",
)

# Version 2: More structured with examples
extraction_v2 = PromptTemplate(
    "idp_extraction",
    "You are an expert invoice parser. Extract structured data from the text below.\n\n"
    "Required fields:\n"
    " invoice_number: string (format: INV-NNNN)\n"
    " vendor_name: string\n"
    " total_amount: float\n"
    " due_date: string (ISO 8601)\n"
    " line_items: list of {description: str, quantity: int, unit_price: float}\n\n"
    "Example output:\n"
    '{"invoice_number": "INV-0001", "vendor_name": "Example", "total_amount": 100.0, '
    '"due_date": "2026-01-01", "line_items": [{"description": "Widget", "quantity": 2, '
    '"unit_price": 50.0}]}\n\n'
    "Document text:\n{{ document_text }}",
    version="2.0.0",
)

prompt_registry.register(extraction_v1)
prompt_registry.register(extraction_v2)

# In production, select the version based on experiment configuration
template = prompt_registry.get("idp_extraction") # Returns v2 (latest)
prompt = template.render(document_text=ocr_output)
```

---

# Part II — Intelligence

---

## Chapter 6: Reasoning Patterns

Here's a hard truth about LLMs: if you throw a complex question at an agent in a
single prompt, you're gambling. Sometimes the model nails it; sometimes it
hallucinated half the answer. **Reasoning patterns** fix that by giving the agent a
structured way to *think before it answers* — loops of thinking, acting, observing,
and reflecting, each step recorded so you can see exactly what happened.

The framework ships six patterns out of the box (ReAct, Chain of Thought,
Plan-and-Execute, Reflexion, Tree of Thoughts, Goal Decomposition). Each one is a
different strategy for the same problem: how do you turn "figure this out" into a
repeatable, observable, debuggable process?

### The Architecture

All patterns share the same core engine. `AbstractReasoningPattern` implements the
**Template Method** design pattern: the base class runs the outer loop (step counting,
trace recording, max-steps enforcement, optional output review), and each concrete
pattern overrides five hooks that define its behaviour:

```
_reason(state) → Generate a thought ("what do I think?")
_act(state) → Perform an action ("what should I do?")
_observe(state, act) → Process the action's result ("what happened?")
_should_continue() → Decide whether to loop again ("am I done?")
_extract_output() → Produce the final answer ("what's the result?")
```

Here is how all the pieces fit together:

```mermaid
graph TD
    subgraph AbstractReasoningPattern
        EX["execute(agent, input)"] --> R["_reason()"]
        R --> STOP{"_should_stop?"}
        STOP -->|no| A["_act()"]
        A --> O["_observe()"]
        O --> CONT{"_should_continue?"}
        CONT -->|yes| R
        CONT -->|no| OUT["_extract_output()"]
        STOP -->|yes| OUT
        OUT --> REV{"reviewer?"}
        REV -->|yes| REVIEW["OutputReviewer.review()"]
        REV -->|no| RESULT["ReasoningResult"]
        REVIEW --> RESULT
    end

    subgraph Six Patterns
        REACT["ReAct"]
        COT["Chain of Thought"]
        PAE["Plan-and-Execute"]
        REF["Reflexion"]
        TOT["Tree of Thoughts"]
        GD["Goal Decomposition"]
    end

    REACT -->|extends| EX
    COT -->|extends| EX
    PAE -->|extends| EX
    REF -->|extends| EX
    TOT -->|extends| EX
    GD -->|extends| EX
```

### How Reasoning Patterns Use Agent Tools

An important thing to understand: **reasoning patterns don't manage tools**. They
manage *thinking*. When a pattern needs to interact with the outside world (search a
database, call an API, do math), it delegates to `agent.run()` — and the agent's
configured Pydantic AI tools handle the rest.

This means you must attach tools to the agent *before* passing it to a pattern.
Here is the canonical flow, using the framework's tool system end-to-end:

```python
# ── Step 1: Define tools with @firefly_tool (see Chapter 4) ──────────────
# These are automatically registered in the global ToolRegistry.

from fireflyframework_genai.tools import firefly_tool, ToolKit

@firefly_tool(name="vendor_lookup", description="Look up vendor in the ERP system")
async def vendor_lookup(vendor_name: str) -> str:
    return '{"id": "V-001", "tax_id": "US-12345"}'

@firefly_tool(name="calculate", description="Evaluate a math expression safely")
async def calculate(expression: str) -> str:
    return str(eval(expression)) # simplified

# ── Step 2: Group tools in a ToolKit and bridge to Pydantic AI ───────────
# ToolKit.as_pydantic_tools() converts framework BaseTool instances into
# pydantic_ai.Tool objects that the LLM can call during agent.run().

extraction_tools = ToolKit(
    "extraction-tools",
    [vendor_lookup, calculate],
    description="Tools available during invoice extraction",
)

# ── Step 3: Create an agent WITH the bridged tools ──────────────────────

from fireflyframework_genai.agents import FireflyAgent

extractor = FireflyAgent(
    name="extractor",
    model="openai:gpt-4o",
    tools=extraction_tools.as_pydantic_tools(), # Bridge: Firefly → Pydantic AI
)

# ── Step 4: Pass the tool-equipped agent to a reasoning pattern ─────────
# The pattern calls extractor.run() internally, which triggers Pydantic AI's
# tool dispatch — the LLM decides when to call vendor_lookup or calculate.

from fireflyframework_genai.reasoning import ReActPattern

react = ReActPattern(max_steps=5)
result = await react.execute(extractor, "What is the total with tax for vendor Acme Corp?")
```

The runtime flow is: **Pattern → `agent.run(prompt)` → Pydantic AI → LLM decides to call tools → tool results → back to pattern loop**.

You can also skip the framework tool system and pass plain Pydantic AI tool functions
directly to `FireflyAgent(tools=[...])` — see Chapter 4 → *Attaching Tools to Agents*
for all three approaches.

### Architecture: Why Tools Are Explicitly Bound to Agents

You may wonder: *"If `@firefly_tool` already registers a tool in the global
`ToolRegistry`, why doesn't every agent automatically see every tool?"*

This is by design. The framework has **two separate layers** with different purposes:

1. **`ToolRegistry` (discovery layer)** — A global catalog of all tools in the system.
   Used for admin dashboards, documentation generation, plugin discovery, and pipeline
   wiring. Think of it as a phone book: it lists everything that exists.

2. **Agent tool binding (execution layer)** — The specific set of tools an agent can
   invoke during an LLM run. Only tools explicitly passed via `FireflyAgent(tools=[])`
   or `agent.tool()` are available to the model.

**Why explicit binding?**

- **Security** — An agent that processes user input should not have access to
  `ShellTool` or `delete_record`. Implicit auto-injection of all registered tools
  would create a dangerous attack surface.
- **Predictability** — When you read an agent definition, you can see *exactly* which
  tools it can call. No surprises from a plugin that registered a tool at import time.
- **Cost control** — Each tool in a Pydantic AI agent's tool list adds tokens to the
  system prompt. Injecting 50 tools when an agent only needs 3 wastes tokens and
  confuses the model.
- **Principle of least privilege** — Each agent gets the minimum set of tools required
  for its task, not the maximum set available.

Use `ToolKit` to curate which subset of registered tools each agent receives:

```python
from fireflyframework_genai.tools import ToolKit
from fireflyframework_genai.tools.registry import tool_registry

# Curate: only extraction-related tools for this agent
extraction_kit = ToolKit("extraction", [
    tool_registry.get("vendor_lookup"),
    tool_registry.get("calculate"),
])

extractor = FireflyAgent(
    name="extractor",
    model="openai:gpt-4o",
    tools=extraction_kit.as_pydantic_tools(),
)
```

### Memory in Reasoning Patterns

Reasoning patterns can also access the framework's memory system. When you pass a
`MemoryManager` via the `memory` keyword argument, it becomes available in the
pattern's internal state as `state["memory"]`. This lets pattern hooks read and write
working memory during iterations:

```python
from fireflyframework_genai.reasoning import PlanAndExecutePattern
from fireflyframework_genai.memory import MemoryManager

memory = MemoryManager(working_scope_id="extraction-session")

# Store a fact that the pattern's hooks can read
memory.set_fact("doc_type", "invoice")

# The memory kwarg is forwarded into state["memory"] inside the pattern
pattern = PlanAndExecutePattern(max_steps=15)
result = await pattern.execute(
    extractor_agent,
    "Extract invoice fields from the OCR text.",
    memory=memory, # Available as state["memory"] in _reason(), _act(), etc.
)
```

In pipelines, this happens automatically — `ReasoningStep` passes
`PipelineContext.memory` to the pattern (see Chapter 10).

### Structured Output Models

Patterns use typed Pydantic models instead of raw text. This is a big deal: instead
of parsing free-form strings for magic words like "FINISH", the model returns structured
objects with explicit fields. No more fragile regex parsing:

```python
from fireflyframework_genai.reasoning.models import (
    ReasoningThought,
    ReasoningAction,
    ReasoningPlan,
    PlanStepDef,
    StepStatus,
    ReflectionVerdict,
    BranchEvaluation,
    GoalDecompositionResult,
    GoalPhase,
)

# A structured thought — is_final replaces magic phrases like "FINISH"
thought = ReasoningThought(
    content="The invoice number is INV-2026-001",
    is_final=True,
    final_answer="INV-2026-001",
    confidence=0.95,
)

# A structured plan with step tracking
plan = ReasoningPlan(
    goal="Extract all invoice fields",
    steps=[
        PlanStepDef(id="s1", description="Find invoice number"),
        PlanStepDef(id="s2", description="Find vendor name", dependencies=["s1"]),
        PlanStepDef(id="s3", description="Find amount and date", dependencies=["s1"]),
    ],
)
# Each step has a status: pending → running → completed/failed/skipped
```

### The Six Built-In Patterns

#### 1. ReAct (Reasoning + Acting)

Interleaves thinking and tool use. Each iteration produces a `ReasoningThought`; when
`is_final=True`, the loop stops.

```python
from fireflyframework_genai.reasoning import ReActPattern

react = ReActPattern(max_steps=5)
result = await react.execute(my_agent, "What is the total on invoice INV-001?")
print(result.output)
print(f"Steps taken: {len(result.trace.steps)}")
```

**When to use:** Tasks that need external information (tool calls, searches, API lookups)
combined with reasoning.

#### 2. Chain of Thought

The agent reasons step by step through a problem. Each step is a `ReasoningThought`.

```python
from fireflyframework_genai.reasoning import ChainOfThoughtPattern

cot = ChainOfThoughtPattern(max_steps=10)
result = await cot.execute(my_agent, "Calculate the VAT on $1,234.56 at 20%.")
```

**When to use:** Math, logic puzzles, multi-step deductions where the agent needs to
show its work.

#### 3. Plan-and-Execute

The agent first generates a `ReasoningPlan` with `PlanStepDef` items, then executes
each step with status tracking (`pending → running → completed/failed`). Supports
replanning when steps fail.

```python
from fireflyframework_genai.reasoning import PlanAndExecutePattern

planner = PlanAndExecutePattern(max_steps=15, allow_replan=True)
result = await planner.execute(
    extractor_agent,
    "Extract all fields from this invoice:\n" + ocr_text,
)
```

**When to use:** Complex, multi-step tasks where you want visibility into progress and
the ability to recover from failures.

#### 4. Reflexion

Adds a self-evaluation loop. After generating output, the agent critiques itself via
a `ReflectionVerdict`. If `is_satisfactory=False`, the issues and suggestions are fed
back into a retry prompt.

```python
from fireflyframework_genai.reasoning import ReflexionPattern

reflexion = ReflexionPattern(max_steps=3)
result = await reflexion.execute(my_agent, "Write a unit test for binary search.")
```

**When to use:** Tasks where quality matters and the agent can meaningfully self-correct
(writing code, generating reports, data extraction).

#### 5. Tree of Thoughts

Explores multiple reasoning branches and evaluates each with a `BranchEvaluation`
(score + reasoning). The highest-scoring branch is selected.

```python
from fireflyframework_genai.reasoning import TreeOfThoughtsPattern

tot = TreeOfThoughtsPattern(branching_factor=3, max_depth=3)
result = await tot.execute(my_agent, "Design an API for a task management system.")
```

**When to use:** Open-ended problems with multiple valid approaches where you want to
explore and compare alternatives.

#### 6. Goal Decomposition

Breaks a high-level goal into structured `GoalPhase` objects, each with concrete tasks.

```python
from fireflyframework_genai.reasoning import GoalDecompositionPattern

decomposer = GoalDecompositionPattern(max_steps=20)
result = await decomposer.execute(my_agent, "Build an IDP pipeline for invoice processing.")
```

**When to use:** Strategic planning, project decomposition, breaking down large goals
into actionable phases.

### Configurable Prompts

Every pattern uses `PromptTemplate` instances for its LLM calls. You can override any
prompt by passing a `prompts` dict:

```python
from fireflyframework_genai.prompts.template import PromptTemplate, PromptVariable
from fireflyframework_genai.reasoning import ReActPattern

custom_thought = PromptTemplate(
    "my:react:thought",
    "Think carefully about: {{ context }}",
    variables=[PromptVariable(name="context")],
)
pattern = ReActPattern(prompts={"thought": custom_thought})
```

Each pattern has named prompt slots:

- **ReAct**: `"thought"`
- **Chain of Thought**: `"step"`
- **Plan-and-Execute**: `"plan"`, `"execute_step"`, `"replan"`
- **Reflexion**: `"critique"`, `"retry"`
- **Tree of Thoughts**: `"branch"`, `"evaluate"`
- **Goal Decomposition**: `"decompose"`, `"plan_phase"`

All built-in prompts are registered in the global `prompt_registry` under the
`reasoning:` namespace (e.g. `"reasoning:react:thought"`).

### Reasoning Pipeline

Chain patterns sequentially — the output of one becomes the input to the next:

```python
from fireflyframework_genai.reasoning import ReasoningPipeline, PlanAndExecutePattern, ReActPattern

pipeline = ReasoningPipeline([
    PlanAndExecutePattern(max_steps=15),
    ReActPattern(max_steps=10),
])
result = await pipeline.execute(my_agent, "Analyse the invoice and verify the totals.")
```

### Reasoning Trace

Every pattern records its work in a `ReasoningTrace`. The trace contains typed steps:

- **ThoughtStep** — The agent's reasoning.
- **ActionStep** — A tool invocation.
- **ObservationStep** — The result of an action.
- **ReflectionStep** — Self-evaluation.
- **PlanStep** — A plan or sub-goal.

```python
for step in result.trace.steps:
    print(f"[{step.step_type}] {step.content[:80]}...")
```

### Creating a Custom Pattern

Extend `AbstractReasoningPattern` and override the template methods:

```python
from fireflyframework_genai.reasoning.base import AbstractReasoningPattern

class VerifyAndCorrectPattern(AbstractReasoningPattern):
    def __init__(self, *, max_steps: int = 5):
        super().__init__("verify_and_correct", max_steps=max_steps)

    async def _reason(self, state):
        # Generate a thought about the current state
        ...

    async def _act(self, state):
        # Perform verification action
        ...

    async def _observe(self, state, action):
        # Process verification result
        ...

    async def _should_continue(self, state):
        # Continue until verification passes or max steps reached
        ...

    async def _extract_output(self, state):
        # Return the verified/corrected output
        ...
```

Register it to make it available framework-wide:

```python
from fireflyframework_genai.reasoning.registry import reasoning_registry

reasoning_registry.register("verify_and_correct", VerifyAndCorrectPattern)
```

### IDP Tie-In: Extraction with Plan-and-Execute + Reflexion

Now let's put reasoning patterns to work in our invoice pipeline. In Chapter 4
we defined IDP tools (`ocr_extract`, `vendor_lookup`) and grouped them into
`extraction_kit`. We also created `extractor_agent` with those tools attached
via `extraction_kit.as_pydantic_tools()`. Here we pass that agent — tools and
all — to reasoning patterns.

The extraction phase is the hardest part — we need to find invoice numbers,
vendor names, amounts, and line items from messy OCR text. A single-shot prompt
might miss something, so we use **Plan-and-Execute** to break it into steps, and
**Reflexion** as a safety net when validation catches errors:

```python
from fireflyframework_genai.reasoning import PlanAndExecutePattern, ReflexionPattern

# ── Recall from Chapter 4 ───────────────────────────────────────────
# extractor_agent = FireflyAgent(
# name="extractor",
# model="openai:gpt-4o",
# tools=extraction_kit.as_pydantic_tools(), # ocr_extract, vendor_lookup, CalculatorTool
# )
# The tools are already bound — reasoning patterns call agent.run() internally,
# so the agent can invoke any of its tools during each reasoning step.
# ─────────────────────────────────────────────────────────────────────

# Phase 3: Systematic extraction.
# Plan-and-Execute generates a plan ("find invoice number", "find vendor", ...)
# and executes each step with status tracking. If a step fails, it can replan.
extraction_pattern = PlanAndExecutePattern(max_steps=15, allow_replan=True)
extraction_result = await extraction_pattern.execute(
    extractor_agent, # Tools already attached in Ch4 via ToolKit.as_pydantic_tools()
    f"Extract invoice fields from:\n{ocr_text}",
)

# Phase 4: If validation catches errors (e.g. invalid date format), use Reflexion
# to let the agent critique its own output and self-correct.
if not validation_passed:
    reflexion = ReflexionPattern(max_steps=2)
    corrected = await reflexion.execute(
        extractor_agent,
        f"Previous extraction had errors: {errors}. Re-extract from:\n{ocr_text}",
    )
```

> **Architecture recap:** Reasoning patterns never see tools directly. They receive
> an agent (which owns its tools) and call `agent.run()`. This is why tools must be
> bound to the agent *before* passing it to a pattern — see the "Attaching Tools to
> Agents" section in Chapter 4 and the full `idp/tools.py` module in Chapter 20.

---

## Chapter 7: Content Processing

Here's a problem you'll hit fast: your 50-page invoice PDF produces OCR text that is
200,000 tokens long — but your model's context window is 128K, and you're paying per
token. You can't just shove the entire document into one call.

The Content module solves this with a three-stage pipeline:

1. **Chunk** — Split oversized content into overlapping pieces that each fit within a
   token budget. `TextChunker` handles text (by token, sentence, or paragraph),
   `DocumentSplitter` handles multi-page documents, and `ImageTiler` handles large
   images.
2. **Process** — Send chunks through an agent concurrently via `BatchProcessor`.
   This is where you do per-chunk OCR cleanup, translation, or summarisation.
3. **Compress** — Merge the results back into a single context that fits the
   downstream agent's window. `ContextCompressor` supports three strategies:
   truncation (cheap, lossy), summarisation (LLM-based, preserves meaning), and
   map-reduce (chunk → summarise each → merge).

Together they let you process documents of any size without losing information or
blowing up your bill.

### Content Processing Pipeline

```mermaid
graph LR
    subgraph "1. Chunk"
        TC["TextChunker"]
        DS["DocumentSplitter"]
        IT["ImageTiler"]
    end

    subgraph "2. Process"
        BP["BatchProcessor\n(concurrent agent calls)"]
    end

    subgraph "3. Compress"
        CC["ContextCompressor"]
        TR["TruncationStrategy"]
        SM["SummarizationStrategy"]
        MR["MapReduceStrategy"]
    end

    subgraph "Utilities"
        TE["TokenEstimator"]
        SW["SlidingWindowManager"]
    end

    TC --> BP
    DS --> BP
    IT --> BP
    BP --> CC
    CC --> TR
    CC --> SM
    CC --> MR
    TE -.-> TC
    TE -.-> CC
    TE -.-> SW
```

### Text Chunking

`TextChunker` splits text into overlapping chunks using one of three strategies:

```python
from fireflyframework_genai.content.chunking import TextChunker

chunker = TextChunker(
    chunk_size=4000, # Max tokens per chunk
    chunk_overlap=200, # Overlap between consecutive chunks
    strategy="paragraph", # "token" | "sentence" | "paragraph"
)

chunks = chunker.chunk(long_document_text)
for chunk in chunks:
    print(f"Chunk {chunk.index}/{chunk.total_chunks}: {len(chunk.content)} chars")
    # chunk.metadata contains additional info
```

Each chunk is a `Chunk` model with `content`, `index`, `total_chunks`,
`overlap_tokens`, and an open `metadata` dict.

**Strategy guide:**
- `"token"` — Split by estimated token count. Best for arbitrary text.
- `"sentence"` — Split at sentence boundaries. Best for natural language.
- `"paragraph"` — Split at paragraph boundaries (`\n\n`). Best for structured docs.

### Document Splitter

`DocumentSplitter` handles multi-document inputs, splitting at page breaks (`\f`) or
horizontal rules (`---`):

```python
from fireflyframework_genai.content.chunking import DocumentSplitter

splitter = DocumentSplitter(min_length=50)
segments = splitter.split(multi_page_text)
```

### Image Tiler

For large images that exceed a VLM's pixel budget, `ImageTiler` computes tile
coordinates:

```python
from fireflyframework_genai.content.chunking import ImageTiler

tiler = ImageTiler(tile_width=1024, tile_height=1024, overlap=128)
tiles = tiler.compute_tiles(image_width=4096, image_height=6144)
# Each tile is a Chunk with metadata: x, y, width, height, row, col
```

### Batch Processing

`BatchProcessor` sends chunks through an agent concurrently:

```python
from fireflyframework_genai.content.chunking import BatchProcessor

processor = BatchProcessor(concurrency=4)
results = await processor.process(ocr_agent, chunks)
```

### Context Compression

When concatenated chunks still exceed the extraction agent's context window, compress
them:

#### Truncation Strategy

Hard-cuts the text at a token limit:

```python
from fireflyframework_genai.content.compression import ContextCompressor, TruncationStrategy

compressor = ContextCompressor(strategy=TruncationStrategy())
compressed = await compressor.compress(full_text, max_tokens=8000)
```

#### Summarization Strategy

Uses an LLM agent to intelligently summarise:

```python
from fireflyframework_genai.content.compression import SummarizationStrategy

compressor = ContextCompressor(
    strategy=SummarizationStrategy(summary_agent)
)
compressed = await compressor.compress(full_text, max_tokens=8000)
```

#### Map-Reduce Strategy

Chunks the text, summarises each chunk in parallel, then merges the summaries:

```python
from fireflyframework_genai.content.compression import MapReduceStrategy

compressor = ContextCompressor(
    strategy=MapReduceStrategy(summary_agent)
)
compressed = await compressor.compress(full_text, max_tokens=8000)
```

### Sliding Window Manager

Maintains a sliding window over a stream of messages, keeping total token usage within
budget:

```python
from fireflyframework_genai.content.compression import SlidingWindowManager

window = SlidingWindowManager(max_tokens=8000)
window.add("First OCR page output...")
window.add("Second OCR page output...")
current_context = window.get_context() # Only recent items that fit
```

### Token Estimator

Estimate token counts without an API call:

```python
from fireflyframework_genai.content.compression import TokenEstimator

estimator = TokenEstimator() # Default ratio: 1.33 tokens per word
tokens = estimator.estimate("This is a test sentence.")
```

### IDP Tie-In: Processing Large Documents

In our IDP pipeline, the OCR phase may produce text that exceeds the extraction
agent's context window. Here's how we handle it:

```python
from fireflyframework_genai.content.chunking import TextChunker, BatchProcessor
from fireflyframework_genai.content.compression import ContextCompressor, MapReduceStrategy

# Step 1: Chunk the raw OCR output
chunker = TextChunker(chunk_size=3000, chunk_overlap=200, strategy="paragraph")
chunks = chunker.chunk(raw_ocr_text)

# Step 2: If needed, process chunks in parallel through OCR cleanup agent
processor = BatchProcessor(concurrency=4)
cleaned_chunks = await processor.process(ocr_cleanup_agent, chunks)

# Step 3: Compress for the extraction agent
full_text = "\n".join(c.output for c in cleaned_chunks)
compressor = ContextCompressor(
    strategy=MapReduceStrategy(summary_agent)
)
compressed_text = await compressor.compress(full_text, max_tokens=8000)
```

---

## Chapter 8: Memory

Without memory, every `agent.run()` call starts from scratch — the agent has no idea
what happened in the previous turn, what the pipeline figured out two steps ago, or
what facts a delegated sub-agent discovered. That's fine for one-shot tasks, but
real applications need context: multi-turn conversations, session state, pipeline
variables. The Memory module gives your agents a brain that persists across calls.

There are two kinds of memory here:
- **Conversation memory** — the actual chat history ("what was said"), automatically
  trimmed to stay within your token budget.
- **Working memory** — a key-value scratchpad ("what we know") for storing facts like
  `doc_type = "invoice"` that multiple agents or pipeline steps can read.

### Architecture

```mermaid
graph TD
    subgraph MemoryManager
        MM["MemoryManager<br/><small>new_conversation · fork<br/>set_fact · get_fact</small>"]
    end

    subgraph Conversation
        CM["ConversationMemory<br/><small>add_turn · get_history<br/>token budget · FIFO eviction</small>"]
    end

    subgraph Working
        WM["WorkingMemory<br/><small>set · get · delete<br/>scoped namespaces</small>"]
    end

    subgraph Backends
        IMS["InMemoryStore<br/><small>dict-backed</small>"]
        FS["FileStore<br/><small>JSON file per namespace</small>"]
        CS["YourCustomStore<br/><small>implements MemoryStore protocol</small>"]
    end

    subgraph Consumers
        AGT["FireflyAgent<br/><small>auto message_history</small>"]
        DR["DelegationRouter<br/><small>auto fork on delegation</small>"]
        PIPE["PipelineContext<br/><small>propagated to steps</small>"]
        RP["ReasoningPattern<br/><small>state['memory']</small>"]
    end

    MM --> CM
    MM --> WM
    WM --> IMS
    WM --> FS
    WM --> CS
    AGT --> MM
    DR --> MM
    PIPE --> MM
    RP --> MM
```

The system has four layers:

1. **ConversationMemory** — Token-aware, per-conversation chat history. Wraps
   Pydantic AI's `message_history` and drops the oldest turns when you exceed budget.
2. **WorkingMemory** — Scoped key-value scratchpad for facts and intermediate state.
3. **MemoryStore** — Pluggable persistence (`InMemoryStore`, `FileStore`, or yours).
4. **MemoryManager** — Facade that composes conversation + working memory behind a
   single API. This is the object you wire into agents, pipelines, and patterns.

### Quick Start

Here's the simplest way to give an agent a memory — attach a `MemoryManager` and pass
a `conversation_id` to each call:

```python
from fireflyframework_genai.agents import FireflyAgent
from fireflyframework_genai.memory import MemoryManager

# Create a memory manager with a 32K token budget for conversation history.
# When the history exceeds this, the oldest turns get dropped automatically.
memory = MemoryManager(max_conversation_tokens=32_000)

# Wire the memory into the agent. From now on, every run() call
# can participate in a persistent conversation.
agent = FireflyAgent(name="assistant", model="openai:gpt-4o", memory=memory)

# Start a new conversation — this returns a unique conversation ID.
conv_id = memory.new_conversation()

# Turn 1: the agent has no history yet.
result1 = await agent.run("What is Python?", conversation_id=conv_id)

# Turn 2: under the hood, FireflyAgent loads the message_history from Turn 1
# and passes it to Pydantic AI, so the model sees the full conversation.
result2 = await agent.run("What about its type system?", conversation_id=conv_id)
# result2 knows we were talking about Python — no context lost.
```

### Conversation Memory

`ConversationMemory` manages chat history per conversation ID. It enforces a token
budget by dropping the oldest turns (FIFO):

```python
from fireflyframework_genai.memory import ConversationMemory

conv_mem = ConversationMemory(max_tokens=16_000)
cid = conv_mem.new_conversation()

# After an agent run, store the turn
conv_mem.add_turn(
    cid,
    user_prompt="Hello",
    assistant_response="Hi there!",
    raw_messages=result.new_messages(),
)

# Before the next run, get trimmed history
history = conv_mem.get_message_history(cid)
```

When `FireflyAgent` has memory attached, this is all automatic.

### Working Memory

`WorkingMemory` is a scoped key-value store for facts and intermediate state:

```python
from fireflyframework_genai.memory import WorkingMemory

wm = WorkingMemory(scope_id="idp-session-42")
wm.set("doc_type", "invoice")
wm.set("vendor", "Acme Corp")

print(wm.get("doc_type")) # "invoice"
print(wm.to_dict()) # {"doc_type": "invoice", "vendor": "Acme Corp"}

# Render as a context block for prompt injection
print(wm.to_context_string())
# Working Memory:
# - doc_type: invoice
# - vendor: Acme Corp
```

Multiple `WorkingMemory` instances can share a backend while maintaining independent
namespaces:

```python
from fireflyframework_genai.memory import InMemoryStore, WorkingMemory

store = InMemoryStore()
agent_a_mem = WorkingMemory(store=store, scope_id="agent_a")
agent_b_mem = WorkingMemory(store=store, scope_id="agent_b")

agent_a_mem.set("key", "from A")
agent_b_mem.set("key", "from B")
assert agent_a_mem.get("key") == "from A" # Isolated
```

### Storage Backends

#### InMemoryStore

Dict-backed, fast, non-persistent. Ideal for testing and short-lived sessions:

```python
from fireflyframework_genai.memory import InMemoryStore
store = InMemoryStore()
```

#### FileStore

JSON file persistence. Each namespace gets its own file:

```python
from fireflyframework_genai.memory import FileStore
store = FileStore(base_dir=".firefly_memory")
```

#### Custom Backends

Implement the `MemoryStore` protocol:

```python
from fireflyframework_genai.memory import MemoryStore, MemoryEntry

class RedisStore:
    def save(self, namespace: str, entry: MemoryEntry) -> None: ...
    def load(self, namespace: str) -> list[MemoryEntry]: ...
    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None: ...
    def delete(self, namespace: str, entry_id: str) -> None: ...
    def clear(self, namespace: str) -> None: ...
```

### MemoryManager

The `MemoryManager` facade is the object you attach to agents, delegation routers, and
pipelines:

```python
from fireflyframework_genai.memory import MemoryManager

mgr = MemoryManager(
    max_conversation_tokens=32_000,
    working_scope_id="main-session",
)

# Conversation
cid = mgr.new_conversation()
mgr.add_turn(cid, "hello", "hi", raw_messages)
history = mgr.get_message_history(cid)

# Working memory
mgr.set_fact("doc_type", "invoice")
mgr.get_fact("doc_type") # "invoice"
```

### Forking

When delegating to a sub-agent or branching a pipeline, `fork()` creates a child
manager that shares conversation memory but gets **independent** working memory.
This means a delegated agent can store its own facts without overwriting the parent's:

```python
# Parent memory has facts about the overall session
mgr.set_fact("session_id", "abc-123")

# Fork for a sub-agent — it gets its own working memory scope
# but can still read the same conversation history.
child = mgr.fork(working_scope_id="sub-agent-classify")
child.set_fact("classification", "invoice") # Only visible in child
assert mgr.get_fact("classification") is None # Parent is unaffected
assert child.get_fact("session_id") is None # Child has its own scope
```

### Memory Integration Points

Memory flows through the framework in four ways. Understanding these is key to
building applications where context is never lost:

**1. Agent integration** — When `FireflyAgent` has a `MemoryManager` attached,
calling `run(prompt, conversation_id=cid)` automatically loads conversation
history as `message_history` before the call and stores new messages after it.
You never touch `message_history` manually.

**2. Delegation integration** — `DelegationRouter` automatically forks memory
when routing to a sub-agent, so the delegated agent gets its own working-memory
scope while sharing conversation context.

**3. Pipeline integration** — When you create `PipelineContext(memory=mgr)`,
both `AgentStep` and `ReasoningStep` propagate the memory to the agent and
pattern respectively. Facts stored in one step are readable in subsequent steps.

**4. Reasoning integration** — Pass `memory=mgr` as a keyword argument to
`pattern.execute(agent, input, memory=mgr)`. The memory object becomes
available as `state["memory"]` inside all pattern hooks (`_reason`, `_act`, etc.),
so custom patterns can read and write working memory during reasoning iterations.

### Configuration

Memory settings via environment variables:

```bash
export FIREFLY_GENAI_MEMORY_BACKEND=in_memory
export FIREFLY_GENAI_MEMORY_MAX_CONVERSATION_TOKENS=128000
export FIREFLY_GENAI_MEMORY_SUMMARIZE_THRESHOLD=10
export FIREFLY_GENAI_MEMORY_FILE_DIR=.firefly_memory
```

### IDP Tie-In: Carrying Facts Across Pipeline Steps

Now let's see why memory matters for our IDP pipeline. When the classifier figures
out that a document is an invoice, the extractor needs to know that — it selects
different prompts for invoices vs. receipts. Working memory is the bridge:

```python
from fireflyframework_genai.memory import MemoryManager

# One memory manager for the entire pipeline run.
# Every step can read and write facts here.
memory = MemoryManager(working_scope_id="idp-run-001")

# Phase 1: The classifier stores what it learned.
# These facts persist across all subsequent pipeline steps.
classification = {"doc_type": "invoice", "language": "en", "page_count": 2}
memory.set_fact("doc_type", classification["doc_type"])
memory.set_fact("language", classification["language"])
memory.set_fact("page_count", classification["page_count"])

# Phase 3: The extractor reads what the classifier discovered.
# This works because both steps share the same MemoryManager.
doc_type = memory.get_fact("doc_type") # "invoice"
# Now we can pick the invoice-specific extraction prompt.
```

---

## Chapter 9: Validation & Quality of Service

You've built an agent that extracts invoice data — but how do you *trust* the output?
LLMs are probabilistic: they can hallucinate an invoice number that doesn't exist,
format a date as "January 15th" instead of ISO 8601, or return an amount as a string
instead of a number. In production, bad data propagates downstream and causes real
damage.

The Validation module gives you a **two-layer defence**:

- **Layer 1 — Structural validation** catches deterministic errors. You define rules
  (regex, range, format, enum, or custom functions) for each field, group them into
  an `OutputValidator`, and run them against the extracted dict or Pydantic model.
  This is fast, cheap (no LLM call), and catches the most common failures: wrong
  date formats, out-of-range amounts, invalid invoice number patterns.

- **Layer 2 — Quality of Service (QoS)** catches statistical errors that rules can't
  see. `ConfidenceScorer` asks the LLM to self-rate its own output.
  `ConsistencyChecker` runs the same prompt multiple times and measures agreement —
  low agreement suggests hallucination. `GroundingChecker` verifies that extracted
  values actually appear in the source document (no LLM needed). `QoSGuard`
  composes all three into a single pass/fail gate.

Both layers can be wired into an `OutputReviewer` that wraps an agent call with
automatic retry: if structural validation or QoS fails, the reviewer feeds the
errors back to the agent and re-runs — up to `max_retries` times.

### Output Validation Rules

Rules are composable predicates that check a single field value:

```python
from fireflyframework_genai.validation.rules import (
    RegexRule,
    FormatRule,
    RangeRule,
    EnumRule,
    CustomRule,
    FieldValidator,
)

# Regex: field value must match a pattern.
# First arg is always the field name.
inv_rule = RegexRule("invoice_number", r"^INV-\d{4,10}$")

# Format: field matches a named format (email, url, date, uuid, iso_date)
date_rule = FormatRule("due_date", "iso_date")

# Range: numeric field within bounds
amount_rule = RangeRule("total_amount", min_value=0.01, max_value=10_000_000)

# Enum: field value is one of an allowed set
status_rule = EnumRule("status", ["approved", "rejected", "pending"])

# Custom: any predicate function
custom_rule = CustomRule(
    "vendor_name",
    lambda v: isinstance(v, str) and len(v.strip()) > 0,
    description="Value must be a non-empty string",
)
```

### Field Validator

Validates a single field against one or more rules:

```python
validator = FieldValidator("invoice_number", [inv_rule])
# validate() takes the field's value directly, not a dict.
results = validator.validate("INV-001234")
assert all(r.passed for r in results)
```

### Output Validator

Validates an entire structured output (dict or Pydantic model). The constructor
takes a dict mapping field names to lists of rules:

```python
from fireflyframework_genai.validation.rules import OutputValidator

validator = OutputValidator({
    "invoice_number": [RegexRule("invoice_number", r"^INV-\d{4,10}$")],
    "vendor_name": [RegexRule("vendor_name", r".{2,}")],
    "total_amount": [RangeRule("total_amount", min_value=0.01, max_value=10_000_000)],
    "due_date": [FormatRule("due_date", "iso_date")],
    "status": [EnumRule("status", ["approved", "rejected", "pending"])],
})

# validate() accepts a dict, Pydantic model, or any object with __dict__.
report = validator.validate(extracted_data)
if not report.valid:
    for err in report.errors:
        print(f" {err.field_name}: {err.message}")
```

### Quality of Service (QoS)

The QoS module provides post-generation quality checks. Each checker requires an
agent (for LLM-based evaluation) or operates purely on text (grounding).

#### Confidence Scorer

Asks the agent to self-evaluate its output confidence on a 0.0–1.0 scale:

```python
from fireflyframework_genai.validation.qos import ConfidenceScorer

# The scorer needs an agent — it sends a self-evaluation prompt to the LLM.
scorer = ConfidenceScorer(evaluator_agent)
score = await scorer.score("The invoice total is $1,234.56") # 0.0–1.0
```

#### Consistency Checker

Runs the same prompt multiple times and measures word-level agreement across
outputs (Jaccard similarity):

```python
from fireflyframework_genai.validation.qos import ConsistencyChecker

# The checker needs an agent and a run count. It runs the prompt num_runs times.
checker = ConsistencyChecker(extractor_agent, num_runs=3)
score, outputs = await checker.check("What is the capital of France?")
# score: float (1.0 = all answers agree), outputs: list[str]
print(f"Consistency: {score:.2f} across {len(outputs)} runs")
```

#### Grounding Checker

Verifies that extracted field values actually appear in the source document —
no agent needed, purely text-based:

```python
from fireflyframework_genai.validation.qos import GroundingChecker

checker = GroundingChecker(min_grounding_ratio=0.8)

# check() takes the source text and a dict of field_name → extracted_value.
score, field_map = checker.check(
    source_text="Invoice #INV-001: Total Amount: $1,234.56. Vendor: Acme Corp.",
    extracted_fields={"total": "$1,234.56", "vendor": "Acme Corp", "id": "INV-999"},
)
# score: float (fraction of grounded fields), field_map: dict[str, bool]
print(f"Grounding: {score:.2f}") # 0.67 (2 of 3 grounded)
print(f"Ungrounded: {[k for k, v in field_map.items() if not v]}") # ["id"]
```

#### QoS Guard

Composes all checks into a single gate. You build the individual checkers and
pass them in:

```python
from fireflyframework_genai.validation.qos import (
    QoSGuard, ConfidenceScorer, ConsistencyChecker, GroundingChecker,
)

# Build the individual checkers first.
guard = QoSGuard(
    confidence_scorer=ConfidenceScorer(evaluator_agent),
    consistency_checker=ConsistencyChecker(extractor_agent, num_runs=3),
    grounding_checker=GroundingChecker(),
    min_confidence=0.8,
    min_consistency=0.6,
    min_grounding=0.8,
)

# evaluate() takes the output string plus optional context for each check.
result = await guard.evaluate(
    str(extracted_data),
    prompt="Extract fields from the invoice.",
    source_text=ocr_text,
    extracted_fields={"total": "$1,234.56", "vendor": "Acme Corp"},
)
# result is a QoSResult with: .passed, .confidence, .consistency_score,
# .grounding_score, .details (dict with per-check info)
if result.passed:
    print("Quality check passed")
else:
    print(f"Failed: confidence={result.confidence:.2f}")
```

### Output Reviewer

The `OutputReviewer` closes the loop between generation and validation. It wraps an
agent call with **schema parsing + rule validation + automatic retry**. When the LLM
produces output that fails Pydantic parsing or validation rules, the reviewer
automatically retries with a feedback prompt describing exactly what was wrong.

#### Basic Usage

```python
from pydantic import BaseModel, Field
from fireflyframework_genai.validation import OutputReviewer

class InvoiceData(BaseModel):
    vendor: str
    amount: float = Field(ge=0)
    date: str
    invoice_number: str | None = None

reviewer = OutputReviewer(output_type=InvoiceData, max_retries=3)
result = await reviewer.review(
    agent,
    "Extract invoice data from: Acme Corp, $1,234, 2026-01-15",
)
print(result.output) # InvoiceData(vendor="Acme Corp", amount=1234.0, ...)
print(result.attempts) # 1 if first try succeeded, 2+ if retries needed
```

#### With Validation Rules

Combine schema parsing with field-level rules:

```python
from fireflyframework_genai.validation import OutputReviewer, OutputValidator, EnumRule

validator = OutputValidator({"vendor": [EnumRule("vendor", ["Acme Corp", "Globex"])]})
reviewer = OutputReviewer(
    output_type=InvoiceData,
    validator=validator,
    max_retries=2,
)
```

#### With Reasoning Patterns

Attach a reviewer to any reasoning pattern to validate the final output:

```python
from fireflyframework_genai.reasoning import ReActPattern
from fireflyframework_genai.validation import OutputReviewer

reviewer = OutputReviewer(output_type=InvoiceData, max_retries=2)
pattern = ReActPattern(reviewer=reviewer)
result = await pattern.execute(agent, "Extract invoice data from the document.")
# Output is automatically validated and retried if needed
```

#### ReviewResult

The result contains:

- `output` — The validated output.
- `attempts` — Total attempts (1 = first try succeeded).
- `validation_report` — The final `ValidationReport` if a validator was used.
- `retry_history` — List of `RetryAttempt` objects with attempt number, raw output,
  and error messages.

### IDP Tie-In: Validating Extracted Invoice Data

For our IDP pipeline, we combine structural validation, QoS checks, and the output
reviewer:

```python
from fireflyframework_genai.validation.rules import (
    OutputValidator, FieldValidator, RegexRule, FormatRule, RangeRule,
)
from fireflyframework_genai.validation.qos import QoSGuard
from fireflyframework_genai.validation import OutputReviewer
from pydantic import BaseModel, Field

# Define the expected output schema
class InvoiceExtraction(BaseModel):
    invoice_number: str
    vendor_name: str
    total_amount: float = Field(ge=0)
    due_date: str
    line_items: list[dict]

# Structural validation rules — dict of field_name -> list of rules
invoice_validator = OutputValidator({
    "invoice_number": [RegexRule("invoice_number", r"^INV-\d{4,10}$")],
    "vendor_name": [RegexRule("vendor_name", r".{2,}")],
    "total_amount": [RangeRule("total_amount", min_value=0.01, max_value=10_000_000)],
    "due_date": [FormatRule("due_date", "iso_date")],
})

# Output reviewer with schema + rules + retry
reviewer = OutputReviewer(
    output_type=InvoiceExtraction,
    validator=invoice_validator,
    max_retries=3,
)

# QoS guard — compose individual checkers with thresholds
from fireflyframework_genai.validation.qos import (
    QoSGuard, ConfidenceScorer, ConsistencyChecker, GroundingChecker,
)

qos = QoSGuard(
    confidence_scorer=ConfidenceScorer(evaluator_agent),
    consistency_checker=ConsistencyChecker(extractor_agent, num_runs=2),
    grounding_checker=GroundingChecker(),
    min_confidence=0.8,
    min_consistency=0.6,
    min_grounding=0.8,
)
```

---

# Part III — Orchestration & Operations

---

## Chapter 10: Pipeline

So far we have individual agents (classify, digitise, extract), tools (OCR, vendor
lookup), reasoning patterns (Plan-and-Execute, Reflexion), validation rules, and memory.
Each piece works in isolation — but a real IDP system needs to **wire them together**
into a single, reliable flow: classify → digitise → extract → validate → assemble.

The Pipeline module does exactly that. It models your processing flow as a **Directed
Acyclic Graph (DAG)** where nodes are processing steps and edges define data flow.
The engine schedules nodes by topological level — nodes at the same level run
concurrently — and handles retries, timeouts, and conditional execution automatically.

### Pipeline Execution Architecture

The following diagram shows how the pipeline engine executes a DAG:

```mermaid
graph LR
    subgraph "Pipeline Engine"
        B["PipelineBuilder"] --> DAG["DAG\n(topological sort)"]
        DAG --> L0["Level 0\n(no dependencies)"]
        DAG --> L1["Level 1\n(depends on L0)"]
        DAG --> L2["Level 2\n(depends on L1)"]
    end

    subgraph "Step Executors"
        AS["AgentStep\n(runs FireflyAgent)"]
        RS["ReasoningStep\n(runs pattern + agent)"]
        CS["CallableStep\n(runs async function)"]
        FO["FanOutStep\n(splits input)"]
        FI["FanInStep\n(merges outputs)"]
    end

    subgraph "Context & Results"
        PC["PipelineContext\n(inputs, metadata, memory)"]
        PR["PipelineResult\n(outputs, trace, duration)"]
    end

    L0 --> AS
    L1 --> RS
    L2 --> CS
    L0 & L1 & L2 -.->|concurrent within level| PC
    PC --> PR
```

### Core Concepts

A pipeline is a **Directed Acyclic Graph (DAG)** where:

- **Nodes** are processing steps (call an agent, run a reasoning pattern, execute a
  function).
- **Edges** define data flow and execution order.
- The **engine** schedules nodes by topological level — nodes at the same level run
  concurrently.

### The Pipeline Builder

The fluent `PipelineBuilder` is the recommended way to construct pipelines:

```python
from fireflyframework_genai.pipeline.builder import PipelineBuilder
from fireflyframework_genai.pipeline.steps import AgentStep, CallableStep, ReasoningStep

engine = (
    PipelineBuilder("invoice-pipeline")
    .add_node("classify", AgentStep(classifier_agent))
    .add_node("extract", AgentStep(extractor_agent))
    .add_node("validate", CallableStep(validate_fn))
    .chain("classify", "extract", "validate")
    .build()
)

result = await engine.run(inputs="<invoice text>")
```

### Step Executors

Five built-in executors cover most scenarios:

- **`AgentStep`** — Runs a `FireflyAgent` with the input as prompt.
- **`ReasoningStep`** — Runs a reasoning pattern through an agent.
- **`CallableStep`** — Wraps any `async` function `(context, inputs) -> output`.
- **`FanOutStep`** — Splits input into a list for parallel downstream processing.
- **`FanInStep`** — Merges outputs from multiple upstream nodes.

### Parallel Execution (Fan-Out / Fan-In)

Process multiple items concurrently:

```python
from fireflyframework_genai.pipeline.steps import FanOutStep, FanInStep

engine = (
    PipelineBuilder("parallel-ocr")
    .add_node("split", FanOutStep(lambda doc: doc.pages))
    .add_node("ocr_1", AgentStep(ocr_agent))
    .add_node("ocr_2", AgentStep(ocr_agent))
    .add_node("merge", FanInStep())
    .add_edge("split", "ocr_1")
    .add_edge("split", "ocr_2")
    .add_edge("ocr_1", "merge", input_key="page_1")
    .add_edge("ocr_2", "merge", input_key="page_2")
    .build()
)
```

### Conditional Execution

Gate nodes with a condition function. If the condition returns `False`, the node is
skipped:

```python
from fireflyframework_genai.pipeline.dag import DAGNode

dag.add_node(DAGNode(
    node_id="ocr",
    step=AgentStep(ocr_agent),
    condition=lambda ctx: ctx.metadata.get("needs_ocr", False),
))
```

### Retries and Timeouts

Configure per-node resilience:

```python
engine = (
    PipelineBuilder("robust-pipeline")
    .add_node("extract", AgentStep(extractor_agent), retry_max=3, timeout_seconds=30.0)
    .build()
)
```

Retries use linear backoff. On exhaustion, the node fails and the pipeline reports
`success=False`.

### Pipeline Context

`PipelineContext` is the shared data bus flowing through the DAG:

```python
from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.memory import MemoryManager

memory = MemoryManager(working_scope_id="invoice-run-42")

ctx = PipelineContext(
    inputs=document_bytes,
    metadata={"source": "email", "tenant": "acme-corp"},
    memory=memory,
)
result = await engine.run(context=ctx)
```

It carries: `inputs`, `metadata`, `correlation_id`, and results from completed upstream
nodes. When a `MemoryManager` is attached, `AgentStep` and `ReasoningStep`
automatically propagate memory to agents and patterns.

### Pipeline Result

`PipelineResult` aggregates all outcomes:

```python
result = await engine.run(context=ctx)

if result.success:
    print(result.final_output)
    print(f"Completed in {result.total_duration_ms:.0f} ms")
else:
    print(f"Failed nodes: {result.failed_nodes}")

# Inspect individual nodes
for node_id, node_result in result.outputs.items():
    print(f" {node_id}: {'ok' if node_result.success else 'FAILED'}")

# Execution trace for observability
for entry in result.execution_trace:
    print(f" [{entry.node_id}] {entry.status} ({entry.duration_ms:.0f} ms)")
```

### Manual DAG Construction

For full control, build the DAG directly:

```python
from fireflyframework_genai.pipeline.dag import DAG, DAGNode, DAGEdge
from fireflyframework_genai.pipeline.engine import PipelineEngine

dag = DAG("my-pipeline")
dag.add_node(DAGNode(node_id="step_a", step=my_step))
dag.add_node(DAGNode(node_id="step_b", step=other_step))
dag.add_edge(DAGEdge(source="step_a", target="step_b"))

engine = PipelineEngine(dag)
result = await engine.run(inputs="hello")
```

### IDP Tie-In: Wiring the Complete Pipeline

Here's our IDP pipeline as a DAG with all five phases:

```python
from fireflyframework_genai.pipeline.builder import PipelineBuilder
from fireflyframework_genai.pipeline.steps import AgentStep, ReasoningStep, CallableStep
from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.reasoning import PlanAndExecutePattern
from fireflyframework_genai.memory import MemoryManager

# Step functions for non-agent nodes
async def validate_step(context, inputs):
    extracted = inputs.get("input", {})
    report = invoice_validator.validate(extracted)
    context.metadata["validation_report"] = report
    return {"extracted": extracted, "valid": report.valid, "errors": report.errors}

async def assemble_step(context, inputs):
    data = inputs.get("input", {})
    return {
        "document_type": context.metadata.get("doc_type", "unknown"),
        "extracted_fields": data.get("extracted", {}),
        "validation_passed": data.get("valid", False),
    }

# Build the DAG
idp_pipeline = (
    PipelineBuilder("idp-pipeline")
    .add_node("classify", AgentStep(classifier_agent))
    .add_node("digitise", AgentStep(ocr_agent), retry_max=2, timeout_seconds=60)
    .add_node(
        "extract",
        ReasoningStep(PlanAndExecutePattern(max_steps=15), extractor_agent),
    )
    .add_node("validate", CallableStep(validate_step))
    .add_node("assemble", CallableStep(assemble_step))
    .chain("classify", "digitise", "extract", "validate", "assemble")
    .build()
)

# Execute
memory = MemoryManager(working_scope_id="idp-session")
ctx = PipelineContext(
    inputs=document_bytes,
    metadata={"source": "email-inbox", "tenant_id": "acme-corp"},
    memory=memory,
)
result = await idp_pipeline.run(context=ctx)

if result.success:
    print(f"Document type: {result.final_output['document_type']}")
    print(f"Extracted fields: {result.final_output['extracted_fields']}")
else:
    print(f"Pipeline failed at: {result.failed_nodes}")
```

---

## Chapter 11: Observability

Your pipeline is running in production, processing thousands of invoices a day. Then
latency spikes. Or accuracy drops. Or a customer reports a missing field. Without
observability you're flying blind — you have no idea which agent is slow, which tool is
failing, or how many tokens you're burning.

The Observability module wraps OpenTelemetry and gives you three primitives out of the
box: **tracing** (distributed spans across agents, tools, and pipeline steps), **metrics**
(counters, histograms, and gauges for latency, throughput, and token usage), and
**events** (structured logs for significant occurrences). When observability is
enabled, the framework instruments agent runs automatically — you get spans for free.

### Tracing

`FireflyTracer` wraps the OpenTelemetry `Tracer` and adds GenAI-specific attributes:

```python
from fireflyframework_genai.observability import FireflyTracer

tracer = FireflyTracer(service_name="idp-service")

with tracer.start_span("agent.run", attributes={"agent.name": "classifier"}) as span:
    result = await classifier_agent.run("Classify this document")
    span.set_attribute("tokens.total", 150)
```

#### The `@traced` Decorator

Automatically create a span around any function:

```python
from fireflyframework_genai.observability import traced

@traced(name="classify_document")
async def classify_document(text: str) -> dict:
    return await classifier_agent.run(text)
```

### Metrics

`FireflyMetrics` provides counters, histograms, and gauges:

```python
from fireflyframework_genai.observability import FireflyMetrics

metrics = FireflyMetrics(service_name="idp-service")

# Count invocations
metrics.increment("agent.invocations", labels={"agent": "classifier"})

# Record latency
metrics.record_histogram("agent.latency_ms", 142.5, labels={"agent": "classifier"})
```

#### The `@metered` Decorator

```python
from fireflyframework_genai.observability import metered

@metered(name="extraction")
async def extract_fields(text: str) -> dict:
    return await extractor_agent.run(text)
```

### Events

`FireflyEvents` emits structured events for significant occurrences:

```python
from fireflyframework_genai.observability import FireflyEvents

events = FireflyEvents()
events.emit("agent.started", {"agent": "classifier", "model": "gpt-4o"})
events.emit("pipeline.step.completed", {"step": "classify", "duration_ms": 250})
```

### Exporter Configuration

Configure where traces and metrics go:

```python
from fireflyframework_genai.observability import configure_exporters

# Send to an OTLP collector (Jaeger, Grafana Tempo, etc.)
configure_exporters(otlp_endpoint="http://localhost:4317")

# Or just print to console for development
configure_exporters(console=True)
```

Configuration via environment variables:

```bash
export FIREFLY_GENAI_OBSERVABILITY_ENABLED=true
export FIREFLY_GENAI_OTLP_ENDPOINT=http://localhost:4317
export FIREFLY_GENAI_LOG_LEVEL=DEBUG
```

### Usage Tracking & Cost Estimation

The framework automatically tracks token usage and estimates cost for every agent
run, reasoning step, and pipeline execution. `UsageTracker` accumulates
`UsageRecord` objects with input/output tokens, cost, latency, and model details.

```python
from fireflyframework_genai.observability import default_usage_tracker

# After running agents, inspect accumulated usage
summary = default_usage_tracker.get_summary()
print(f"Total tokens: {summary.total_tokens}")
print(f"Total cost: ${summary.total_cost_usd:.4f}")
print(f"Requests: {summary.total_requests}")

# Filter by agent or pipeline correlation ID
agent_summary = default_usage_tracker.get_summary_for_agent("extractor")
pipeline_summary = default_usage_tracker.get_summary_for_correlation("run-123")
```

Cost is calculated via `CostCalculator` — either a built-in static price table or
the optional `genai-prices` library for up-to-date pricing:

```python
from fireflyframework_genai.observability import get_cost_calculator

calc = get_cost_calculator() # auto-selects best available
cost = calc.estimate("openai:gpt-4o", input_tokens=1000, output_tokens=500)
```

#### Budget Enforcement

Set budget thresholds to get warnings when costs are high:

```bash
export FIREFLY_GENAI_BUDGET_ALERT_THRESHOLD_USD=5.00
export FIREFLY_GENAI_BUDGET_LIMIT_USD=10.00
```

Pipeline results include aggregated usage automatically:

```python
result = await engine.run(context=ctx)
if result.usage:
    print(f"Pipeline cost: ${result.usage.total_cost_usd:.4f}")
```

### Automatic Integration

When an agent is invoked, the framework automatically creates trace spans, records
metrics, emits events, and tracks usage/cost. You don't need to instrument agent
code manually unless you want additional detail.

### IDP Tie-In: Instrumenting the Pipeline

```python
from fireflyframework_genai.observability import FireflyTracer, FireflyMetrics, traced

tracer = FireflyTracer(service_name="idp-service")
metrics = FireflyMetrics(service_name="idp-service")

@traced(name="idp.process_document")
async def process_document(document_bytes: bytes) -> dict:
    ctx = PipelineContext(inputs=document_bytes)
    result = await idp_pipeline.run(context=ctx)

    metrics.increment("idp.documents_processed")
    if result.success:
        metrics.increment("idp.documents_succeeded")
    else:
        metrics.increment("idp.documents_failed")

    return result.final_output
```

---

## Chapter 12: Explainability

In regulated industries — finance, healthcare, legal — "the model said so" is not an
acceptable answer. Auditors, compliance officers, and customers need to see **why** the
agent classified a document as an invoice, **why** it chose one vendor name over
another, and **what** alternatives it considered. The Explainability module provides
four building blocks: a **trace recorder** that captures every decision, an
**explanation generator** that turns raw records into natural-language narratives, a
tamper-evident **audit trail**, and a **report builder** that compiles everything into
markdown or JSON.

### Trace Recorder

`TraceRecorder` captures every decision during execution:

```python
from fireflyframework_genai.explainability import TraceRecorder

recorder = TraceRecorder()
recorder.record_decision(
    agent_name="extractor",
    action="field_extraction",
    chosen="regex_match",
    alternatives=["llm_extraction", "template_match"],
    rationale="Invoice number matches INV-NNNN pattern; regex is more reliable.",
)
```

Each `DecisionRecord` includes: timestamp, agent name, action, chosen option,
alternatives considered, and rationale.

### Explanation Generator

Transforms raw decision records into natural-language explanations:

```python
from fireflyframework_genai.explainability import ExplanationGenerator

generator = ExplanationGenerator()
explanation = generator.generate(recorder.decisions)
print(explanation)
# "The extractor agent chose regex_match for field_extraction because..."
```

### Audit Trail

A tamper-evident log where each entry includes a hash of the previous entry:

```python
from fireflyframework_genai.explainability import AuditTrail

trail = AuditTrail()
for decision in recorder.decisions:
    trail.append(decision)

# Verify integrity
assert trail.verify()
```

### Report Builder

Compile everything into a structured report:

```python
from fireflyframework_genai.explainability import ReportBuilder

builder = ReportBuilder()
builder.add_decisions(recorder.decisions)
builder.add_explanation(explanation)

# Markdown report (for documentation/review)
markdown = builder.build_markdown()

# JSON report (for programmatic consumption)
json_data = builder.build_json()
```

### IDP Tie-In: Audit Trail for Invoice Extraction

In our IDP pipeline, we record why each field was extracted the way it was:

```python
from fireflyframework_genai.explainability import (
    TraceRecorder, ExplanationGenerator, AuditTrail, ReportBuilder,
)

recorder = TraceRecorder()

# During extraction, record decisions
recorder.record_decision(
    agent_name="field_extractor",
    action="extract_invoice_number",
    chosen="INV-2026-001",
    alternatives=["INV-2026-01", "2026-001"],
    rationale="Matched the INV-NNNN pattern with highest confidence.",
)
recorder.record_decision(
    agent_name="field_extractor",
    action="extract_amount",
    chosen="1234.56",
    alternatives=["1,234.56", "$1234.56"],
    rationale="Normalised currency format to numeric value.",
)

# Generate explanation and audit trail
generator = ExplanationGenerator()
explanation = generator.generate(recorder.decisions)

trail = AuditTrail()
for decision in recorder.decisions:
    trail.append(decision)
assert trail.verify()

# Build the report
report = ReportBuilder()
report.add_decisions(recorder.decisions)
report.add_explanation(explanation)
print(report.build_markdown())
```

---

# Part IV — Experimentation & Deployment

---

## Chapter 13: Experiments

You've built a working extraction agent — but is GPT-4o the right model? Would
Claude give better results? What about lowering the temperature from 0.5 to 0.1?
Answering these questions by hand (run each variant, eyeball the output, repeat) doesn't
scale. The Experiments module gives you a structured way to **define variants**,
**run them against the same inputs**, **collect metrics** (latency, token usage, output
length), and **compare results** — all in a few lines of code.

### Defining an Experiment

```python
from fireflyframework_genai.experiments import Experiment, Variant

experiment = Experiment(
    name="extraction_model_comparison",
    description="Compare GPT-4o vs Claude 3.5 Sonnet on invoice extraction.",
    variants=[
        Variant(name="gpt4o", config={"model": "openai:gpt-4o"}),
        Variant(name="claude", config={"model": "anthropic:claude-3-5-sonnet"}),
    ],
)
```

### Running an Experiment

The `ExperimentRunner` executes each variant against test inputs and collects metrics
(latency, token usage, quality):

```python
from fireflyframework_genai.experiments import ExperimentRunner

runner = ExperimentRunner()
results = await runner.run(
    experiment,
    inputs=[
        "Extract fields from: Invoice #INV-001, Acme Corp, $500, 2026-01-15",
        "Extract fields from: Invoice #INV-002, Globex, $1,200, 2026-02-28",
    ],
)
```

### Tracking Results

Persist results for later analysis and reproducibility:

```python
from fireflyframework_genai.experiments import ExperimentTracker

tracker = ExperimentTracker(storage_dir="./experiment_results")
tracker.save(results)

# Later, reload
loaded = tracker.load("extraction_model_comparison")
```

### Comparing Variants

```python
from fireflyframework_genai.experiments import VariantComparator

comparator = VariantComparator()
metrics = comparator.compare(results)
print(comparator.summary(results))
# "gpt4o: avg_latency=1.2s, avg_output_len=145 | claude: avg_latency=0.9s, ..."
```

### IDP Tie-In: Finding the Best Extraction Model

```python
experiment = Experiment(
    name="idp_extraction_ab_test",
    description="A/B test extraction accuracy for IDP invoices.",
    variants=[
        Variant(name="gpt4o", config={"model": "openai:gpt-4o", "temperature": 0.1}),
        Variant(name="gpt4o_warm", config={"model": "openai:gpt-4o", "temperature": 0.5}),
        Variant(name="claude", config={"model": "anthropic:claude-3-5-sonnet"}),
    ],
)

results = await ExperimentRunner().run(experiment, inputs=test_invoices)
print(VariantComparator().summary(results))
```

---

## Chapter 14: Lab

The Experiments module helps you compare *variants* — but sometimes you just need a
sandbox to poke at an agent interactively, run quick benchmarks, compare side-by-side
outputs, or evaluate accuracy against a labelled dataset. The Lab module is that
sandbox. It provides interactive sessions (REPL-like), benchmarking helpers, model
comparison tables, evaluation datasets, and pluggable scorers — everything you need to
iterate on agent quality before going to production.

### Interactive Sessions

Test an agent conversationally:

```python
from fireflyframework_genai.lab import LabSession

session = LabSession(name="extraction-dev", agent=extractor_agent)
response = await session.interact("Extract fields from: Invoice #INV-001...")
print(response)

# Review history
for entry in session.history:
    print(f"[{entry.timestamp}] {entry.prompt} → {entry.response}")
```

### Benchmarking

Measure agent performance across a set of prompts:

```python
from fireflyframework_genai.lab import Benchmark

bench = Benchmark(inputs=[
    "Extract from: Invoice #INV-001, Acme Corp, $500",
    "Extract from: Invoice #INV-002, Globex, $1,200",
    "Extract from: Invoice #INV-003, Initech, $3,456.78",
])
result = await bench.run(extractor_agent)
print(f"Avg latency: {result.avg_latency_ms:.1f} ms")
print(f"P95 latency: {result.p95_latency_ms:.1f} ms")
```

### Side-by-Side Comparison

Compare multiple agents on the same prompts:

```python
from fireflyframework_genai.lab import ModelComparison

comparison = ModelComparison(prompts=[
    "Extract from: Invoice #INV-001, Acme Corp, $500",
])
entries = await comparison.compare({
    "gpt4o": extractor_gpt4o,
    "claude": extractor_claude,
})
for entry in entries:
    for agent_name, response in entry.responses.items():
        print(f" {agent_name}: {response}")
```

### Datasets

Manage test inputs and expected outputs:

```python
from fireflyframework_genai.lab import EvalDataset, EvalCase

dataset = EvalDataset(cases=[
    EvalCase(
        input="Extract from: Invoice #INV-001, Acme Corp, $500, 2026-01-15",
        expected_output='{"invoice_number": "INV-001", "vendor_name": "Acme Corp", "total_amount": 500.0}',
    ),
])

# Or load from a JSON file
dataset = EvalDataset.from_json("test_data/invoices.json")
```

### Evaluators

Run an agent against a dataset with a pluggable scorer:

```python
from fireflyframework_genai.lab import EvalOrchestrator

# Custom scorer for extraction accuracy
def extraction_scorer(expected: str, actual: str) -> float:
    import json
    try:
        exp = json.loads(expected)
        act = json.loads(actual)
        matching = sum(1 for k in exp if exp.get(k) == act.get(k))
        return matching / len(exp) if exp else 0.0
    except (json.JSONDecodeError, AttributeError):
        return 0.0

orchestrator = EvalOrchestrator(scorer=extraction_scorer)
report = await orchestrator.evaluate(extractor_agent, dataset)
print(f"Accuracy: {report.avg_score:.1%} across {report.total_cases} cases")
```

### IDP Tie-In: Benchmarking Extraction Accuracy

```python
# Load a dataset of real invoices with expected outputs
dataset = EvalDataset.from_json("test_data/invoices.json")

# Benchmark with custom extraction scorer
orchestrator = EvalOrchestrator(scorer=extraction_scorer)
report = await orchestrator.evaluate(extractor_agent, dataset)
print(f"Extraction accuracy: {report.avg_score:.1%}")
```

---

## Chapter 15: Exposure: REST API

Your agents work, your pipeline passes validation, your experiments prove which model is
best. Now you need to put it all behind an HTTP endpoint so other services (or a UI)
can call it. The Exposure REST module gives you a one-liner FastAPI application factory
that auto-generates endpoints for every agent in the `AgentRegistry` — including
streaming via Server-Sent Events, health probes, CORS, and correlation-ID propagation.
You can also add custom endpoints for pipelines.

### Quick Start

```bash
uv add "fireflyframework-genai[rest]"
```

```python
from fireflyframework_genai.exposure.rest import create_genai_app

app = create_genai_app(title="IDP Service", version="1.0.0")
```

```bash
uvicorn myapp:app --reload
```

That's it. The app auto-generates endpoints for every agent in the `AgentRegistry`.

### What You Get Out of the Box

- **GET /agents/** — Lists all registered agents with metadata.
- **POST /agents/{name}/run** — Invokes an agent with a JSON body.
- **GET /agents/{name}/stream** — SSE streaming for real-time output.
- **GET /health** — Liveness probe (`{"status": "healthy"}`).
- **GET /health/ready** — Readiness probe (`{"status": "ready"}`).
- **X-Request-ID** middleware — Injects or propagates request correlation IDs.
- **CORS** middleware — Configurable origins.

### Request and Response

```json
// POST /agents/extractor/run
{
    "prompt": "Extract fields from: Invoice #INV-001, Acme Corp, $500",
    "deps": {}
}
```

```json
// Response
{
    "agent_name": "extractor",
    "output": {"invoice_number": "INV-001", "vendor_name": "Acme Corp", ...},
    "success": true,
    "error": null,
    "metadata": {}
}
```

### SSE Streaming

For long-running agent invocations:

```
GET /agents/extractor/stream?prompt=Extract+fields+from+...

data: {"text": "Processing..."}
data: {"text": "Found invoice number..."}
data: [DONE]
```

### Configuration

```python
app = create_genai_app(
    title="IDP Service",
    version="1.0.0",
    enable_cors=True,
    cors_origins=["https://myapp.example.com"],
)
```

### Multi-Turn Conversations via REST

Pass `conversation_id` in the request body:

```json
{
    "prompt": "What did we discuss earlier?",
    "conversation_id": "abc123"
}
```

### IDP Tie-In: Exposing the Pipeline as a REST API

```python
from fireflyframework_genai.exposure.rest import create_genai_app
from fastapi import UploadFile

app = create_genai_app(title="IDP Service")

# Custom endpoint for the full IDP pipeline
@app.post("/idp/process")
async def process_document(file: UploadFile):
    content = await file.read()
    ctx = PipelineContext(
        inputs=content,
        metadata={"filename": file.filename},
    )
    result = await idp_pipeline.run(context=ctx)
    return result.model_dump() if hasattr(result, "model_dump") else result
```

---

## Chapter 16: Exposure: Message Queues

REST is great for synchronous request/response, but many production systems are
**event-driven**: documents arrive on a Kafka topic, processing results go back on
another topic, and nothing blocks. The Queues module gives you both sides of that
coin — **consumers** that listen for incoming messages and route them to agents, and
**producers** that publish agent results back to the broker.

Three brokers are supported out of the box: Apache Kafka, RabbitMQ, and Redis Pub/Sub.
Each follows the same `QueueConsumer` / `QueueProducer` protocol, so switching
brokers is a one-line change.

```mermaid
flowchart LR
    subgraph Broker
        REQ["Requests Topic"]
        RES["Results Topic"]
    end

    subgraph fireflyframework-genai
        CONS["Consumer<br/><small>KafkaAgentConsumer<br/>RabbitMQAgentConsumer<br/>RedisAgentConsumer</small>"]
        ROUTER["QueueRouter<br/><small>pattern-based routing</small>"]
        REG["AgentRegistry"]
        AGT["FireflyAgent"]
        PROD["Producer<br/><small>KafkaAgentProducer<br/>RabbitMQAgentProducer<br/>RedisAgentProducer</small>"]
    end

    REQ --> CONS
    CONS --> ROUTER
    ROUTER --> REG
    REG --> AGT
    AGT --> PROD
    PROD --> RES
```

### Quick Start

```bash
# Install the backend you need
uv add "fireflyframework-genai[kafka]"
uv add "fireflyframework-genai[rabbitmq]"
uv add "fireflyframework-genai[redis]"
```

### Consumers

Consumers listen on a topic/queue/channel and route each incoming message to a
registered agent. They run continuously — think of them as your agent's "inbox".

#### Kafka Consumer

```python
from fireflyframework_genai.exposure.queues.kafka import KafkaAgentConsumer

# This consumer reads from the "idp-incoming-documents" topic.
# Every message body is passed to the "document_classifier" agent's run() method.
consumer = KafkaAgentConsumer(
    agent_name="document_classifier",
    topic="idp-incoming-documents",
    bootstrap_servers="localhost:9092",
    group_id="idp-workers", # Kafka consumer group for load balancing
)
await consumer.start() # Blocks and processes messages until stopped
```

#### RabbitMQ Consumer

```python
from fireflyframework_genai.exposure.queues.rabbitmq import RabbitMQAgentConsumer

consumer = RabbitMQAgentConsumer(
    agent_name="document_classifier",
    queue_name="idp-incoming-documents",
    url="amqp://guest:guest@localhost/",
)
await consumer.start()
```

#### Redis Consumer

```python
from fireflyframework_genai.exposure.queues.redis import RedisAgentConsumer

consumer = RedisAgentConsumer(
    agent_name="document_classifier",
    channel="idp-incoming-documents",
    url="redis://localhost:6379",
)
await consumer.start()
```

### Producers

Producers are the other half — they publish messages (typically agent results) back
to the broker. Each producer satisfies the `QueueProducer` protocol.

#### Kafka Producer

```python
from fireflyframework_genai.exposure.queues.kafka import KafkaAgentProducer
from fireflyframework_genai.exposure.queues import QueueMessage

# Create a producer that publishes to the "idp-results" topic.
producer = KafkaAgentProducer(
    topic="idp-results",
    bootstrap_servers="localhost:9092",
)

# Publish a result back to the broker.
await producer.publish(QueueMessage(
    body='{"invoice_number": "INV-001", "status": "extracted"}',
    headers={"agent": "field_extractor", "tenant": "acme-corp"},
))

# When you're done, clean up.
await producer.stop()
```

#### RabbitMQ Producer

```python
from fireflyframework_genai.exposure.queues.rabbitmq import RabbitMQAgentProducer

producer = RabbitMQAgentProducer(
    queue_name="idp-results",
    url="amqp://guest:guest@localhost/",
)
await producer.publish(QueueMessage(body='{"status": "done"}'))
await producer.stop()
```

#### Redis Producer

```python
from fireflyframework_genai.exposure.queues.redis import RedisAgentProducer

producer = RedisAgentProducer(
    channel="idp-results",
    url="redis://localhost:6379",
)
await producer.publish(QueueMessage(body='{"status": "done"}'))
await producer.stop()
```

#### Consumer + Producer Pattern

The most common pattern is a **consumer that processes messages and publishes results**.
This turns your agent into a microservice that reads from one topic and writes to another:

```python
from fireflyframework_genai.exposure.queues.kafka import KafkaAgentConsumer, KafkaAgentProducer
from fireflyframework_genai.exposure.queues import QueueMessage
from fireflyframework_genai.agents.registry import agent_registry

# Set up both sides
consumer = KafkaAgentConsumer(
    agent_name="field_extractor",
    topic="idp-extract-requests",
    bootstrap_servers="kafka:9092",
)
producer = KafkaAgentProducer(
    topic="idp-extract-results",
    bootstrap_servers="kafka:9092",
)

# Process: consume → run agent → publish result
async def process_and_publish():
    agent = agent_registry.get("field_extractor")
    # In practice, you'd integrate this into the consumer's message loop.
    # Here we show the conceptual flow:
    result = await agent.run("Extract fields from: Invoice #INV-001, Acme, $500")
    await producer.publish(QueueMessage(
        body=str(result.output),
        headers={"agent": "field_extractor"},
    ))
```

### Queue Messages

All consumers and producers work with `QueueMessage`:

```python
from fireflyframework_genai.exposure.queues import QueueMessage

message = QueueMessage(
    body="Process this invoice",
    headers={"tenant": "acme-corp", "priority": "high"},
    routing_key="invoice.process",
    reply_to="idp-responses",
)
```

### Queue Router

Route messages to different agents based on routing-key patterns:

```python
from fireflyframework_genai.exposure.queues import QueueRouter

router = QueueRouter(default_agent="fallback")
router.add_route(r"invoice\..*", "invoice_processor")
router.add_route(r"receipt\..*", "receipt_processor")
router.add_route(r"contract\..*", "contract_processor")

# Incoming message with routing_key="invoice.classify"
# → routed to "invoice_processor" agent
```

### Custom Consumers

For unsupported brokers, extend `BaseQueueConsumer`:

```python
from fireflyframework_genai.exposure.queues.base import BaseQueueConsumer

class MyBrokerConsumer(BaseQueueConsumer):
    async def start(self) -> None:
        # Connect and begin consuming
        ...

    async def stop(self) -> None:
        # Disconnect gracefully
        ...
```

The base class provides `_process_message(message)` which routes to the configured
agent automatically.

### IDP Tie-In: Processing Documents from Kafka

In our IDP system, documents arrive on a Kafka topic. The consumer classifies them
and routes to specialised extractors. Results go back on a results topic for
downstream systems to pick up:

```python
from fireflyframework_genai.exposure.queues.kafka import KafkaAgentConsumer, KafkaAgentProducer
from fireflyframework_genai.exposure.queues import QueueRouter, QueueMessage

# Route different document types to specialised extraction agents.
# Messages with routing_key "invoice.*" go to the invoice extractor, etc.
router = QueueRouter(default_agent="document_classifier")
router.add_route(r"invoice\..*", "invoice_extractor")
router.add_route(r"receipt\..*", "receipt_extractor")

# Consumer: reads raw documents from Kafka
consumer = KafkaAgentConsumer(
    agent_name="document_classifier",
    topic="idp-documents",
    bootstrap_servers="kafka:9092",
    group_id="idp-consumers",
)

# Producer: publishes extraction results back to Kafka
producer = KafkaAgentProducer(
    topic="idp-results",
    bootstrap_servers="kafka:9092",
)

# Start both — the consumer runs in a loop, the producer is ready to publish.
await consumer.start()
```

---

# Part V — Advanced

---

## Chapter 17: Template Agents

By now you've written several agents from scratch — classifier, extractor, OCR. Each
time you had to think about the system prompt, output type, and registration. But many
agent patterns are universal: *summarise text*, *classify into categories*, *extract
structured data*, *hold a conversation*, *route to sub-agents*. The framework ships
five **template agents** as factory functions that encode best practices for each
pattern. You provide the domain-specific bits (categories, schemas, personality), and
the factory handles prompt engineering, output typing, and registry registration.

### Summarizer

```python
from fireflyframework_genai.agents.templates import create_summarizer_agent

agent = create_summarizer_agent(
    max_length="short", # concise | short | medium | detailed
    style="technical", # professional | casual | technical | academic
    output_format="bullets", # paragraph | bullets | numbered
    model="openai:gpt-4o",
)
result = await agent.run("Long invoice description text here...")
```

### Classifier

Returns a structured `ClassificationResult` with category, confidence, and reasoning:

```python
from fireflyframework_genai.agents.templates import create_classifier_agent

agent = create_classifier_agent(
    categories=["invoice", "receipt", "contract", "form"],
    descriptions={
        "invoice": "Bills requesting payment for goods or services",
        "receipt": "Proof of payment or purchase",
        "contract": "Legal agreements between parties",
        "form": "Fillable forms and applications",
    },
    model="openai:gpt-4o",
)
result = await agent.run("Invoice from Acme Corp, Amount Due: $1,234.56")
# result.output → ClassificationResult(category="invoice", confidence=0.95, ...)
```

### Extractor

Extracts structured data into a user-provided Pydantic model:

```python
from pydantic import BaseModel
from fireflyframework_genai.agents.templates import create_extractor_agent

class Invoice(BaseModel):
    vendor: str
    amount: float
    date: str
    invoice_number: str | None = None

agent = create_extractor_agent(
    Invoice,
    field_descriptions={
        "vendor": "The company that issued the invoice",
        "amount": "Total monetary amount",
    },
    model="openai:gpt-4o",
)
result = await agent.run("Invoice from Acme Corp, $1,234.56, 2026-01-15")
# result.output → Invoice(vendor="Acme Corp", amount=1234.56, ...)
```

### Conversational Agent

Memory-enabled multi-turn assistant:

```python
from fireflyframework_genai.agents.templates import create_conversational_agent
from fireflyframework_genai.memory import MemoryManager

memory = MemoryManager(max_conversation_tokens=32_000)
agent = create_conversational_agent(
    personality="friendly and concise",
    domain="accounts payable",
    memory=memory,
    model="openai:gpt-4o",
)

cid = memory.new_conversation()
result = await agent.run("I need help with invoice INV-001.", conversation_id=cid)
result = await agent.run("What's the payment status?", conversation_id=cid)
```

### Router Agent

Intent-based routing to child agents:

```python
from fireflyframework_genai.agents.templates import create_router_agent

agent = create_router_agent(
    agent_map={
        "invoice_processor": "Handles invoice extraction and validation",
        "receipt_processor": "Handles receipt scanning and categorisation",
        "support": "General questions about the IDP system",
    },
    fallback_agent="support",
    model="openai:gpt-4o",
)
result = await agent.run("Process this invoice from Acme Corp")
# result.output → RoutingDecision(target_agent="invoice_processor", confidence=0.92, ...)
```

### Common Parameters

All template factories accept:

- **name** — Agent name for the registry (sensible defaults provided).
- **model** — LLM model string; falls back to framework default.
- **extra_instructions** — Text appended to the system prompt.
- **tools** — Additional tools to attach.
- **auto_register** — Set to `False` to skip registry registration.

### IDP Tie-In: Using Templates Instead of Hand-Rolled Agents

Replace our manual agents with templates for cleaner code:

```python
from fireflyframework_genai.agents.templates import (
    create_classifier_agent,
    create_extractor_agent,
)

# Phase 1: Use the built-in classifier template
classifier_agent = create_classifier_agent(
    categories=["invoice", "receipt", "contract", "form"],
    name="document_classifier",
    model="openai:gpt-4o",
)

# Phase 3: Use the built-in extractor template
extractor_agent = create_extractor_agent(
    InvoiceExtraction,
    field_descriptions={
        "invoice_number": "Format: INV-NNNN",
        "vendor_name": "Company that issued the invoice",
        "total_amount": "Total amount due",
        "due_date": "Payment due date in ISO format",
    },
    name="field_extractor",
    model="openai:gpt-4o",
)
```

---

## Chapter 18: Multi-Agent Delegation

Not every document is an invoice. Your IDP system might receive receipts, contracts,
and forms — each requiring a specialised agent with different prompts, tools, and
validation rules. Instead of building one mega-agent that tries to do everything,
you build **specialised agents** and let a **delegation router** decide which one
handles each request. The router picks an agent based on a **strategy** (round-robin
for load balancing, capability-based for expertise matching), delegates the work, and
optionally **forks memory** so the sub-agent gets its own working-memory scope.

### Delegation Architecture

```mermaid
graph LR
    REQ["Incoming Request"] --> ROUTER["DelegationRouter"]

    subgraph Strategy
        RR["RoundRobinStrategy\n(load balance)"]
        CAP["CapabilityStrategy\n(match by tag)"]
    end

    ROUTER --> RR
    ROUTER --> CAP

    subgraph Agent Pool
        A1["invoice_extractor"]
        A2["receipt_extractor"]
        A3["contract_extractor"]
    end

    RR --> A1 & A2 & A3
    CAP -->|tag match| A1

    subgraph Memory
        MEM["MemoryManager"]
        FORK["fork()"]
        CHILD["Child Scope"]
    end

    ROUTER -.->|auto fork| FORK
    FORK --> CHILD
    CHILD --> A1
```

### Delegation Router

```python
from fireflyframework_genai.agents.delegation import DelegationRouter, RoundRobinStrategy

router = DelegationRouter(
    agents=[agent_a, agent_b, agent_c],
    strategy=RoundRobinStrategy(),
)
result = await router.route("Process this document.")
```

### Round Robin Strategy

Distributes requests evenly across a pool of agents. Useful for load balancing
when all agents have equivalent capabilities:

```python
from fireflyframework_genai.agents.delegation import RoundRobinStrategy

strategy = RoundRobinStrategy()
router = DelegationRouter([agent_1, agent_2, agent_3], strategy)
# Request 1 → agent_1, Request 2 → agent_2, Request 3 → agent_3, Request 4 → agent_1...
```

### Capability-Based Strategy

Selects the first agent whose tags include a required capability:

```python
from fireflyframework_genai.agents.delegation import CapabilityStrategy

strategy = CapabilityStrategy(required_tag="invoice_extraction")
router = DelegationRouter([invoice_agent, receipt_agent], strategy)
result = await router.route("Extract invoice data.")
# → Routed to invoice_agent (which has the "invoice_extraction" tag)
```

### Memory with Delegation

When a `MemoryManager` is attached, delegated agents receive a forked memory scope:

```python
from fireflyframework_genai.memory import MemoryManager

memory = MemoryManager(working_scope_id="main")
router = DelegationRouter([agent_a, agent_b], RoundRobinStrategy(), memory=memory)
result = await router.route("Process this.")
# The delegated agent gets its own working memory scope
```

### IDP Tie-In: Routing Documents to Specialised Agents

```python
from fireflyframework_genai.agents.delegation import DelegationRouter, CapabilityStrategy

# Specialised agents for different document types
invoice_agent = create_extractor_agent(InvoiceSchema, name="invoice_extractor")
receipt_agent = create_extractor_agent(ReceiptSchema, name="receipt_extractor")
contract_agent = create_extractor_agent(ContractSchema, name="contract_extractor")

# Route based on capability
strategy = CapabilityStrategy(required_tag="invoice")
router = DelegationRouter(
    agents=[invoice_agent, receipt_agent, contract_agent],
    strategy=strategy,
)
```

---

## Chapter 19: Plugin System

As your application grows, you'll want to share agents, tools, and reasoning patterns
across projects — or let third-party teams contribute their own. The Plugin module
uses Python's standard **entry-point** mechanism so that any installed package can
register components that are discovered and loaded automatically at startup. No manual
imports, no central configuration file — just install the package and go.

### Discovering Plugins

```python
from fireflyframework_genai.plugin import PluginDiscovery

result = PluginDiscovery.discover_all()
print(f"Loaded {len(result.successful)} plugins, {len(result.failed)} failed")
```

### Creating a Plugin

In your package's `pyproject.toml`, declare entry points under the framework's groups:

```toml
[project.entry-points."fireflyframework_genai.agents"]
my_agent = "my_package.agents:MySpecialAgent"

[project.entry-points."fireflyframework_genai.tools"]
my_tool = "my_package.tools:MyCustomTool"

[project.entry-points."fireflyframework_genai.reasoning_patterns"]
my_pattern = "my_package.reasoning:MyCustomPattern"
```

The three entry-point groups are:

- `fireflyframework_genai.agents` — Custom agents.
- `fireflyframework_genai.tools` — Custom tools.
- `fireflyframework_genai.reasoning_patterns` — Custom reasoning patterns.

On discovery, the framework loads each entry point and registers it in the appropriate
registry.

### Configuration

```python
# Enable auto-discovery on startup (default: True)
# FIREFLY_GENAI_PLUGIN_AUTO_DISCOVER=true
```

### IDP Tie-In: Packaging IDP as a Plugin

You can package the entire IDP pipeline as a plugin that self-registers when installed:

```toml
# In idp_plugin/pyproject.toml
[project.entry-points."fireflyframework_genai.agents"]
document_classifier = "idp_plugin.agents:classifier_agent"
field_extractor = "idp_plugin.agents:extractor_agent"
ocr_agent = "idp_plugin.agents:ocr_agent"
```

After `uv add idp-plugin`, calling `PluginDiscovery.discover_all()` registers all three
agents automatically.

---

## Chapter 20: Putting It All Together

You've learned every module in fireflyframework-genai, each in isolation. Now it's time
to see how they all fit together in a single, production-grade application. The diagram
below shows the full system architecture — every layer, every connection:

### Full System Architecture

```mermaid
graph TB
    subgraph "Exposure Layer"
        REST["REST API\n(FastAPI + SSE)"]
        KAFKA["Kafka Consumer"]
        RABBIT["RabbitMQ Consumer"]
        REDIS["Redis Consumer"]
    end

    subgraph "Orchestration Layer"
        PIPE["Pipeline Engine\n(DAG scheduler)"]
        DELEG["Delegation Router"]
    end

    subgraph "Intelligence Layer"
        REASON["Reasoning Patterns\n(ReAct, CoT, P&E, ...)"]
        VALID["Validation & QoS"]
        REVIEW["OutputReviewer"]
    end

    subgraph "Agent Layer"
        FA["FireflyAgent"]
        REG["AgentRegistry"]
        TPL["Template Agents"]
    end

    subgraph "Agent Support"
        TOOLS["Tools + ToolKit\n(guards, builtins, registry)"]
        PROMPTS["Prompts\n(Jinja2, versioned, composed)"]
        MEM["Memory\n(conversation + working)"]
        CONTENT["Content Processing\n(chunk, compress, batch)"]
    end

    subgraph "Ops Layer"
        OBS["Observability\n(traces, metrics, events)"]
        EXPL["Explainability\n(audit trail, reports)"]
        EXP["Experiments\n(A/B testing)"]
        LAB["Lab\n(benchmarks, eval)"]
    end

    subgraph "Foundation"
        PAI["Pydantic AI\n(model calls, streaming)"]
        CFG["FireflyGenAIConfig\n(env-driven settings)"]
        PLUG["Plugin System\n(entry-point discovery)"]
    end

    REST & KAFKA & RABBIT & REDIS --> PIPE & DELEG
    PIPE --> FA
    DELEG --> FA
    FA --> REASON
    REASON --> FA
    FA --> VALID
    VALID --> REVIEW
    REVIEW --> FA
    FA --> PAI
    FA --> TOOLS
    FA --> PROMPTS
    FA --> MEM
    FA --> CONTENT
    FA --> REG
    TPL --> FA
    OBS -.-> FA & PIPE & REASON
    EXPL -.-> FA
    EXP -.-> FA
    LAB -.-> FA
    PLUG -.-> REG & TOOLS
    CFG -.-> FA & PIPE & MEM & OBS
```

Let's assemble the complete IDP pipeline using everything we've learned. This is the
full, production-ready implementation.

### Project Structure

```
idp-service/
├── pyproject.toml
├── .env
├── prompts/
│ ├── classification.jinja2
│ └── extraction.jinja2
├── src/
│ └── idp_service/
│ ├── __init__.py
│ ├── agents.py # Agent definitions
│ ├── tools.py # Tool definitions
│ ├── pipeline.py # Pipeline wiring
│ ├── validation.py # Validation rules
│ ├── app.py # REST application
│ └── consumers.py # Queue consumers
└── tests/
    └── test_pipeline.py
```

### Configuration (.env)

```bash
FIREFLY_GENAI_DEFAULT_MODEL=openai:gpt-4o
FIREFLY_GENAI_DEFAULT_TEMPERATURE=0.1
FIREFLY_GENAI_MAX_RETRIES=3
FIREFLY_GENAI_OBSERVABILITY_ENABLED=true
FIREFLY_GENAI_OTLP_ENDPOINT=http://localhost:4317
FIREFLY_GENAI_MEMORY_BACKEND=file
FIREFLY_GENAI_MEMORY_FILE_DIR=.firefly_memory
FIREFLY_GENAI_DEFAULT_CHUNK_SIZE=4000
FIREFLY_GENAI_VALIDATION_ENABLED=true
```

### Agents (agents.py)

```python
from pydantic import BaseModel, Field
from fireflyframework_genai.agents.templates import (
    create_classifier_agent,
    create_extractor_agent,
    create_summarizer_agent,
)
from fireflyframework_genai.agents import FireflyAgent

# Output schema for extraction
class InvoiceData(BaseModel):
    invoice_number: str
    vendor_name: str
    total_amount: float = Field(ge=0)
    due_date: str
    line_items: list[dict] = []

# Phase 1: Document classifier
classifier_agent = create_classifier_agent(
    categories=["invoice", "receipt", "contract", "form", "other"],
    name="document_classifier",
    model="openai:gpt-4o",
)

# Phase 2: OCR/digitisation agent
ocr_agent = FireflyAgent(
    name="ocr_agent",
    model="openai:gpt-4o",
    instructions="Extract all text from this document. Preserve layout and structure.",
)

# Phase 2.5: Summariser for compression
summary_agent = create_summarizer_agent(
    name="doc_summariser",
    max_length="medium",
    style="technical",
    model="openai:gpt-4o",
)

# Phase 3: Field extractor — with tools from tools.py attached
from .tools import extraction_kit

extractor_agent = create_extractor_agent(
    InvoiceData,
    field_descriptions={
        "invoice_number": "Format: INV-NNNN or similar",
        "vendor_name": "Company that issued the invoice",
        "total_amount": "Total monetary amount due",
        "due_date": "Payment due date (ISO 8601)",
        "line_items": "List of line items with description, quantity, unit_price",
    },
    name="field_extractor",
    model="openai:gpt-4o",
    tools=extraction_kit.as_pydantic_tools(), # Bridge Firefly tools → Pydantic AI
)
```

### Tools (tools.py)

Tools live in their own module. Each `@firefly_tool` call creates a `BaseTool`,
registers it in the global `ToolRegistry`, and returns the instance. The `ToolKit`
bundles them for agent injection via `as_pydantic_tools()`:

```python
from fireflyframework_genai.tools import firefly_tool, guarded, retryable, ToolKit
from fireflyframework_genai.tools.guards import RateLimitGuard, ValidationGuard
from fireflyframework_genai.tools.builtins import CalculatorTool

# OCR tool — rate-limited because the upstream API is metered
@retryable(max_retries=2, backoff=1.0)
@guarded(RateLimitGuard(max_calls=100, period_seconds=60))
@firefly_tool(name="ocr_extract", description="Extract text from a document image via OCR")
async def ocr_extract(image_data: str) -> str:
    """In production, call an OCR service like AWS Textract or Google Vision."""
    return "Invoice #INV-2026-001\nVendor: Acme Corp\nAmount: $1,234.56\nDate: 2026-01-15"

# Vendor lookup — validates that vendor_name is present
@guarded(ValidationGuard(required_keys=["vendor_name"]))
@firefly_tool(name="vendor_lookup", description="Look up vendor details from the ERP system")
async def vendor_lookup(vendor_name: str) -> str:
    vendors = {
        "Acme Corp": '{"id": "V-001", "tax_id": "US-12345", "payment_terms": "NET30"}',
        "Globex": '{"id": "V-002", "tax_id": "US-67890", "payment_terms": "NET60"}',
    }
    return vendors.get(vendor_name, '{"error": "Vendor not found"}')

# Calculator — a built-in tool, no decorator needed
calculator = CalculatorTool()

# Bundle the tools the extractor agent needs.
# as_pydantic_tools() bridges them into the Pydantic AI tool format.
extraction_kit = ToolKit(
    "extraction-tools",
    [ocr_extract, vendor_lookup, calculator],
    description="Tools available during invoice field extraction",
)
```

### Validation (validation.py)

```python
from fireflyframework_genai.validation.rules import (
    OutputValidator, RegexRule, FormatRule, RangeRule,
)
from fireflyframework_genai.validation.qos import (
    QoSGuard, ConfidenceScorer, ConsistencyChecker, GroundingChecker,
)
from fireflyframework_genai.validation import OutputReviewer
from .agents import InvoiceData, extractor_agent

invoice_validator = OutputValidator({
    "invoice_number": [RegexRule("invoice_number", r"^INV-\d{4,10}$")],
    "vendor_name": [RegexRule("vendor_name", r".{2,}")],
    "total_amount": [RangeRule("total_amount", min_value=0.01, max_value=10_000_000)],
    "due_date": [FormatRule("due_date", "iso_date")],
})

reviewer = OutputReviewer(
    output_type=InvoiceData,
    validator=invoice_validator,
    max_retries=3,
)

qos_guard = QoSGuard(
    confidence_scorer=ConfidenceScorer(extractor_agent),
    consistency_checker=ConsistencyChecker(extractor_agent, num_runs=2),
    grounding_checker=GroundingChecker(),
    min_confidence=0.8,
    min_consistency=0.6,
    min_grounding=0.8,
)
```

### Pipeline (pipeline.py)

```python
from fireflyframework_genai.pipeline.builder import PipelineBuilder
from fireflyframework_genai.pipeline.steps import AgentStep, ReasoningStep, CallableStep
from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.reasoning import PlanAndExecutePattern, ReflexionPattern
from fireflyframework_genai.content.chunking import TextChunker, BatchProcessor
from fireflyframework_genai.content.compression import ContextCompressor, MapReduceStrategy
from fireflyframework_genai.memory import MemoryManager
from fireflyframework_genai.observability import traced
from .agents import classifier_agent, ocr_agent, summary_agent, extractor_agent
from .validation import invoice_validator, reviewer

async def validate_step(context, inputs):
    extracted = inputs.get("input", {})
    report = invoice_validator.validate(extracted)
    context.metadata["validation_report"] = report
    if not report.valid:
        # Self-correct with Reflexion
        reflexion = ReflexionPattern(max_steps=2)
        corrected = await reflexion.execute(
            extractor_agent,
            f"Fix these errors: {report.errors}. Original data: {extracted}",
        )
        return {"extracted": corrected.output, "valid": True, "errors": []}
    return {"extracted": extracted, "valid": True, "errors": []}

async def assemble_step(context, inputs):
    data = inputs.get("input", {})
    return {
        "document_type": context.metadata.get("doc_type", "unknown"),
        "language": context.metadata.get("language", "unknown"),
        "extracted_fields": data.get("extracted", {}),
        "validation_passed": data.get("valid", False),
    }

idp_pipeline = (
    PipelineBuilder("idp-pipeline")
    .add_node("classify", AgentStep(classifier_agent))
    .add_node("digitise", AgentStep(ocr_agent), retry_max=2, timeout_seconds=60)
    .add_node(
        "extract",
        ReasoningStep(PlanAndExecutePattern(max_steps=15, allow_replan=True), extractor_agent),
    )
    .add_node("validate", CallableStep(validate_step))
    .add_node("assemble", CallableStep(assemble_step))
    .chain("classify", "digitise", "extract", "validate", "assemble")
    .build()
)

@traced(name="idp.process")
async def process_document(document_bytes: bytes, metadata: dict | None = None) -> dict:
    memory = MemoryManager(working_scope_id="idp-session")
    ctx = PipelineContext(
        inputs=document_bytes,
        metadata=metadata or {},
        memory=memory,
    )
    result = await idp_pipeline.run(context=ctx)
    return result.final_output if result.success else {"error": result.failed_nodes}
```

### REST Application (app.py)

```python
from fireflyframework_genai.exposure.rest import create_genai_app
from fireflyframework_genai.observability import configure_exporters
from fastapi import UploadFile
from .pipeline import process_document

# Configure observability
configure_exporters(otlp_endpoint="http://localhost:4317", console=True)

# Create the app
app = create_genai_app(title="IDP Service", version="1.0.0")

@app.post("/idp/process")
async def handle_document(file: UploadFile):
    content = await file.read()
    result = await process_document(
        content,
        metadata={"filename": file.filename, "source": "rest-api"},
    )
    return result
```

### Queue Consumers (consumers.py)

```python
from fireflyframework_genai.exposure.queues.kafka import KafkaAgentConsumer
from fireflyframework_genai.exposure.queues import QueueRouter

# Route different document types to specialised processing
router = QueueRouter(default_agent="document_classifier")
router.add_route(r"invoice\..*", "field_extractor")
router.add_route(r"receipt\..*", "receipt_processor")

# Main Kafka consumer
consumer = KafkaAgentConsumer(
    agent_name="document_classifier",
    topic="idp-documents",
    bootstrap_servers="kafka:9092",
    group_id="idp-workers",
)
```

### Running the Service

```bash
# Start the REST API
uvicorn idp_service.app:app --host 0.0.0.0 --port 8000

# Or start the Kafka consumer
python -m idp_service.consumers
```

### Production Checklist

Before deploying to production, verify:

- [ ] **Configuration** — All `FIREFLY_GENAI_*` environment variables are set.
- [ ] **Model access** — API keys for your LLM provider are configured.
- [ ] **Observability** — OTLP endpoint is reachable; traces are flowing.
- [ ] **Memory persistence** — `memory_backend` is set to `"file"` (or a custom backend)
  for durability.
- [ ] **Validation** — `OutputValidator` rules match your business requirements.
- [ ] **QoS thresholds** — `min_confidence` and `num_runs` (ConsistencyChecker) are tuned
  for your use case.
- [ ] **Retry limits** — Pipeline nodes have appropriate `retry_max` and
  `timeout_seconds`.
- [ ] **CORS** — REST API `cors_origins` is restricted to known domains.
- [ ] **Health checks** — Kubernetes probes point to `/health` and `/health/ready`.
- [ ] **Experiments** — You've A/B tested your prompt and model variants.
- [ ] **Audit trail** — Explainability is enabled for regulated workloads.

---

## Next Steps

Congratulations — you now know every module in fireflyframework-genai. Here are some
paths to explore further:

- **Dive deeper** — Each chapter links to a detailed module guide in `docs/`.
- **Read the source** — The framework is fully typed and well-documented in code.
- **Run the tests** — `uv run pytest` runs 367+ tests that exercise every module.
- **Build your own** — Extend `AbstractReasoningPattern`, implement `MemoryStore`,
  create custom tools, or write a plugin.

### Module Reference

- [Architecture](architecture.md)
- [Agents](agents.md)
- [Template Agents](templates.md)
- [Tools](tools.md)
- [Prompts](prompts.md)
- [Reasoning Patterns](reasoning.md)
- [Content Processing](content.md)
- [Memory](memory.md)
- [Validation](validation.md)
- [Pipeline](pipeline.md)
- [Observability](observability.md)
- [Explainability](explainability.md)
- [Experiments](experiments.md)
- [Lab](lab.md)
- [Exposure REST](exposure-rest.md)
- [Exposure Queues](exposure-queues.md)
- [Use Case: IDP](use-case-idp.md)
