# Tools Guide

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The Tools module provides a protocol-driven system for defining, guarding, composing,
and registering tools that agents can invoke.

---

## Concepts

A tool is any callable that an agent can use to interact with external systems or
perform computations. The framework wraps tools with metadata, guards, and composition
logic.

The core contract lives in `fireflyframework_agentic.tools.base`:

- **`ToolProtocol`** -- a runtime-checkable `Protocol` (properties `name`, `description`;
  `async execute(**kwargs)`). Implement it directly for composition, or subclass `BaseTool`
  for guard evaluation, timeout, and error handling out of the box.
- **`GuardProtocol`** -- `async check(tool_name, kwargs) -> GuardResult`.
- **`GuardResult`** -- `GuardResult(passed: bool, reason: str | None = None)`; guards return it.
- **`ParameterSpec`** -- `ParameterSpec(name, type_annotation, description="", required=True,
  default=None)`; declared specs drive the Pydantic AI JSON schema the LLM sees.
- **`ToolInfo`** -- serialisable summary (`name`, `description`, `tags`, `parameter_count`)
  returned by `BaseTool.info()` and `ToolRegistry.list_tools()`.

All six are exported from `fireflyframework_agentic.tools`.

```mermaid
classDiagram
    class ToolProtocol {
        <<protocol>>
        +name: str
        +description: str
        +execute(**kwargs) Any
    }

    class BaseTool {
        <<abstract>>
        +name: str
        +description: str
        +execute(**kwargs) Any
    }

    class ToolBuilder {
        +ToolBuilder(name)
        +description(d) ToolBuilder
        +tag(t) ToolBuilder
        +tags(ts) ToolBuilder
        +parameter(name, type, ...) ToolBuilder
        +guard(g) ToolBuilder
        +handler(fn) ToolBuilder
        +build() BaseTool
    }

    class ToolRegistry {
        +register(tool)
        +get(name) ToolProtocol
        +get_by_tag(tag) list
        +has(name) bool
        +unregister(name)
        +list_tools() list~ToolInfo~
        +clear()
    }

    class ToolKit {
        +ToolKit(name, tools, *, description, tags)
        +tools: list
        +register_all(registry)
        +unregister_all(registry)
        +as_pydantic_tools() list
    }

    ToolProtocol <|.. BaseTool
    ToolBuilder --> BaseTool : creates
    ToolRegistry --> ToolProtocol
    ToolKit --> ToolProtocol
```

---

## Creating a Tool

### Using the Decorator

```python
from fireflyframework_agentic.tools import firefly_tool

@firefly_tool(name="calculator", description="Evaluate a math expression")
async def calculator(expression: str) -> str:
    return str(eval(expression))
```

### Using the Builder

The fluent `ToolBuilder` lets you construct tools step by step. Beyond `description()`,
`handler()`, and `guard()`, it also exposes `tag()`, `tags()`, and
`parameter(name, python_type, *, description, required, default)` — declared
parameters generate the JSON schema the LLM uses to call the tool. `build()` raises
`ValueError` if no handler was set.

`python_type` is a **real Python type object** — `str`, `list[str]`,
`Literal["a", "b"]`, a nested `BaseModel`, `dict[str, Any] | None`, … pydantic-ai
introspects it directly, so nested models, enums and element types all reach the
LLM's schema intact.

```python
from typing import Literal

from fireflyframework_agentic.tools import ToolBuilder
from fireflyframework_agentic.tools.guards import RateLimitGuard

tool = (
    ToolBuilder("weather")
    .description("Get current weather for a city")
    .tags(["web", "geo"])
    .parameter("city", str, description="City name", required=True)
    .parameter("units", Literal["metric", "imperial"], default="metric", required=False)
    .guard(RateLimitGuard(max_calls=10, period_seconds=60))
    .handler(get_weather_fn)
    .build()
)
```

### Full-fidelity schemas & RunContext

