# Migration Guide

This guide covers the Pydantic AI 2.x upgrade and the earlier tool and Dynamic
Workflow changes. It distinguishes dependency changes from changes to Firefly's
public API and model routing.

## Pydantic AI 2 and OpenAI API selection

The framework now requires `pydantic-ai>=2.51.0,<3` and
`genai-prices>=0.1.9,<0.2`. Update application constraints that still require
Pydantic AI 1.x, then resolve dependencies and run your application tests. The
framework declares provider extras explicitly to preserve its existing provider
integrations under the new dependency layout.

### Existing OpenAI agents keep Chat Completions

The framework preserves the endpoint for existing configurations:

```python
# Before and after the dependency upgrade: Chat Completions.
agent = FireflyAgent(name="assistant", model="openai:gpt-4o")
spec = ModelSpec(provider="openai", model="gpt-4o")

# Explicit equivalents for new/shared configuration.
agent = FireflyAgent(name="assistant", model="openai-chat:gpt-4o")
spec = ModelSpec(provider="openai-chat", model="gpt-4o")
```

The same rule applies to `azure:` / `provider="azure"`, with `azure-chat:` /
`provider="azure-chat"` as the explicit form. An existing preconfigured
`OpenAIChatModel` stays on Chat Completions; an `OpenAIResponsesModel` stays on
Responses. `ModelSpec(model_class="OpenAIResponsesModel", provider="openai", ...)`
remains valid.

Explicit API selection also applies to fallback models and evaluation judges.
After a fallback run, Firefly restores the original model and identifier and
resets the fallback chain, including when the run succeeds or fails.

