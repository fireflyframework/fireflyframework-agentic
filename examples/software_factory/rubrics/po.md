# Rubric — Product Owner (`po`)

The PO agent minimises the gap between the intent received and a PRD that
downstream agents can act on without ambiguity. Every criterion below is a
dimension of that gap. The agent iterates until all hard criteria pass.

## Hard criteria (must pass — loss = 0 required)

- [ ] **Completeness**: PRD contains all six sections: Context, Objectives,
  Acceptance Criteria, Out of Scope, Risks, Assumptions.
- [ ] **Testability**: every Acceptance Criterion is phrased so that a QA
  agent can write a deterministic check (observable behaviour, not intent).
- [ ] **Scope boundary**: Out of Scope explicitly names at least one thing
  that is *not* being built, to prevent scope creep in downstream agents.
- [ ] **Assumption explicitness**: every `[ASSUMPTION]` in the PRD has a
  rationale and a stated risk if wrong.
- [ ] **No open questions**: the PRD must not contain unresolved "TBD"
  markers. Unresolvable unknowns become Risks with a mitigation.

## Soft criteria (graded — lower loss is better)

- **Concision**: PRD is ≤ 800 words. Verbose PRDs lead to architect drift.
- **Metric presence**: at least one Acceptance Criterion has a measurable
  threshold (latency < X ms, coverage ≥ Y %, cost < Z USD).
- **Dependency identification**: external systems the app depends on are
  named in Context or Risks.

## Output schema

```
PRD.md   — human-readable markdown
spec.yaml — machine-readable acceptance criteria for the architect
```

## Loss function (self-evaluation prompt)

After generating PRD.md and spec.yaml, the agent re-reads both and answers:

1. Is every AC testable by a deterministic check? (yes/no per AC)
2. Is there at least one measurable threshold? (yes/no)
3. Are there any TBD markers? (list them or "none")
4. Does Out of Scope name ≥ 1 explicit exclusion? (yes/no)

If any answer indicates a gap, the agent revises and re-evaluates. Max 2 revision rounds.
