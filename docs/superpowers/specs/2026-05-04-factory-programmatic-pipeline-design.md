# Spec 6 — Factory Programmatic Pipeline

**Date:** 2026-05-04
**Status:** Draft — MVP2 backlog (not approved)
**Owner:** Agentic Factory MVP2
**Depends on:** Specs 1–4 (MVP1 must be implemented and stable first)
**Required by:** Spec 7 (CLI + REST), any consumer that wants the factory inside their own service

---

## Context

In MVP1 the factory's only entry point is GitHub: workflows chain agents via `workflow_run` and the runtime is an Action. That is the right substrate when GitHub is the system of record, but it is the wrong substrate when:

- A consumer wants to drive the factory from their own backend (CEREBRO, Firefly tooling, customer SaaS).
- A developer wants to iterate locally on a single agent without push-and-wait latency.
- The factory needs to participate in a longer pipeline composed by the host application (e.g., factory step → human approval → factory step).

This spec wires the same four agents into the existing `PipelineEngine` (`fireflyframework_agentic.pipeline`) so the entire SDLC loop can run as a single in-process DAG without GitHub.

## Non-goals

- A new pipeline engine. Reuse `PipelineEngine`, `PipelineBuilder`, `PipelineContext`, and the existing `AgentStep` / `BranchStep`.
- A new transport. Spec 7 layers REST/SSE on top.
- Persistent state across runs. The DAG is in-memory; SaaS persistence is Spec 13.
- Cross-process orchestration. One pipeline run = one Python process.

## Sketch

```python
from fireflyframework_agentic.pipeline import PipelineBuilder
from fireflyframework_agentic.factory.pipeline import build_factory_pipeline

pipeline = build_factory_pipeline(max_iterations=3)
result = await pipeline.run(intent="Generate a corpus-search service")
# result.context["pull_request"], result.context["qa_report"], result.context["release_tag"]
```

Internally:

1. `AgentStep("product_owner")` → writes `prd` and `spec` keys into `PipelineContext`.
2. `AgentStep("architect")` → writes `adr`, `architecture`.
3. `AgentStep("codegen")` → writes `pull_request`, `branch`.
4. `CallableStep("ci")` → optionally invokes a configured CI runner (defaults to a no-op for "headless" runs that don't push).
5. `AgentStep("qa")` → writes `qa_report`.
6. `BranchStep` on `qa_report.passed` → tag step or loop back to step 3 with `feedback` in context, bounded by `max_iterations`.

The same agent code from Spec 3 runs unchanged. The only new code is `factory/pipeline/builder.py` (DAG construction) and `factory/pipeline/__init__.py`.

## Verification

- A unit test runs `build_factory_pipeline()` with stubbed agents and asserts the DAG topology matches the diagram (Define → Design → Generate → CI → QA → Branch).
- An integration test runs the same pipeline with `pydantic_ai`'s `TestModel`-backed agents end-to-end and asserts the QA loop fires once on a seeded failure.
- The Action runtime (Spec 1) is refactored to delegate to `build_factory_pipeline().run(...)` so MVP1 and MVP2 share the same orchestration code (no two paths to maintain).

## Open questions

- Where does file-system state live for headless runs? `tempfile.mkdtemp()` per run vs. a configurable `workspace_dir`? Spec proposes the latter so a host application can inspect intermediate artifacts.
- The CI step is the awkward one — without GitHub, do we shell out to `pytest` directly, or require the consumer to provide a `CIRunner` Protocol? Spec proposes the Protocol; default implementation runs `pytest` if a `tests/` dir exists.