If application code constructs a **bare `pydantic_ai.Agent`**, its `openai:` prefix
now selects Responses. Use `openai-chat:` there to retain the old endpoint, or
`openai-responses:` to adopt the new one deliberately. This also matters when
sharing a model string with an upstream library outside Firefly. See
[Pydantic AI's OpenAI configuration](https://pydantic.dev/docs/ai/models/openai/).

### Opt into Responses

```python
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.models import ModelOptions

# Reads OPENAI_API_KEY from the environment.
agent = FireflyAgent(
    name="assistant",
    model="openai-responses:gpt-6-luna",
    model_options=ModelOptions(reasoning="low", store_responses=False),
)
first = await agent.run("The project name is Lantern. Acknowledge it.")
second = await agent.run("What is its name?", message_history=first.all_messages())
```

Your tool definitions, output models, and `run` / `run_sync` / `run_stream` calls
keep the same interface. Pydantic AI handles each endpoint's request and response
shapes. Use `provider="openai-responses"` in `ModelSpec`, or `azure-responses` for
an Azure deployment that supports Responses. Custom OpenAI-compatible services
must implement the selected API; changing a prefix cannot add server support.

For GPT-6 model and endpoint restrictions, follow the
[compatibility table](models.md#gpt-6-model-selection). In particular, migrating
an Astra agent with tools requires Responses. Review reasoning effort and remove
sampling/log-probability settings that the selected mode rejects, including any
configured default temperature. See the
[official OpenAI migration guide](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart).

### Settings, profiles, and conversation history

- Prefer `ModelOptions` for framework-owned settings, including reasoning and
  provider response storage. Pass `model_options=` to an agent or individual run,
  or `options=` to `ModelSpec`. Unsupported options raise `ModelOptionsError`.
  See the [typed option reference](models.md#typed-model-options).
- `ModelSpec.settings` preserves native Pydantic AI provider settings such as
  `openai_reasoning_effort` and `openai_store`, alongside the translated console
  settings. Pass `factory.settings_for(spec)` to `FireflyAgent(model_settings=...)`.
- Pydantic AI 2.x model profiles are dictionaries. Replace custom code that uses
  `dataclasses.replace(profile, ...)` or attribute access with dictionary merging
  and key access. `ModelSpec.profile_overrides` remains a mapping.
- `message_history` and Firefly memory continue to carry conversation state.
  Optional `openai_previous_response_id="auto"` chains stored Responses using
  response IDs from that history. It requires storage; leave it unset with
  `openai_store=False`. See the [conversation-state example](agents.md#responses-conversation-state).
- Completed buffered and incremental streams now persist their full messages to
  Firefly memory, including provider metadata and Responses reasoning state.
  Interrupted streams do not persist an incomplete conversation turn.

The offline HTTP compatibility suite checks the SDK/framework request boundary.
It does not establish live model access. Use the credential-gated OpenAI suite for
your selected deployment and model before rollout; commands and scope are in
[tests/README.md](https://github.com/fireflyframework/fireflyframework-agentic/blob/main/tests/README.md#live-model-tests).

### Database memory lifecycle

PostgreSQL and MongoDB clients now stay on a persistent event loop owned by their
store. This permits initialization and the synchronous memory facade to share the
same database connection safely. Existing `await store.initialize()` and
`await store.close()` remain supported; `initialize_sync()` and `close_sync()` are
available to synchronous hosts. `MemoryManager.from_config()` initializes the
backend, and applications must call `manager.close()` or `await manager.aclose()`
after every manager/fork using the shared backend has finished.

Initialization through `from_config()` and synchronous memory methods block the
caller. Async hosts can offload the factory with `asyncio.to_thread()` and use the
store's async methods for nonblocking I/O. See [Memory](memory.md#shutdown).

### Capabilities and instrumentation

Firefly exposes Pydantic AI 2.x `capabilities=` for native tools and other agent
capabilities. Existing framework tools still use `tools=` / `toolsets=`. See the
[native-capabilities example](agents.md#native-capabilities). Firefly explicitly
keeps `end_strategy="early"`; `"graceful"` and `"exhaustive"` are opt-in.

Native instrumentation defaults to version `5`; legacy configured versions `1`
through `4` map to `5`, and version `6` can be selected explicitly. Pydantic AI 2.x
removed the separate log-event mode: `instrumentation_event_mode` remains accepted
for configuration compatibility but has no effect, and events are represented as
span attributes. Update telemetry queries and exporters that consumed the old log
events. Content inclusion remains controlled by `instrumentation_include_content`.

### Optional evaluation dependencies

The `[evaluation]` extra retains [Ragas 0.2.6](https://pypi.org/project/ragas/0.2.6/)
(`>=0.2.6,<0.2.7`) with `langchain-community>=0.3.31,<0.4`. This is a compatibility
pin: Ragas 0.4.3 requires Instructor, whose
[`jiter<0.15` constraint](https://pypi.org/pypi/instructor/1.17.0/json) conflicts
with [OpenAI 3.19's `jiter>=0.16`](https://pypi.org/pypi/openai/3.19.0/json).
Intermediate Ragas 0.2.7–0.3.1 also patches asyncio during import.

The pinned extra resolves with the upgraded SDK. Framework metric adapters pass
LLM and embedding clients through Ragas `evaluate(...)` so its wrappers apply
correctly. Offline tests exercise the actual metric implementations and check
that importing Ragas preserves the active event loop; this does not claim support
for the latest Ragas release or validate live judge quality.

---

## 1. Tool parameters use a real `python_type` (breaking)

**Why.** Tool parameter schemas were declared with a *string* `type_annotation`
resolved through a tiny built-in map that only understood `str`/`int`/`float`/
`bool`/`list`/`dict` and **dropped** generic element types, enums and nested
models. The LLM therefore saw lossy schemas (`list[str]` became an untyped array,
`Literal[...]` lost its `enum`). `ParameterSpec` now takes a **real Python type
object**, which pydantic-ai introspects directly for a full-fidelity schema.

The string `type_annotation` field and its resolver (`_TYPE_MAP`,
`_resolve_param_type`) have been **removed** — there is one way to declare a type.

### `ParameterSpec`

```python
# Before
ParameterSpec(name="tags", type_annotation="list[str]")          # array with no item type
ParameterSpec(name="body", type_annotation="dict[str, Any] | None")

# After
ParameterSpec(name="tags", python_type=list[str])                # array of strings
ParameterSpec(name="body", python_type=dict[str, Any] | None)
ParameterSpec(name="mode", python_type=Literal["fast", "slow"])  # now a real enum
```

`python_type` defaults to `str`, so `ParameterSpec(name="q")` is a string param.

### `ToolBuilder.parameter()`

The second argument is now the real type, not a string:

```python
# Before
ToolBuilder("weather").parameter("city", "str", description="City name")

# After
ToolBuilder("weather").parameter("city", str, description="City name")
```

### Built-in tools

All built-in tools were migrated; if you subclassed `BaseTool` or built tools with
`ParameterSpec`/`ToolBuilder`, replace each string type with the real type. There is
no compatibility shim — a stray `type_annotation=` keyword is simply ignored by the
model (it is no longer a field).

---

## 2. Tools can opt into `RunContext` (new, additive)

A tool can now receive pydantic-ai's `RunContext` (agent deps, usage, retry count,
messages) by setting `takes_ctx=True`. The context is delivered to `_execute` as the
keyword-only `_ctx`; **guards and the cache never see it**, so it cannot poison a
cache key.

```python
class SetPriority(BaseTool):
    def __init__(self) -> None:
        super().__init__("set_priority", takes_ctx=True,
                         parameters=[ParameterSpec(name="level", python_type=str)])

    async def _execute(self, *, _ctx=None, **kwargs):
        return f"{_ctx.deps}: {kwargs['level']}"   # reach the agent's deps
```

Decorated tools (`@firefly_tool`) that declare a `RunContext`-first parameter already
get it natively — no change.

---

## 3. Native toolset combinators are re-exported (new, additive)

`fireflyframework_agentic.tools` now re-exports pydantic-ai's `RunContext` and the
native toolset combinators (`FilteredToolset`, `PrefixedToolset`, `RenamedToolset`,
`CombinedToolset`, `WrapperToolset`, `PreparedToolset`, `ApprovalRequiredToolset`),
plus `to_pydantic_handler(tool)`. Import them from the tools package instead of
reaching into `pydantic_ai.toolsets`. `ToolKit.as_toolset()` now also forwards each
tool's **description** to the model (it was previously dropped).

---

## 4. `FireflyAgentRunner` is the default workflow runner (behavioural)

**Why.** Workflow sub-agents used to run as a bare `pydantic_ai.Agent`, bypassing the
whole framework. They now run through a `FireflyAgent` by default, inheriting the
middleware chain (logging, prompt/output guards, cost guard, caching, observability,
explainability, validation, retry), the 429 rate-limit retry loop, the **global usage
tracker / budget gate**, and model fallback.

What changes for you:

- **Cost is now tracked globally** for workflow sub-agents, and a configured global
  `budget_limit_usd` (BudgetGate) now applies to them — a workflow can raise
  `BudgetExceededError` where it previously would not. Per-run `WorkflowBudget` is
  unchanged and still applies on top.
- The **model-resolution contract is unchanged**: you still pass `model=` per call or
  `default_model=` on the runner; nothing new is required.

To keep the old lightweight, bare-`pydantic_ai.Agent` behaviour, opt out explicitly:

```python
from fireflyframework_agentic.workflows import DefaultAgentRunner

await my_workflow(args, runner=DefaultAgentRunner())   # the lightweight path
```

---

## 5. Per-call agent targeting with `using=` (new, additive)

A single workflow can route different calls to different configured agents — for
multi-model sub-agents and per-task cost optimisation:

```python
@workflow(name="triage")
async def triage(args, ctx):
    label = await agent("classify the ticket", using="cheap-classifier")
    return await agent("write the resolution", using="premium-writer")

await triage(args, runner=FireflyAgentRunner())   # both resolved from the registry
```

`using` accepts a `FireflyAgent` instance or a registry name. With a non-
`FireflyAgentRunner` runner it raises a clear error.

---

## 6. `ApprovalGuard` removed — human-in-the-loop is now native (breaking)

**Why.** Tool approval was a bespoke guard (`ApprovalGuard(callback)`) that ran inside
Firefly's guard chain and raised `ToolError` on a denied call — a synchronous, all-or-nothing
gate with no pause/resume, metadata, or per-call granularity, parallel to pydantic-ai's own
deferred-tools protocol. It has been **removed** in favour of the native protocol
(`requires_approval`, `DeferredToolRequests`/`DeferredToolResults`, `ApprovalRequired`,
`ApprovalRequiredToolset`).

Previously, `ApprovalGuard(callback=approve)` wrapped a tool and blocked denied
calls. Remove that guard and mark the tool `requires_approval=True`. This complete
replacement pauses, asks for an explicit decision, and resumes the same history:

```python
import asyncio

from fireflyframework_agentic.agents import FireflyAgent, is_deferred
from fireflyframework_agentic.tools import DeferredToolResults, firefly_tool

records = {"42": {"title": "Draft invoice"}}

@firefly_tool("delete_record", description="Delete a local example record", requires_approval=True)
async def delete_record(record_id: str) -> str:
    removed = records.pop(record_id, None)
    return "Deleted" if removed is not None else "Record not found"

agent = FireflyAgent(name="approved-delete", tools=[delete_record])
result = await agent.run("Delete record 42")
if is_deferred(result):
    approvals = {}
    for call in result.output.approvals:
        answer = await asyncio.to_thread(input, f"Approve {call.tool_name} {call.args}? [y/N] ")
        approvals[call.tool_call_id] = answer.strip().lower() == "y"
    result = await agent.run(
        message_history=result.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals=approvals),
    )
```

For the old **inline, non-pausing** behaviour (a callback decides programmatically), pass
`FireflyAgent(approval_handler=...)` — wired as a native `HandleDeferredToolCalls` capability.
See [Human-in-the-Loop Tool Approval](tools.md#human-in-the-loop-tool-approval).

Also: guard denials (validation, rate-limit, sandbox) now raise `ToolGuardError` instead of a
plain `ToolError`. `ToolGuardError` **subclasses** `ToolError`, so existing `except ToolError`
handlers keep working.

---

## Checklist

- [ ] Replace every `type_annotation="..."` with `python_type=<real type>` in
      `ParameterSpec` and `ToolBuilder.parameter(name, <type>)`.
- [ ] (Optional) Enrich types now that they are real — `list[str]`, `Literal[...]`,
      nested models — for better LLM tool schemas.
- [ ] (Optional) Add `takes_ctx=True` to tools that need agent deps/usage.
- [ ] Review workflows for global cost/budget effects now that sub-agents run through
      `FireflyAgent`; pass `runner=DefaultAgentRunner()` if you want the old path.
- [ ] Import toolset combinators / `RunContext` from `fireflyframework_agentic.tools`.
- [ ] Replace `ApprovalGuard` with `requires_approval=True` + the native pause/resume flow
      (`is_deferred()` + `deferred_tool_results=`), or an inline `approval_handler=`.
- [ ] If you matched on `ToolError` from guard denials specifically, note it is now the
      `ToolGuardError` subclass (still caught by `except ToolError`).