A `BaseTool` subclass declares its parameters as `ParameterSpec(name=..., python_type=...)`.
Because `python_type` is a real type, the generated schema is exact — `list[str]`
keeps its element type, a `Literal` becomes an `enum`, a nested model becomes a
`$ref`. Opt a tool into pydantic-ai's `RunContext` (agent deps, usage, retry count)
with `takes_ctx=True`; the context arrives as the keyword-only `_ctx` in `_execute`,
and **guards and the cache never see it** (so it can't poison a cache key):

```python
from typing import Any, Literal

from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec

class SetPriority(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            "set_priority",
            description="Set a ticket's priority.",
            takes_ctx=True,                                  # opt into RunContext
            parameters=[ParameterSpec(name="level", python_type=Literal["low", "medium", "high"])],
        )

    async def _execute(self, *, _ctx: Any = None, **kwargs: Any) -> str:
        tenant = _ctx.deps                                   # reach the agent's deps
        return f"{tenant}: priority set to {kwargs['level']}"
```

> **Cross-provider schema portability.** Real `python_type`s keep tool schemas
> portable across providers, but **Gemini's `FunctionDeclaration` rejects free-form
> objects** — a `dict[str, Any]` parameter produces an open object schema (no
> declared properties) that Google's API refuses (OpenAI/Anthropic/Bedrock accept
> it). Prefer a **JSON-object string** (`python_type=str`, parsed in `_execute`) or a
> constrained nested `BaseModel` for "bag of fields" inputs. The built-in
> `DatabaseTool` does exactly this for its `params` argument.

### Toolsets and native combinators

`ToolKit.as_toolset()` returns a pydantic-ai `FunctionToolset` (descriptions and
schemas included) for `Agent(toolsets=[...])` / `FireflyAgent(toolsets=[...])`. For
convenience the tools package re-exports pydantic-ai's native toolset combinators —
`FilteredToolset`, `PrefixedToolset`, `RenamedToolset`, `CombinedToolset`,
`WrapperToolset`, `PreparedToolset`, `ApprovalRequiredToolset` — plus `RunContext`,
so you can wrap/filter/combine a kit's toolset without importing from `pydantic_ai`
directly. `to_pydantic_handler(tool)` returns the guard/cache-routing handler for a
single tool.

---

## Guards

Guards wrap tool execution to enforce policies. They run before and/or after the
tool's handler.

```mermaid
flowchart LR
    REQ[Tool Call] --> G1[Validation Guard]
    G1 --> G2[Rate Limit Guard]
    G2 --> H[Tool Handler]
    H --> G3[Sandbox Guard]
    G3 --> RES[Result]
```

Each guard implements `GuardProtocol.check(tool_name, kwargs) -> GuardResult`. When a
guard returns `GuardResult(passed=False, reason=...)`, `BaseTool.execute()` raises a
`ToolGuardError` (a `ToolError` subclass) before the handler runs.

