# Spec 1 — Factory Agent Action Runtime

**Date:** 2026-05-04
**Status:** Draft
**Owner:** Agentic Factory MVP1
**Depends on:** none
**Required by:** Spec 3 (Specialized agents), Spec 4 (Workflows)

---

## Context

The agentic factory MVP1 runs each specialized SDLC agent (product_owner, architect, codegen, qa) as a reusable GitHub Action. Without a shared runtime, every agent action would re-implement the same boilerplate: parse `INPUT_*` env vars, instantiate a `FireflyAgent` from the registry, wire the embedder/vector store, run the agent, write outputs to `$GITHUB_OUTPUT`, upload artifacts, propagate trace context.

This spec defines a single `action_runtime` module that does this once, plus a base Docker image that all agent actions extend. The four agent actions (Spec 3) become trivial: an `action.yml` declaring inputs/outputs, a 5-line Dockerfile, and a CMD that names the agent.

The runtime is also the substrate for MVP2 Spec 6 (programmatic pipeline) — the same entrypoint can be invoked from a `PipelineEngine` step instead of a GitHub runner without code changes.

## Non-goals

- Agent implementations themselves — Spec 3.
- Knowledge base indexing — Spec 2.
- Workflow orchestration — Spec 4.
- Artifact retention policy beyond the GitHub default (90 days).
- Streaming intermediate output to `$GITHUB_STEP_SUMMARY` (later improvement).

## Module layout

```
src/fireflyframework_agentic/factory/
├── __init__.py
└── action_runtime/
    ├── __init__.py        # public surface: run_agent(name, inputs) -> outputs
    ├── __main__.py        # python -m fireflyframework_agentic.factory.action_runtime
    ├── entrypoint.py      # CLI parser, env-var ingest, dispatch to agent runner
    ├── io_models.py       # Pydantic schemas: AgentInput, AgentOutput, IntentInput, PRDOutput, ADROutput, PRRef, QAReport
    ├── artifact.py        # upload/download via $RUNNER_TEMP, declares artifact names
    ├── feedback.py        # loads previous QAReport (when iteration > 1) and produces FeedbackContext
    └── github_outputs.py  # writes typed values to $GITHUB_OUTPUT (escaping multiline)
```

Public API (`from fireflyframework_agentic.factory.action_runtime import run_agent`):

```python
async def run_agent(name: str, inputs: AgentInput) -> AgentOutput: ...
```

`name` is one of `product_owner | architect | codegen | qa` — looked up via `AgentRegistry`. The runtime is agent-agnostic: adding a new agent in MVP2 (e.g. `guardian`) requires only registering it and giving it an `action.yml`, no runtime change.

## Input contract

The runtime reads two sources:

1. **Environment variables** (set by GitHub for Docker actions):
   - `INPUT_<NAME>` — one per declared input in `action.yml`. Names normalized to lowercase Pydantic fields.
   - `GITHUB_OUTPUT`, `GITHUB_ENV`, `GITHUB_WORKSPACE`, `RUNNER_TEMP`, `GITHUB_REPOSITORY`, `GITHUB_RUN_ID`, `GITHUB_SHA` — standard GitHub-provided.
   - `ANTHROPIC_API_KEY` (or other provider key, set per `FACTORY_LLM_PROVIDER`).
   - `FACTORY_VECTOR_BACKEND` (default `sqlite-vec`), `FACTORY_KNOWLEDGE_BASE_INDEX` (path to the artifact downloaded by the workflow before invoking the agent).

2. **Artifacts on disk** at `$RUNNER_TEMP/factory/`:
   - `prd.md`, `spec.yaml` — produced by `product_owner`, consumed by `architect` and downstream.
   - `adr.md`, `architecture.yaml` — produced by `architect`, consumed by `codegen`.
   - `qa_report.json` — produced by `qa`, consumed by next `codegen` iteration via `feedback.py`.

