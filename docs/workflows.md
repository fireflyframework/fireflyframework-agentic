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
| `agent` | `await agent(prompt, *, label, model, output_type, instructions, deps)` | Run one isolated sub-agent; returns its `output` (a `str` or a validated `output_type`). Honours the budget, the concurrency gate, and the resume journal. |
| `parallel` | `await parallel(thunks)` | **Barrier.** Run zero-arg async thunks concurrently; a thunk that raises resolves to `None` (the call never propagates). Returns a list aligned to `thunks`. |
| `pipeline` | `await pipeline(items, *stages)` | **No inter-stage barrier.** Each item flows through every stage independently (item A can be in stage 3 while B is in stage 1). Each stage receives `(prev, item, index)` — declare only the params you need. A stage that raises drops *that* item to `None`. |
| `phase` | `with phase("title"):` | Group enclosed work for telemetry (`phase.start` / `phase.end` events). |
| `log` | `log("message")` | Emit a narrator line to the run's event handler. |

**Reduce in Python, not with a model.** The strength of the DSL is that the
glue between agent calls — dedup, rank, filter, branch — is ordinary
deterministic Python. Reach for an `agent()` only when you genuinely need a
model.

---

## Budgets

Every run is bounded by a `WorkflowBudget`:

```python
WorkflowBudget(
    max_concurrent_agents=8,   # asyncio.Semaphore; default min(16, cpu - 2)
    max_agents_total=1000,     # hard kill-switch (runaway-loop backstop)
    max_tokens=500_000,        # optional output-token ceiling for the whole run
)
```

Exceeding `max_agents_total` or `max_tokens` raises `WorkflowBudgetError`. Token
accounting is fed by each `AgentRunner` call's reported usage.

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
across processes — e.g. behind a pipeline `Checkpointer`.

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
    async def run(self, prompt, *, model=None, output_type=None,
                  instructions=None, deps=None) -> AgentCall: ...
```

- **`DefaultAgentRunner`** (default) runs each call as a fresh
  `pydantic_ai.Agent` with no shared message history — isolation by construction.
  Pass a per-call `model=` or a runner-wide `default_model=`.
- **Custom runners** make workflows trivially testable: inject a deterministic
  fake that returns canned `AgentCall(output=..., tokens=...)` and no network is
  touched.

```python
await deep_research(args, runner=MyFakeRunner())
```

---

## Verify combinators

Built on the primitives, these encode the "fan-out → reduce → decide" patterns
that make multi-agent output trustworthy:

```python
from fireflyframework_agentic.workflows import adversarial_verify, loop_until_dry

# Spawn N skeptics prompted to REFUTE; survives only if fewer than a majority refute.
ok = await adversarial_verify("claim: X causes Y", model="openai:gpt-4o-mini", n=3)

# Keep producing until K consecutive rounds surface nothing new (catches the tail).
items = await loop_until_dry(produce_batch, dry_rounds=2, max_rounds=8, key=lambda x: x.id)
```

---

## Telemetry

Pass `events=callable` to a run to receive structured events:
`workflow.start` / `workflow.end`, `phase.start` / `phase.end`,
`agent.start` / `agent.end` (with `label`, `phase`, `seq`, `tokens`), and `log`.
Wire this into the [observability](observability.md) layer for live per-phase
token/agent/time counters.

---

## API reference

| Symbol | Purpose |
|---|---|
| `workflow(name=None, *, args_schema=None, description="", register=True)` | Decorator → a registered, runnable `Workflow`. |
| `Workflow.run(args, *, budget, runner, journal, events, run_id)` | Execute; returns the body's return value. |
| `run_workflow(name, args, **opts)` | Look up a registered workflow by name and run it. |
| `agent` / `parallel` / `pipeline` / `phase` / `log` | The DSL primitives. |
| `WorkflowBudget` | Concurrency / agent-count / token ceilings. |
| `Journal` | Sequence-keyed cache for deterministic resume. |
| `AgentRunner` / `DefaultAgentRunner` / `AgentCall` | The runner seam. |
| `adversarial_verify` / `loop_until_dry` | Quality combinators. |
| `workflow_registry` | The global `WorkflowRegistry` singleton. |
| `current_workflow()` | The active `WorkflowContext` (raises outside a run). |

Exceptions live in `fireflyframework_agentic.exceptions`: `WorkflowError` (base),
`WorkflowNotFoundError`, `WorkflowBudgetError`, `WorkflowContextError`.
