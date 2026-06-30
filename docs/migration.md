# Migration Guide

This guide covers the breaking and behavioural changes introduced when the tools
and Dynamic Workflows subsystems were aligned with pydantic-ai's native model.
Each change lists the **why**, the **before → after**, and whether it is a hard
break or a behavioural shift.

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

```python
# Before — guard that blocks the run on denial
from fireflyframework_agentic.tools.guards import ApprovalGuard

async def approve(tool_name, kwargs) -> bool:
    return await ask_admin(tool_name, kwargs)

@guarded(ApprovalGuard(callback=approve))
@firefly_tool("delete_record", description="Delete a record")
async def delete_record(record_id: str) -> str: ...

# After — native: the run PAUSES for sign-off, then resumes
from fireflyframework_agentic.agents import is_deferred
from fireflyframework_agentic.tools import DeferredToolResults

@firefly_tool("delete_record", description="Delete a record", requires_approval=True)
async def delete_record(record_id: str) -> str: ...

result = await agent.run("delete record 42")
if is_deferred(result):
    approvals = {c.tool_call_id: await ask_admin(c) for c in result.output.approvals}  # bool / ToolApproved / ToolDenied
    result = await agent.run(message_history=result.all_messages(),
                             deferred_tool_results=DeferredToolResults(approvals=approvals))
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
