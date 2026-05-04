# Spec 3 — Factory Specialized Agents

**Date:** 2026-05-04
**Status:** Draft
**Owner:** Agentic Factory MVP1
**Depends on:** Spec 1 (action runtime), Spec 2 (knowledge base + tools)
**Required by:** Spec 4 (workflows orchestrate these agents)

---

## Context

The factory MVP1 ships four specialized SDLC agents that, together, take a natural-language intent and produce a Pull Request whose CI is green: `product_owner`, `architect`, `codegen`, `qa`. Each is a `FireflyAgent` instance with an explicit model, reasoning pattern, system prompt, and tool set. Each is wrapped in a Docker GitHub Action via the runtime defined in Spec 1, and consumes the knowledge surface from Spec 2.

The architecture document (§5) lists seven Phase-1 agents — `guardian`, `builder`, `deployer` are deferred to MVP2. In MVP1, codegen subsumes guardian via its `ReflexionPattern` review/critique loop, and build + deploy are absent because the factory's deliverable in MVP1 is a green PR, not a deployed system.

This spec defines the four agents themselves: their inputs, outputs, prompts, tools, models, and the contracts they must honor for the workflows in Spec 4 to chain them deterministically.

## Non-goals

- Action wrapping mechanics — Spec 1.
- Knowledge-base content authoring — Spec 2.
- Workflow orchestration / QA feedback loop — Spec 4.
- Multi-stack support (Java, frontend) — MVP2 Spec 12.
- Guardian as a separate agent — MVP2 Spec 9.

## Module layout

```
src/fireflyframework_agentic/factory/agents/
├── __init__.py            # registers all four agents in AgentRegistry
├── product_owner.py
├── architect.py
├── codegen.py
├── qa.py
├── models.py              # shared Pydantic types: Intent, PRD, ADR, PullRequest, QAReport, FeedbackContext
└── prompts/               # loaded by Spec 2 indexer; symlinks to knowledge_base/prompts/
```

Each agent module exposes a single async factory function `build_<name>_agent() -> FireflyAgent` that the action runtime (Spec 1) calls when invoked with `--agent <name>`. The functions are lazy — they read prompt content and tool bindings at call time, not at import.

## The four agents

### `product_owner`

**Goal:** turn a free-text `Intent` into a typed `PRD` and `SPEC.yaml`.

**Model:** `anthropic:claude-sonnet-latest`. Sonnet is sufficient for elicitation and structured-document synthesis; Opus is overkill.

**Reasoning:** `GoalDecompositionPattern`. Breaks the intent into objectives, acceptance criteria, success metrics, risks, and dependencies. When an objective lacks information, the agent emits a marked `[ASSUMPTION]` block in the PRD rather than blocking — downstream agents and the qa loop can re-evaluate.

**Tools:**
- `prd_lookup` — find similar past PRDs to copy structure from.
- `knowledge_search` — pull domain or compliance context if the intent mentions a regulated area.

**Inputs:** `Intent` (free text + optional repo target + optional regulatory tags).
**Outputs:** `PRD.md` (human-readable, sections: Context / Objectives / Acceptance Criteria / Out of Scope / Risks / Assumptions) + `SPEC.yaml` (machine-readable schema for the architect).

**Cost target:** ≤ $0.05 per run on a typical 200-word intent.

### `architect`

**Goal:** produce an `ADR` and `architecture.yaml` from a `PRD` + `SPEC.yaml`.

**Model:** `anthropic:claude-opus-latest`. Architectural decisions are the highest-leverage step — Opus's better reasoning is worth the cost premium.

**Reasoning:** `ChainOfThoughtPattern`. The pattern's explicit step-by-step trace becomes the body of the ADR — every "Decision" section in the rendered ADR maps to one CoT step.

**Tools:**
- `archetype_lookup` — pick the matching project archetype (returns `name` + `template_path`).
- `knowledge_search` — pull conventions, prior ADRs.

**Inputs:** `PRD.md` + `SPEC.yaml` from `$RUNNER_TEMP/factory/`.
**Outputs:** `ADR.md` (sections: Status / Context / Decision Drivers / Considered Options / Decision / Consequences / Compliance) + `architecture.yaml` (lists modules, contracts, dependencies, the chosen archetype path, target stack — pyfly only in MVP1).

**Cost target:** ≤ $0.30 per run.

### `codegen`

**Goal:** produce a working repository from `ADR` + `architecture.yaml` + (optionally) `FeedbackContext` from a prior failed QA, and open a Pull Request.

**Model:** `anthropic:claude-sonnet-latest`.

**Reasoning:** `ReflexionPattern`. Three phases per run:

1. **Generate.** Scaffold the project from the archetype's `template/` directory, then write each module per the architecture.
2. **Critique.** Re-read the generated files. Check against `pyfly-conventions`, `testing-conventions`, `github-workflow-conventions` retrieved via `skill_lookup`. Emit a critique with file-level findings.
3. **Improve.** Apply patches addressing the critique. Stop when the critique is empty or after 2 critique rounds.

This loop is what subsumes a separate `guardian` agent in MVP1. It is internal to a single agent run; it does not trigger a new workflow.

**Tools:**
- `skill_lookup` — load conventions for the target stack (pyfly).
- File-system tools (write within `$GITHUB_WORKSPACE` only — guarded by `SandboxGuard`).
- `git` (commit, push branch).
- `gh` (open PR, label it `factory:generated`, link the run).

