# Rubric — QA (`qa`)

The QA agent minimises the gap between the live deployment and the
PRD's acceptance criteria. It is the final arbiter of "done": only
when all hard criteria pass does the factory tag a release.

## Hard criteria (must pass)

- [ ] **All ACs verified**: every Acceptance Criterion in `spec.yaml`
  has an explicit pass/fail verdict in `QAReport.passed_criteria` or
  `QAReport.missed_criteria`.
- [ ] **No missed ACs on pass**: if `QAReport.passed = true`, then
  `QAReport.missed_criteria` must be empty.
- [ ] **Failure classification**: every entry in `QAReport.failures`
  has a non-null `classification` (one of: compile_error,
  test_assertion, network, timeout, unknown).
- [ ] **Structured feedback**: if `passed = false`, each failure entry
  must include a `suggested_fix` so codegen can act without re-reading
  logs.

## Soft criteria

- **Cost within budget**: `QAReport.cost_usd` ≤ $0.20 per run.
- **Coverage reported**: QA surfaces the test coverage percentage
  from the CI run (if available).
- **PR comment**: a human-readable summary is posted as a PR comment
  regardless of pass/fail outcome.

## Iteration policy

If `passed = false` and `iteration < 3`, QA feeds `QAReport` back to
codegen as `FeedbackContext` and re-runs the loop. On the 3rd failure,
QA marks the run as permanently failed and closes the factory run.

## Output schema

```
qa_report.json:
  {
    "passed": false,
    "iteration": 1,
    "summary": "...",
    "failures": [
      {
        "criterion": "...",
        "classification": "test_assertion",
        "evidence": "...",
        "suggested_fix": "..."
      }
    ],
    "passed_criteria": [...],
    "missed_criteria": [...],
    "cost_usd": 0.18
  }
$GITHUB_OUTPUT:
  qa_passed    — true|false
  qa_iteration — integer
```
