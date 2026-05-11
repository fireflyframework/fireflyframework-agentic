# Rubric — Codegen (`codegen`)

The codegen agent minimises the gap between `architecture.yaml` and a
repository whose CI is green and whose code covers all SPEC criteria.

## Hard criteria (must pass)

- [ ] **Tests pass**: the PR's CI workflow exits 0 on the generated
  repo's own test suite.
- [ ] **Coverage**: line coverage ≥ 80 % (or the threshold set in
  `architecture.yaml.quality.coverage_threshold`).
- [ ] **All criteria addressed**: every Acceptance Criterion from
  `spec.yaml` has at least one test that would fail if the criterion
  were violated.
- [ ] **No secrets**: no API keys, tokens, or credentials appear in any
  committed file (checked by `guardian` rubric, but codegen must not
  rely on guardian to catch this).
- [ ] **Style clean**: `ruff check` and `mypy --strict` pass with zero
  errors on the generated code.

## Soft criteria

- **PR description**: PR body includes a summary of what was generated,
  which archetype was used, and the estimated LLM cost.
- **Minimal diff**: the PR touches only files required by the
  architecture; no unrelated changes.
- **Idiomatic**: generated code follows conventions in
  `knowledge_base/skills/` for the target stack.

## Reflexion loop

Codegen uses `ReflexionPattern` internally:
1. **Generate** — scaffold + write modules per architecture.
2. **Critique** — re-read generated files against this rubric.
3. **Improve** — patch gaps identified in critique.

Max 2 internal critique rounds. After that, the PR is opened regardless
and the QA loop handles residual failures.

## Output schema

```
$GITHUB_OUTPUT:
  pr_number   — integer
  branch_name — string
  cost_usd    — float
```