**Inputs:** `ADR.md` + `architecture.yaml` + optional `FeedbackContext` (set when re-running due to QA failure — see Spec 4 loop).
**Outputs:** `pr_number` and `branch_name` to `$GITHUB_OUTPUT`. Code is in the PR; no artifact.

**Cost target:** ≤ $1.50 per run for a small service. Reflexion can blow this up; if cost exceeds the per-run budget the agent stops and surfaces the partial result.

**Iteration counter.** When `FeedbackContext.iteration > 1`, the system prompt prepends the prior `QAReport.failures` and instructs the agent to address them specifically. The Reflexion loop's own critique step is unchanged.

### `qa`

**Goal:** verify the PR's runnable behavior against the PRD's acceptance criteria. Produce `QAReport.json` and a PR comment. Decide pass / fail / request-iteration.

**Model:** `anthropic:claude-sonnet-latest`.

**Reasoning:** `ReflexionPattern` over the test results — generate a verdict, critique it for false positives/negatives, finalize.

**Tools:**
- `gh` (read workflow status of the PR's CI; read PR diff).
- `parse_test_results` — `BaseTool` that ingests JUnit XML / pytest JSON and returns a structured `TestSummary`.
- `diagnose_failure` — pure-Python callable (no LLM) that takes failed-test outputs and produces a `FailureClassification` (compile error / test assertion / network / timeout / unknown). Heuristic in MVP1; the LLM-backed `qa_diagnoser` is MVP2 (Spec 11).
- `knowledge_search` — for context on edge cases.

**Inputs:** PR number, PRD acceptance criteria (loaded from artifact), CI workflow run id of the generated repo's own tests.
**Outputs:**
- `QAReport.json` artifact:
  ```json
  {
    "passed": false,
    "iteration": 1,
    "summary": "...",
    "failures": [{"test_id": "...", "classification": "...", "evidence": "...", "suggested_fix": "..."}],
    "passed_criteria": ["..."],
    "missed_criteria": ["..."],
    "cost_usd": 0.42
  }
  ```
- `qa_passed=true|false` to `$GITHUB_OUTPUT`.
- A PR comment summarizing the report.

**Cost target:** ≤ $0.20 per run.

## Shared types (`models.py`)

```python
class Intent(BaseModel):
    text: str
    target_repo: str | None = None
    regulatory_tags: list[str] = []

class PRD(BaseModel):
    title: str
    objectives: list[Objective]
    acceptance_criteria: list[AcceptanceCriterion]
    out_of_scope: list[str]
    risks: list[Risk]
    assumptions: list[str]

class ADR(BaseModel):
    title: str
    status: Literal["Proposed", "Accepted"]
    context: str
    drivers: list[str]
    options: list[Option]
    decision: str
    consequences: list[Consequence]
    archetype: str           # name from knowledge_base/archetypes/
    stack: Literal["pyfly"]  # widened in MVP2

class PullRequest(BaseModel):
    number: int
    branch: str
    head_sha: str

class FailureClassification(str, Enum):
    COMPILE_ERROR = "compile_error"
    TEST_ASSERTION = "test_assertion"
    NETWORK = "network"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"

class QAReport(BaseModel):
    passed: bool
    iteration: int
    summary: str
    failures: list[Failure]
    passed_criteria: list[str]
    missed_criteria: list[str]
    cost_usd: float

class FeedbackContext(BaseModel):
    iteration: int
    previous_report: QAReport
```

## Cross-cutting concerns

- All four agents register a `PromptCacheMiddleware` so the system prompt + retrieved skills are cached across iterations of the same intent.
- `OutputGuard` runs over every agent's final output before it lands in artifacts or PR comments.
- `UsageTracker` records costs per agent; the action runtime (Spec 1) writes the total to `$GITHUB_OUTPUT` as `cost_usd`.
- Tracing: every agent run is one root span. Tool calls are sub-spans. The trace context is propagated by Spec 1.

## Verification

- `tests/factory/agents/` exercises each agent against a fixture intent using Pydantic-AI's `TestModel`. Assertions: output schema validates, required artifact files written, `cost_usd` < per-test budget, tool call counts within expected bounds.
- An end-to-end test (`tests/factory/test_define_to_design.py`) chains `product_owner` → `architect` and asserts the architect's `architecture.yaml` references a real archetype.
- A QA happy path (`tests/factory/test_qa_passes.py`) runs `qa` against a fixture PR with all-green tests and asserts `passed=true`.
- A QA failure path (`tests/factory/test_qa_fails.py`) runs `qa` against a fixture PR with one failing test and asserts `passed=false` and `failures[0].classification` is set.

## Open questions

- Architect on Opus is expensive. For very small intents (e.g., the corpus-search demo) Sonnet may be enough. Should we add a `ComplexityClassifier` that downgrades model when the PRD has < N acceptance criteria? **Spec proposes deferring** — a single per-agent default keeps MVP1 simple.
- Should `qa` re-run the generated repo's tests itself, or trust the workflow's own CI run? Spec proposes trusting CI — Spec 4's `factory-qa.yml` runs CI before invoking the agent.
- File-write guard scope: does codegen ever need to write outside `$GITHUB_WORKSPACE`? Spec proposes no — `SandboxGuard` is hard-coded to that path.