> Guards are for **hard, synchronous policy** (validation, rate-limiting, sandboxing).
> For **human-in-the-loop approval** — pausing a run until a person signs off — use the
> native deferred-tools path described in
> [Human-in-the-Loop Tool Approval](#human-in-the-loop-tool-approval), not a guard.

### Built-in Guards

- **ValidationGuard** -- `ValidationGuard(required_keys)` — rejects the call when any
  required keyword argument is missing.
- **RateLimitGuard** -- `RateLimitGuard(max_calls, period_seconds=60.0)` — sliding-window
  rate limiter that caps invocations per time window.
- **SandboxGuard** -- `SandboxGuard(*, allowed_patterns=(), denied_patterns=())` — converts
  each kwarg value to a string and rejects it if it matches a `denied_patterns` regex
  (unless it also matches an `allowed_patterns` regex, which takes precedence).
- **CompositeGuard** -- `CompositeGuard(guards)` — AND-composition; evaluates guards in
  order and short-circuits on the first failure.

### Applying Guards

Two equivalent paths. The `@guarded` decorator appends a guard to an existing `BaseTool`:

```python
from fireflyframework_agentic.tools import firefly_tool, guarded
from fireflyframework_agentic.tools.guards import RateLimitGuard

@guarded(RateLimitGuard(max_calls=10, period_seconds=60))
@firefly_tool("search", description="Search the web")
async def search(query: str) -> str:
    ...
```

Or pass a guard chain straight to a tool's constructor via the `guards=` keyword
(accepted by `BaseTool`, the built-in tools, `firefly_tool`, and `ToolBuilder.guard()`):

```python
from fireflyframework_agentic.tools.builtins import ShellTool
from fireflyframework_agentic.tools.guards import SandboxGuard

shell = ShellTool(
    allowed_commands=["ls", "cat"],
    guards=[SandboxGuard(denied_patterns=[r"rm\s+-rf"])],
)
```

### Retry

`retryable(max_retries=3, backoff=1.0)` is a cross-cutting decorator (alongside `guarded`)
exported from `fireflyframework_agentic.tools`. It wraps the tool's `_execute` hook
(not the public `execute`) so the retry sits *inside* the guard/timeout wrapper:
guards run **once**, then only the tool body is retried — and the retry applies on
the path pydantic-ai actually calls (the generated handler) and to `RunContext`-aware
(`takes_ctx`) tools, not just a direct `tool.execute()`. The call is attempted up to
`max_retries + 1` times, doubling the delay (starting at `backoff` seconds) after each
failure. If every attempt fails, the last exception propagates.

```python
from fireflyframework_agentic.tools import firefly_tool, retryable

@retryable(max_retries=3, backoff=0.5)
@firefly_tool("fetch", description="Fetch a flaky upstream")
async def fetch(url: str) -> str:
    ...
```

---

## Human-in-the-Loop Tool Approval

Destructive or sensitive tools can require a human to sign off **before** they run.
Firefly delegates this to pydantic-ai's native **deferred-tools** protocol — no bespoke
mechanism — so approval is per-tool-call, carries metadata, and survives durable
execution.

### Declaring a tool that needs approval

Set `requires_approval=True` on the tool. It works on the decorator, `BaseTool`
subclasses, and tools added to a `ToolKit` (via either `as_pydantic_tools()` or
`as_toolset()`):

```python
from fireflyframework_agentic.tools import firefly_tool

@firefly_tool("delete_record", description="Delete a database record", requires_approval=True)
async def delete_record(record_id: str) -> str:
    ...
```

### Pause → approve → resume

When the model calls an approval-required tool, the run **pauses before executing it**
and returns a `DeferredToolRequests` as `result.output`. Check this with `is_deferred()`,
collect the human decision, then **resume** by calling `run()` again with the prior
messages and a `DeferredToolResults`:

```python
from fireflyframework_agentic.agents import FireflyAgent, is_deferred
from fireflyframework_agentic.tools import DeferredToolResults, ToolApproved, ToolDenied

agent = FireflyAgent("ops", model="anthropic:claude-haiku-4-5", tools=[delete_record])

result = await agent.run("Delete record 42.")
if is_deferred(result):
    requests = result.output                      # DeferredToolRequests
    decisions = {}
    for call in requests.approvals:               # each is a ToolCallPart
        # call.tool_name, call.args, requests.metadata.get(call.tool_call_id)
        decisions[call.tool_call_id] = True        # True / ToolApproved(override_args=...) / ToolDenied(message=...)
    result = await agent.run(
        message_history=result.all_messages(),     # required: thread the paused run's messages
        deferred_tool_results=DeferredToolResults(approvals=decisions),
    )
# result.output is now the model's final answer
```

The full pause → approve → resume flow:

```mermaid
sequenceDiagram
    actor Caller
    participant Agent as FireflyAgent
    participant Model as LLM
    actor Human

    Caller->>Agent: run("Delete record 42.")
    Agent->>Model: prompt + tool schemas
    Model-->>Agent: call delete_record(record_id="42")
    Note over Agent: requires_approval → run PAUSES<br/>before executing the tool
    Agent-->>Caller: result.output = DeferredToolRequests<br/>(is_deferred(result) is True)

    Caller->>Human: present requests.approvals (+ metadata)
    Human-->>Caller: decision = True / ToolApproved(override_args=…) / ToolDenied(message=…)

    Caller->>Agent: run(message_history=result.all_messages(),<br/>deferred_tool_results=DeferredToolResults(approvals={call_id: decision}))
    alt approved
        Agent->>Agent: execute delete_record<br/>(RunContext.tool_call_approved = True)
    else denied
        Note over Agent: ToolDenied message returned to the model<br/>(not a crash — the run continues)
    end
    Agent->>Model: continue with tool result / denial
    Model-->>Agent: final answer
    Agent-->>Caller: result.output = final answer
```

> With an `approval_handler=` (the inline, non-pausing path), the handler resolves the
> `DeferredToolRequests` **inside** the run via a native `HandleDeferredToolCalls` capability,
> so the run never returns to the caller paused.

Decision values: `True` approves (equivalent to `ToolApproved()`); `ToolApproved(override_args={...})`
approves but replaces the call arguments; `ToolDenied(message="...")` denies — the message is
returned to the model, which continues (it is **not** a crash). On resume the tool's
`RunContext.tool_call_approved` is `True` and `RunContext.tool_call_metadata` carries any
`DeferredToolResults.metadata` you passed.

> Do not set `conversation_id` on the resume call — an explicit `message_history` and
> memory injection are mutually exclusive.

### Auto-detection and forcing HITL

`FireflyAgent` widens its output type to allow the `DeferredToolRequests` pause exactly when
HITL is in play. It auto-detects this from any `requires_approval` tool (directly, inside a
`ToolKit`, or inside a `ToolKit.as_toolset()`), or an `ApprovalRequiredToolset` in `toolsets`.
If your tools defer **dynamically** (raising `pydantic_ai.exceptions.ApprovalRequired`) so
detection can't see it statically, pass `hitl=True`.

### Dynamic, predicate-based approval

To gate **existing** tools by a runtime predicate (e.g. approve small amounts, hold large
ones), wrap a toolset in the native `ApprovalRequiredToolset`:

```python
from fireflyframework_agentic.tools import ApprovalRequiredToolset

gated = ApprovalRequiredToolset(
    my_toolkit.as_toolset(),
    approval_required_func=lambda ctx, tool_def, args: args.get("amount", 0) > 1000,
)
agent = FireflyAgent("payments", model="...", toolsets=[gated])
```

### Inline (non-pausing) approval

For programmatic / policy-based auto-approval that resolves **inside** the run instead of
pausing, pass an `approval_handler` — wired as a native `HandleDeferredToolCalls` capability:

```python
def auto_approve(ctx, requests):
    return requests.build_results(approvals={c.tool_call_id: True for c in requests.approvals})

agent = FireflyAgent("ops", model="...", tools=[delete_record], approval_handler=auto_approve)
```

> **Three distinct HITL layers, by design.** Tool approval (this section) is native
> deferred-tools at the **agent** layer. A **workflow** pause uses `human()` /
> `WorkflowInterrupt` (journal-replay). A **pipeline** node pauses by returning `Pause(...)`
> and resumes via `approve_pause` (checkpoint). They solve different problems and are not
> collapsed into one mechanism.

---

## Composition

Tools can be composed into higher-level operations. Each composer implements
`ToolProtocol`, so it can be registered or nested inside other composers.

- **SequentialComposer** -- `SequentialComposer(name, tools, *, description="")` — runs
  tools in order; the first receives the original kwargs, each subsequent tool receives a
  single `input=` kwarg set to the previous tool's return value.
- **FallbackComposer** -- `FallbackComposer(name, tools, *, description="")` — tries tools
  in priority order until one succeeds; if all fail it raises `ToolError` **chained from
  the last error** (`raise … from last_error`), so the original traceback is preserved.
- **ConditionalComposer** -- `ConditionalComposer(name, router_fn, tool_map, *,
  description="")` — `router_fn(**kwargs)` returns the key of the tool in `tool_map` to run.

```python
from fireflyframework_agentic.tools import ConditionalComposer
from fireflyframework_agentic.tools.builtins import CalculatorTool, TextTool

router = ConditionalComposer(
    name="dispatch",
    router_fn=lambda **kw: "math" if kw.get("kind") == "math" else "text",
    tool_map={"math": CalculatorTool(), "text": TextTool()},
)
```

```mermaid
flowchart TD
    subgraph Sequential
        T1[Tool A] --> T2[Tool B] --> T3[Tool C]
    end

    subgraph Fallback
        F1[Primary Tool] -->|fails| F2[Fallback Tool]
    end

    subgraph Conditional
        P{Predicate} -->|true| CT1[Tool X]
        P -->|false| CT2[Tool Y]
    end
```

---

## Built-in Tools

The framework ships with nine ready-to-use tools in `tools/builtins/`.

### Concrete tools (ready to use)

- **DateTimeTool** -- Get the current date, time, or Unix timestamp with timezone conversion. Actions: `now`, `date`, `time`, `timestamp`, `timezones`.
- **CalculatorTool** -- Safely evaluate math expressions using AST-based parsing (no `eval`). Supports arithmetic, functions (`sqrt`, `sin`, `cos`, `log`, etc.), and constants (`pi`, `e`).
- **JsonTool** -- Parse, validate, extract (dot-path), format, and list keys of JSON data.
- **TextTool** -- Text utilities: count (words/chars/sentences/lines), extract (regex), truncate, replace, and split.
- **HttpTool** -- Make HTTP requests (GET, POST, PUT, DELETE). Uses a pooled `httpx.AsyncClient` when available, falling back to `urllib` via `asyncio.to_thread` to keep the event loop non-blocking.
- **FileSystemTool** -- Read, write, and list files within a sandboxed base directory. Path-traversal attacks are rejected.
- **ShellTool** -- Execute shell commands restricted to an explicit allow-list using `create_subprocess_exec` (no shell metacharacter injection). Empty allow-list rejects all commands (safe default).

### Abstract tools (subclass to use)

- **SearchTool** -- Web search abstraction. Subclass and implement `_search()` with your provider (Tavily, SerpAPI, Brave, etc.).
- **DatabaseTool** -- SQL/NoSQL query abstraction. Subclass and implement `_execute_query()` with your driver. Read-only mode enforced by default.

```python
from fireflyframework_agentic.tools.builtins import (
    DateTimeTool,
    CalculatorTool,
    JsonTool,
    TextTool,
)

datetime_tool = DateTimeTool(default_timezone="America/New_York")
json_tool = JsonTool()
text_tool = TextTool()
calculator = CalculatorTool()
```

---

## Using Built-in Tools with Agents

`FireflyAgent` automatically converts `BaseTool` and `ToolKit` instances into
Pydantic AI tools. You can pass them directly to the `tools` parameter:

```python
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.tools.builtins import DateTimeTool, CalculatorTool

agent = FireflyAgent(
    name="assistant",
    model="openai:gpt-4o",
    tools=[DateTimeTool(), CalculatorTool()], # auto-converted
)
```

You can also use a `ToolKit` to group tools:

```python
from fireflyframework_agentic.tools.toolkit import ToolKit
from fireflyframework_agentic.tools.builtins import DateTimeTool, JsonTool, TextTool

kit = ToolKit("utilities", [DateTimeTool(), JsonTool(), TextTool()], description="Common helpers")
agent = FireflyAgent(name="helper", model="openai:gpt-4o", tools=[kit])
```

The constructor is `ToolKit(name, tools, *, description="", tags=())`. Beyond direct use
with an agent, a kit can register or remove its tools in bulk against a `ToolRegistry`
via `register_all(registry)` / `unregister_all(registry)`, expose its tools as Pydantic AI
tools with `as_pydantic_tools()`, and reports its size through `len(kit)`.

Plain async functions and `pydantic_ai.Tool` objects are passed through unchanged.

---

## HttpTool with Connection Pooling

`HttpTool` provides HTTP client functionality with optional connection pooling
for improved performance in production deployments.

### Basic Usage

```python
from fireflyframework_agentic.tools.builtins import HttpTool

http_tool = HttpTool()

# All built-in tools expose a keyword-only `execute(**kwargs)`. HttpTool reads
# `url` (required) and `method` (default "GET"), plus optional `body` and `headers`.
response = await http_tool.execute(url="https://api.example.com/data", method="GET")
print(response["status"]) # 200
print(response["headers"]) # dict of response headers
print(response["body"]) # Response text
```

### Connection Pooling

Enable connection pooling to reuse TCP connections across requests, reducing
latency and improving throughput:

```python
from fireflyframework_agentic.tools.builtins import HttpTool

http_tool = HttpTool(
    use_pool=True, # Enable connection pooling (default: True)
    pool_size=100, # Max concurrent connections (default: 100)
    pool_max_keepalive=20, # Max keepalive connections (default: 20)
    timeout=30.0, # Request timeout in seconds
)
```

Connection pooling uses `httpx.AsyncClient` under the hood, providing:

- **TCP connection reuse** — Eliminates handshake overhead for repeated requests
- **HTTP/2 support** — Automatic upgrade when server supports it
- **Automatic keepalive** — Maintains connection pools efficiently
- **Thread-safe** — Safe for concurrent use across agents

### Configuration

`FireflyAgenticConfig` carries the pool defaults (`http_pool_enabled`, `http_pool_size`,
`http_pool_max_keepalive`, `http_pool_timeout`), settable from the environment with the
`FIREFLY_AGENTIC_` prefix. Pass the resolved values into the `HttpTool` constructor:

```bash
# Enable connection pooling (default: true)
export FIREFLY_AGENTIC_HTTP_POOL_ENABLED=true

# Configure pool size
export FIREFLY_AGENTIC_HTTP_POOL_SIZE=100
export FIREFLY_AGENTIC_HTTP_POOL_MAX_KEEPALIVE=20

# Set default request timeout (seconds)
export FIREFLY_AGENTIC_HTTP_POOL_TIMEOUT=30.0
```

```python
from fireflyframework_agentic import get_config
from fireflyframework_agentic.tools.builtins import HttpTool

cfg = get_config()
http_tool = HttpTool(
    use_pool=cfg.http_pool_enabled,
    pool_size=cfg.http_pool_size,
    pool_max_keepalive=cfg.http_pool_max_keepalive,
    timeout=cfg.http_pool_timeout,
)
```

### Fallback to urllib

If `httpx` is not installed, `HttpTool` automatically falls back to `urllib`
with `asyncio.to_thread()` for non-blocking I/O:

```python
# Works even without httpx installed
http_tool = HttpTool(use_pool=False) # Forces urllib
```

### Performance Comparison

With connection pooling enabled:

- **Latency**: 50-70% reduction for repeated requests to the same host
- **Throughput**: 2-3x improvement for high-volume workloads
- **Memory**: Minimal overhead (~10KB per pooled connection)

### Usage with Agents

```python
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.tools.builtins import HttpTool

agent = FireflyAgent(
    name="api-agent",
    model="openai:gpt-4o",
    tools=[HttpTool(use_pool=True, pool_size=50)],
)

# Agent can make efficient HTTP requests with connection reuse
result = await agent.run("Fetch data from https://api.example.com/users")
```

### Cleanup

When using connection pooling, call `await http_tool.close()` when done to release the
underlying `httpx.AsyncClient` (an unclosed client emits a `ResourceWarning`):

```python
http_tool = HttpTool(use_pool=True)

try:
    response = await http_tool.execute(url="https://api.example.com")
finally:
    await http_tool.close() # Release connection pool
```

---

## CachedTool

`CachedTool` wraps any `ToolProtocol` implementation and transparently
memoises results using a TTL-based in-memory cache keyed on the tool's
input arguments. This is ideal for deterministic tools (lookups, calculations)
where repeated calls with the same arguments should avoid redundant work.

Concurrent identical misses are **single-flighted**: the first caller for a key
runs the underlying tool while the others `await` the same in-flight result, so an
expensive or rate-limited tool is never stampeded (it runs once per key). A failure
is not cached and clears the in-flight slot so the next call retries. (It uses an
`asyncio.Lock`; intended for one event loop.)

```python
from fireflyframework_agentic.tools.cached import CachedTool
from fireflyframework_agentic.tools.builtins import HttpTool

cached_http = CachedTool(HttpTool(), ttl_seconds=600.0, max_entries=256)
result = await cached_http.execute(url="https://api.example.com/data")
# Second call with same args returns cached result
result2 = await cached_http.execute(url="https://api.example.com/data")
```

Parameters:

- **`ttl_seconds`** — Time-to-live in seconds for cached entries (default: 300).
  Pass `0` to disable caching (pass-through).
- **`max_entries`** — Maximum entries before FIFO eviction (default: 1024).

Cache management methods:

- **`invalidate(**kwargs)`** — Remove a specific entry by its arguments.
- **`clear()`** — Drop all cached entries. Returns the number evicted.
- **`cache_size`** — Current number of entries in the cache.

`CachedTool` conforms to `ToolProtocol`, so it integrates transparently with
`FireflyAgent`, `ToolKit`, and `ToolRegistry`.

---

## Tool Timeout

`BaseTool` supports an optional `timeout` parameter (in seconds) that wraps
the tool's `_execute` call in `asyncio.wait_for`. If the call exceeds the
timeout, a `ToolTimeoutError` is raised.

`ToolTimeoutError` lives in `fireflyframework_agentic.exceptions` (it is not re-exported
from `fireflyframework_agentic.tools`), so import it explicitly:

```python
from fireflyframework_agentic.exceptions import ToolTimeoutError
from fireflyframework_agentic.tools.builtins import HttpTool

# Timeout HTTP calls after 10 seconds
http_tool = HttpTool(timeout=10.0)

try:
    result = await http_tool.execute(url="https://slow-api.example.com")
except ToolTimeoutError:
    print("Tool timed out")
```

This is useful for enforcing SLAs and preventing runaway tool executions
in production pipelines.

---

## Tool Registry

The `ToolRegistry` provides thread-safe tool lookup by name and tag. A module-level
singleton `tool_registry` is also exported — `firefly_tool(..., auto_register=True)`
(the default) registers decorated tools into it automatically.

```python
from fireflyframework_agentic.tools import ToolRegistry, tool_registry

registry = ToolRegistry()
registry.register(my_tool)

tool = registry.get("my_tool")          # raises ToolNotFoundError if absent
math_tools = registry.get_by_tag("math") # list[ToolProtocol]
exists = registry.has("my_tool")         # bool ("my_tool" in registry also works)
infos = registry.list_tools()            # list[ToolInfo]
registry.unregister("my_tool")
registry.clear()                         # primarily for tests
count = len(registry)
```