Each agent declares its expected artifact set in its `AgentInput` Pydantic model. Missing required artifacts raise a typed `MissingArtifactError` that the entrypoint surfaces as a non-zero exit and a clear `::error::` annotation.

## Output contract

Two channels:

- **`$GITHUB_OUTPUT`** — short, typed, machine-readable. Examples: `pr_number=42`, `qa_passed=true`, `iteration=2`, `cost_usd=0.43`. Multi-line values use the `<<EOF` heredoc form per GitHub docs. Implemented in `github_outputs.py`.
- **Artifact files** at `$RUNNER_TEMP/factory/` — large or structured outputs. The runtime auto-uploads the directory at the end via `actions/upload-artifact` (called from the workflow, not from inside the container — the runtime just writes files; the workflow uploads them).

Naming convention for artifacts: `factory-<stage>-<run_id>` (e.g. `factory-define-1234567`, `factory-design-1234567`). Stage names match the workflow names defined in Spec 4.

## Reasoning, observability, cost

The runtime wires four cross-cutting concerns once for every agent:

- **Tracing.** `FireflyTracer` with W3C trace context extracted from `INPUT_TRACEPARENT` (set by the parent workflow). Every agent run is one root span; sub-spans cover tool calls.
- **Usage.** `UsageTracker` records token counts; final summary written to `$GITHUB_OUTPUT` as `cost_usd`, `tokens_in`, `tokens_out`, plus to `$GITHUB_STEP_SUMMARY` as a markdown table.
- **Prompt caching.** `PromptCacheMiddleware` enabled by default for Anthropic models — the system prompt + knowledge-base context are cacheable across iterations of the same intent.
- **Output guards.** `default_output_guard` runs over every agent's final string output to scrub credentials before they end up in PR comments or logs.

## Base Docker image

`.github/actions/_base/Dockerfile`:

```dockerfile
FROM python:3.12-slim AS base
RUN useradd -u 1001 -m runner
WORKDIR /home/runner
COPY pyproject.toml uv.lock /home/runner/
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache "fireflyframework-agentic[factory]"
USER runner
ENTRYPOINT ["python", "-m", "fireflyframework_agentic.factory.action_runtime"]
```

Built once per agentic-library release and pushed to `ghcr.io/fireflyframework/factory-base:<calver-tag>`. Each agent action's Dockerfile is then:

```dockerfile
FROM ghcr.io/fireflyframework/factory-base:2026.05.0
CMD ["--agent", "codegen"]
```

The `[factory]` optional dependency in `pyproject.toml` adds: `httpx` (already in core, will be a no-op), `sqlite-vec`, `pyyaml`, `gh` (system requirement, installed via apt in base image).

## `act` test harness

A reusable test fixture under `tests/factory/action_runtime/` runs each agent action via `nektos/act` against a fixture intent, fixture knowledge-base index, and a stubbed LLM (using Pydantic-AI's `TestModel`). Asserts:

- Exit code 0 on the happy path.
- Required artifact files exist.
- `$GITHUB_OUTPUT` parses cleanly.
- Cost output is non-negative and below a per-test budget.
- `MissingArtifactError` produces exit code 78 (skip) and a clear annotation.

## Open questions

- Should we mirror the base image to multiple registries (Docker Hub, GHCR) to avoid GHCR pull rate limits in customer runners? **Decision deferred to Spec 4** when we know how customer repos consume these actions.
- Do we tag base images by CalVer (`2026.05.0`) or by the git SHA of the agentic library? Spec proposes CalVer for stability; the build job can tag both.

## Verification

- A `workflow_dispatch` of a minimal end-to-end test workflow (fixture intent → product_owner action → assert PRD artifact exists) succeeds against this runtime alone, before Spec 3 agents are wired.
- `act -j test-action-runtime` passes locally with a stubbed LLM.
- Importing `fireflyframework_agentic.factory.action_runtime` adds no measurable startup cost when the factory extra is not installed (lazy imports for `sqlite-vec`, `gh`).
