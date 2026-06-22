# Dynamic Workflows

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

`fireflyframework_agentic.workflows` is a **code-defined orchestration DSL** for
fanning out isolated sub-agents and reducing their results in plain Python. The
plan lives in your script's control flow — not in a model's context — so an
orchestration is deterministic, inspectable, and resumable. It mirrors the
mechanism Claude Code uses for multi-agent workflows, adapted to Python and
[Pydantic AI](https://ai.pydantic.dev/).

It is a peer of, not a replacement for, two existing layers:

- **[Reasoning patterns](reasoning.md)** drive a single agent's *reason → act →
  observe* loop. A workflow is the opposite concern: deterministic orchestration
  *across* many agents.
- **[Pipelines](pipeline.md)** are declarative DAGs with checkpointing and HITL.
  A workflow is an *imperative* code-first façade for fan-out/gather/verify
  patterns that read more naturally as a function than as a graph.

---

## Quick start

```python
from pydantic import BaseModel
from fireflyframework_agentic.workflows import (
    workflow, agent, parallel, pipeline, phase, run_workflow, WorkflowBudget,
)

class ResearchArgs(BaseModel):
    queries: list[str]
    model: str = "openai:gpt-4o-mini"

@workflow(name="deep_research", args_schema=ResearchArgs)
async def deep_research(args, ctx):
    with phase("search"):
        # parallel() is a barrier; a failed branch resolves to None (never raises)
        hits = await parallel([
            (lambda q=q: agent(f"search the web for: {q}", model=args.model))
            for q in args.queries
        ])

    # reduce in PLAIN PYTHON — deterministic, no model call
    candidates = sorted({h for h in hits if h is not None})

    with phase("verify"):
        # pipeline() streams each item through every stage with no inter-stage barrier
        verified = await pipeline(candidates, verify_stage, score_stage)

    with phase("synthesize"):
        return await agent("write a cited report", deps=verified, model=args.model)

async def verify_stage(prev, item, index):
    return prev  # ... call agent(), drop weak candidates, etc.

async def score_stage(prev):
    return prev

# Run it (the body returns whatever you return):
report = await run_workflow(
    "deep_research",
    {"queries": ["pydantic-ai durable execution", "pydantic v2.13 features"]},
    budget=WorkflowBudget(max_concurrent_agents=8, max_tokens=500_000),
)
```

A `@workflow`-decorated function can be invoked directly (`await deep_research(args)`)
or by name through `run_workflow("deep_research", args)`.

---

## Primitives

| Primitive | Signature | Semantics |
|---|---|---|
| `agent` | `await agent(prompt, *, label, model, output_type, instructions, deps, tools, toolsets)` | Run one isolated sub-agent; returns its `output` (a `str` or a validated `output_type`). A sub-agent can use `tools=`/`toolsets=` (e.g. `ToolKit.as_toolset()` or an MCP server) just like a top-level agent. Honours the budget, the concurrency gate, and the resume journal. |
| `parallel` | `await parallel(thunks)` | **Barrier.** Run zero-arg async thunks concurrently; a thunk that raises resolves to `None` (the call never propagates). Returns a list aligned to `thunks`. |
| `pipeline` | `await pipeline(items, *stages)` | **No inter-stage barrier.** Each item flows through every stage independently (item A can be in stage 3 while B is in stage 1). Each stage receives `(prev, item, index)` — declare only the params you need. A stage that raises drops *that* item to `None`. |
| `stream` | `async with stream(prompt, ...) as s:` | Stream one sub-agent token-by-token: iterate `s.text()` for deltas; `s.output` holds the full output after the block. Same budget/journal/cost accounting as `agent`. Requires a streaming runner. See [Streaming](#streaming). |
| `phase` | `with phase("title"):` | Group enclosed work for telemetry (`phase.start` / `phase.end` events). |
| `log` | `log("message")` | Emit a narrator line to the run's event handler. |

**Reduce in Python, not with a model.** The strength of the DSL is that the
glue between agent calls — dedup, rank, filter, branch — is ordinary
deterministic Python. Reach for an `agent()` only when you genuinely need a
model.

### Type safety

The DSL is statically typed end-to-end. `agent(output_type=T)` is typed to
return `T` (not `Any`), and `@workflow` produces a `Workflow[OutputT]` inferred
from the function's return annotation — so the awaited result is typed too:

```python
from pydantic import BaseModel
from fireflyframework_agentic.workflows import workflow, agent

class Report(BaseModel):
    summary: str
    sources: list[str]

@workflow(name="research")
async def research(args, ctx) -> Report:
    return await agent("write the report", output_type=Report)   # typed Report

report: Report = await research(args)   # research is Workflow[Report]; result is Report
```

Without `output_type`, `agent()` returns `Any` (the raw string output). Pyright
infers all of the above with no casts.

---

## Budgets

Every run is bounded by a `WorkflowBudget`:

```python
WorkflowBudget(
    max_concurrent_agents=8,   # asyncio.Semaphore; default min(16, cpu - 2)
    max_agents_total=1000,     # hard kill-switch (runaway-loop backstop)
    max_tokens=500_000,        # optional output-token ceiling for the whole run
    max_cost_usd=2.50,         # optional USD ceiling (priced via genai-prices)
    max_wall_seconds=120,      # optional wall-clock ceiling for the whole run
)
```

Exceeding any ceiling raises `WorkflowBudgetError` — including **inside a
`parallel`/`pipeline` fan-out** (a kill-switch aborts the run; only ordinary
branch failures resolve to `None`). Token *and dollar* cost are fed by each
`AgentRunner` call's reported usage, priced through the same `genai-prices` cost
stack the rest of the framework uses; read live spend with
`ctx.tokens_spent` / `ctx.cost_spent_usd` and the remaining headroom with
`ctx.remaining_tokens()` / `ctx.remaining_cost_usd()`.

---

## Deterministic resume (the journal)

Every `agent()` call is keyed by its sequence number and recorded in a `Journal`.
Re-running the workflow with a *populated* journal serves completed calls from
cache and runs only new calls live:

```python
from fireflyframework_agentic.workflows import Journal

journal = Journal()
await run_workflow("deep_research", args, journal=journal)   # full run, populates journal
# ... process crashes / you tweak a later stage ...
await run_workflow("deep_research", args, journal=journal)   # cached calls replay instantly
```

Persist `journal.to_dict()` (and rebuild with `Journal.from_dict(...)`) to resume
manually. For **durable, crash-resilient** resume, attach a `JournalBackend` — the
journal then flushes after every completed call, so an out-of-process crash
resumes from the last one:

```python
from fireflyframework_agentic.workflows import Journal, FileJournalBackend

backend = FileJournalBackend("/var/lib/firefly/workflows")
journal = Journal(backend=backend, run_key="research-job-42")   # loads if present
await run_workflow("deep_research", args, journal=journal)      # auto-flushes each call
# ... process crashes; in a fresh process, the same run_key reloads progress:
await run_workflow("deep_research", args,
                   journal=Journal(backend=backend, run_key="research-job-42"))
```

`FileJournalBackend` stores each run as JSON (strings/numbers/lists/dicts
round-trip exactly; structured outputs round-trip as their serialized form).
Implement the `JournalBackend` protocol (`load`/`save`) for Postgres/Redis/S3.

> **Determinism contract.** Replay is correct only when the orchestration code is
> deterministic. The call sequence number is assigned synchronously at the top of
> `agent()` (before any `await`), so it is stable in task-launch order even inside
> `parallel`/`pipeline`. Keep wall-clock and `random` out of control flow (or seed
> them); only the agent *calls* are treated as non-deterministic.

---

## The agent runner

`agent()` delegates LLM execution to a pluggable `AgentRunner`:

```python
class AgentRunner(Protocol):
    async def run(self, prompt, *, model=None, output_type=None, instructions=None,
                  deps=None, tools=None, toolsets=None, using=None) -> AgentCall: ...
```

- **`FireflyAgentRunner`** (**default**) runs each call through a **`FireflyAgent`**,
  so sub-agents inherit the full framework stack — see below.
- **`DefaultAgentRunner`** (lightweight alternative) runs each call as a fresh bare
  `pydantic_ai.Agent` with no shared message history — isolation by construction
  and zero coupling. Choose it explicitly (`runner=DefaultAgentRunner()`) when you
  want the minimal path with none of the FireflyAgent middleware.
- **Custom runners** make workflows trivially testable: inject a deterministic
  fake that returns canned `AgentCall(output=..., tokens=...)` and no network is
  touched.

```python
await deep_research(args, runner=MyFakeRunner())
```

### `FireflyAgentRunner` — sub-agents with the full FireflyAgent stack

This is the **default** runner: every workflow sub-agent runs through a
`FireflyAgent`, inheriting its **middleware chain** (logging, prompt/output
guards, cost guard, caching, observability, explainability, validation, retry),
the **429 rate-limit retry** loop, the **global usage tracker / budget gate**, and
**model fallback** — the same enrichment your top-level agents get. You only
construct it explicitly to configure it (a default model, or a specific agent
source):

```python
from fireflyframework_agentic.workflows import workflow, agent, FireflyAgentRunner

# The default — no runner needed; sub-agents are FireflyAgents already:
await my_workflow(args)

# Give every ephemeral sub-agent a default model (built auto_register=False, memory=None):
await my_workflow(args, runner=FireflyAgentRunner(default_model="anthropic:claude-haiku-4-5"))

# Or reuse one configured agent for every call (keeps its model/tools/middleware):
await my_workflow(args, runner=FireflyAgentRunner(my_configured_agent))
```

The `agent=` source decides how each call's agent is obtained: `None` → a fresh
**ephemeral** agent per call (isolated, mirrors `DefaultAgentRunner`); a
`FireflyAgent` instance → **reuse** it; a **registry name** (`str`) → resolve it
per call; a zero-arg **factory** → build a fresh agent per call.

**Per-call targeting with `using=`** — a single workflow can route different
calls to different configured agents (multi-model sub-agents and per-task cost
optimisation):

```python
@workflow(name="triage")
async def triage(args, ctx):
    # cheap, fast model for the easy classification...
    label = await agent("classify the ticket", using="cheap-classifier")
    # ...escalate the hard synthesis to a configured premium agent
    return await agent("write the resolution", using="premium-writer")

await triage(args, runner=FireflyAgentRunner())   # both agents come from the registry
```

`using` accepts a `FireflyAgent` instance or a registry name and overrides the
runner's source for that one call. `DefaultAgentRunner` **rejects** `using=` with a
clear error (it has no agent registry to resolve against); `SmartRoutingRunner`
**forwards** it to its `base_runner`, so `using=` works when the base is a
`FireflyAgentRunner`.

Notes:

- **Two disjoint ledgers, each billed once.** Per-call tokens/cost feed the
  per-run `WorkflowBudget`; `FireflyAgent` records the same call once to the
  *global* usage tracker. No double counting; a journal-resumed call bills neither.
- **Isolation.** Ephemeral/factory agents are built `auto_register=False`,
  `memory=None`, and never receive a `conversation_id` — no shared history, no
  registry churn. A *reused* agent that carries a `ResultCache` or memory
  intentionally opts into shared state; use the ephemeral/factory form for strict
  per-call isolation.
- **`tools=` vs `toolsets=`.** Per-call `tools=` only applies on the ephemeral
  path (pydantic-ai has no per-call `tools` parameter); for a reused agent,
  configure tools on the agent or pass `toolsets=`.
- Composes with everything: `SmartRoutingRunner(base_runner=FireflyAgentRunner(...))`,
  `cascade()`, budgets and the journal all work unchanged.

---

## Streaming

Stream a single sub-agent's output token-by-token with the `stream()` context
manager (requires a streaming-capable runner — `DefaultAgentRunner` and
`FireflyAgentRunner` both are). It
honours the budget, concurrency gate, journal and cost accounting exactly like
`agent()`:

```python
from fireflyframework_agentic.workflows import workflow, stream

@workflow(name="live_report")
async def live_report(args, ctx):
    async with stream("write a cited report", model=args.model) as s:
        async for delta in s.text():
            print(delta, end="", flush=True)   # surface tokens as they arrive
    return s.output                            # the full text, available after the block
```

On resume, a cached `stream()` call yields its full output once (the model is not
re-invoked). A runner that doesn't support streaming raises `WorkflowError`.

**Structured output.** `stream()` accepts `output_type=` like `agent()`. Token
deltas are inherently a *text* concept, so for a structured (non-text) run
`s.text()` transparently falls back to yielding stringified partial-object
**snapshots** (whole objects, not token deltas) instead of crashing; `s.output`
still holds the validated model after the block.

---

## Model routing & cost optimization

The cheapest model that can do the job should do the job. Two complementary tools
give a workflow automatic per-task model selection — the workflow body is
unchanged; only *which* model runs each `agent()` call changes.

### `SmartRoutingRunner` — cheapest capable model per call (a-priori)

A drop-in `AgentRunner`: give it model tiers ordered cheap → expensive and a
selection strategy. Each `agent()` call with **no explicit `model=`** is routed;
an explicit `model=` always wins. A transient error escalates up the ladder.

```python
from fireflyframework_agentic.workflows import (
    SmartRoutingRunner, ComplexityHeuristicStrategy, CostFloorStrategy,
)

runner = SmartRoutingRunner(
    tiers=["anthropic:claude-haiku-4-5", "anthropic:claude-sonnet-4-5"],
    strategy=ComplexityHeuristicStrategy(),   # training-free: routes by prompt length + cues
    fallback=True,                            # escalate to the next tier on a transient error
)
report = await run_workflow("deep_research", args, runner=runner)
```

- **`ComplexityHeuristicStrategy`** (default) — no extra LLM call; short/simple
  prompts route to the cheapest tier, long or reasoning-heavy prompts escalate.
- **`CostFloorStrategy`** — always start at the genai-prices cheapest tier
  (priced from the actual prompt length), leaving escalation to `fallback`.
- **Custom** — implement `ModelSelectionStrategy.select(prompt, tiers) -> int`
  (e.g. an embedding router or a cheap classifier model).

Every decision emits a structured event (`route.select`, `route.escalate`), so a
cheap-model quality regression is observable, not silent.

### `cascade()` — escalate only on low confidence (a-posteriori)

The FrugalGPT trade-off: run the cheapest tier, score its answer, and escalate
only when confidence is below `threshold`. Typically the strongest cost lever.

```python
from fireflyframework_agentic.workflows import cascade

result = await cascade(
    "Summarise this contract clause: ...",
    tiers=["anthropic:claude-haiku-4-5", "anthropic:claude-sonnet-4-5"],
    threshold=0.7,            # accept the first tier scoring >= 0.7
    # confidence=my_async_scorer(output)->float, or judge_model=... (defaults to the cheapest tier)
    output_type=None,         # constrain each tier to a pydantic model (like agent())
    instructions=None,        # per-call system instructions for every tier
    max_escalations=None,     # cap how many tiers to climb (default: all of them)
)
result.output, result.tier, result.model, result.confidence, result.escalations
```

When no `confidence` callable is given, a judge model rates each answer 0–1
(defaulting to the cheapest tier as judge). Each tier emits a `cascade.tier`
event. Cascades go through `agent()`, so they honour the run's budget and journal.

### Pricing a model directly

```python
from fireflyframework_agentic.workflows import price_model
usd = price_model("anthropic:claude-haiku-4-5", input_tokens=1000, output_tokens=500)
```

---

## Verify combinators

Built on the primitives, these encode the "fan-out → reduce → decide" patterns
that make multi-agent output trustworthy:

```python
from fireflyframework_agentic.workflows import adversarial_verify, judge_panel, loop_until_dry

# Spawn N skeptics prompted to REFUTE; survives only if fewer than a majority refute.
ok = await adversarial_verify("claim: X causes Y", model="openai:gpt-4o-mini", n=3)

# A panel of DIFFERENT models votes; returns a structured Verdict.
verdict = await judge_panel("X causes Y", judges=["openai:gpt-4o-mini", "anthropic:claude-haiku-4-5"])
verdict.survived, verdict.support, verdict.votes   # bool, fraction, ((model, yes), ...)

# Keep producing until K consecutive rounds surface nothing new (catches the tail).
items = await loop_until_dry(produce_batch, dry_rounds=2, max_rounds=8, key=lambda x: x.id)
```

A heterogeneous-model panel (`judge_panel`) is a stronger signal than asking one
model repeatedly, and its `Verdict` doubles as a confidence oracle for `cascade()`.

---

## Sub-workflows

Compose workflows by running one inline as a step of another with `subworkflow`.
The child inherits the parent's **budget, concurrency gate, journal and runner** —
its `agent()` calls count against the same budget and resume from the same journal
(one deterministic sequence stream across the whole nested run):

```python
from fireflyframework_agentic.workflows import workflow, agent, subworkflow

@workflow(name="summarize")
async def summarize(args, ctx):
    return await agent(f"summarize: {args}")

@workflow(name="report")
async def report(args, ctx):
    bullets = await subworkflow("summarize", args)   # by name, or pass the Workflow object
    return await agent(f"turn into a report: {bullets}")
```

To run a workflow in *isolation* (its own fresh budget), call `other_wf.run(...)`
directly instead.

---

## Human-in-the-loop

`human(prompt)` pauses a run for external input. It raises `WorkflowInterrupt`;
you collect the answer, `provide()` it, and re-run with the **same journal** to
resume past the pause — the answer is journaled, so resume is deterministic:

```python
from fireflyframework_agentic.workflows import workflow, agent, human, Journal, WorkflowInterrupt

@workflow(name="triage")
async def triage(args, ctx):
    draft = await agent(f"draft a reply to: {args}")
    decision = await human(f"Approve this reply?\n\n{draft}")
    if decision.lower().startswith("y"):
        return draft
    return await agent(f"revise per feedback '{decision}': {draft}")

journal = Journal()
try:
    result = await triage.run(ticket, journal=journal)
except WorkflowInterrupt as it:
    it.provide(input(it.prompt))                         # a human reviews and answers
    result = await triage.run(ticket, journal=journal)   # resumes past human()
```

Pair `human()` with a `JournalBackend` for durable approvals that survive a
process restart.

---

## Telemetry

Pass `events=callable` to a run to receive structured events:
`workflow.start` / `workflow.end` (with `agents`, `tokens`, `cost_usd`),
`phase.start` / `phase.end`, `agent.start` / `agent.end` (with `label`, `phase`,
`seq`, `tokens`, `cost_usd`; streamed calls also carry `stream: True`),
`route.select` / `route.escalate`, `cascade.tier`,
`subworkflow.start` / `subworkflow.end`, `human.pause`, and `log`. Wire this into
the [observability](observability.md) layer for live per-phase token/cost/agent/time
counters.

---

## API reference

| Symbol | Purpose |
|---|---|
| `workflow(name=None, *, args_schema=None, description="", register=True)` | Decorator → a registered, runnable `Workflow`. |
| `Workflow.run(args, *, budget, runner, journal, events, run_id)` | Execute; returns the body's return value. |
| `run_workflow(name, args, **opts)` | Look up a registered workflow by name and run it. |
| `subworkflow(name_or_wf, args)` | Run another workflow inline, inheriting the parent's budget/journal/runner. |
| `agent` / `parallel` / `pipeline` / `phase` / `log` | The DSL primitives. |
| `stream(prompt, ...)` | Async context manager → a `StreamHandle` (`.text()` deltas, `.output`); streams one sub-agent. |
| `StreamHandle` / `StreamingAgentRunner` | The streaming result handle and the runner protocol a runner implements to support `stream`. |
| `human(prompt)` | Pause for external input (raises `WorkflowInterrupt`; resume via the same journal). |
| `map_agents(items, fn, *, strict=False)` | Run `fn(item)` per item concurrently — sugar over `parallel` (no late-binding lambda). |
| `WorkflowBudget` | Concurrency / agent-count / token / **USD cost** / **wall-clock** ceilings. |
| `Journal` / `JournalBackend` / `FileJournalBackend` | Sequence-keyed resume cache; attach a backend for durable, crash-resilient resume. |
| `AgentRunner` / `AgentCall` | The runner seam (`AgentCall` carries `output`, `tokens`, `cost_usd`). |
| `FireflyAgentRunner` | **Default** runner: each call runs through a `FireflyAgent` (full middleware/observability/guards/retry/global-cost/fallback). Pair with `agent(..., using=)` for multi-model sub-agents. |
| `DefaultAgentRunner` | Lightweight alternative: each call is a bare `pydantic_ai.Agent`. Pass it explicitly for the zero-coupling path. |
| `SmartRoutingRunner` / `ComplexityHeuristicStrategy` / `CostFloorStrategy` / `ModelSelectionStrategy` | Cheapest-capable model per call (with fallback). |
| `cascade` / `CascadeResult` | Cheap-first, escalate on low confidence. |
| `price_model(model, *, input_tokens, output_tokens)` | USD price for a model at a token shape. |
| `adversarial_verify` / `judge_panel` / `Verdict` / `loop_until_dry` | Quality combinators. |
| `workflow_registry` | The global `WorkflowRegistry` singleton. |
| `current_workflow()` | The active `WorkflowContext` (raises outside a run). |

Exceptions live in `fireflyframework_agentic.exceptions`: `WorkflowError` (base),
`WorkflowNotFoundError`, `WorkflowBudgetError`, `WorkflowContextError`, and
`WorkflowInterrupt` (the human-in-the-loop pause signal).
