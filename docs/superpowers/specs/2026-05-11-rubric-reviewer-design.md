# RubricReviewer — Design Spec

**Date:** 11-5-2026
**Issue:** fireflyframework/fireflyframework-agentic#121
**Scope:** Core rubric-based semantic reviewer. No RAG or pipeline integration.

---

## Problem

`OutputReviewer` validates structural conformance (schema, field rules). It cannot evaluate whether an output is semantically correct, well-reasoned, or citation-backed. The grader also runs in the same agent context, so it can rationalise the generator's own reasoning.

`QoSGuard` provides heuristic quality checks (confidence, consistency, grounding) but has no feedback loop and no LLM judge.

There is no mechanism to define semantic acceptance criteria as a rubric and iterate until the output satisfies them.

---

## Design

### Principle

The rubric is the loss function. The difference between the rubric and the actual output state is what gets minimised across iterations. The grader runs in an isolated context window — separate `FireflyAgent`, no access to the generator's reasoning — so it evaluates the output as a user would.

### What changes

| File | Change |
|---|---|
| `validation/reviewer.py` | Add `RubricReviewer` class and `_parse_grader_response()` helper |
| `validation/__init__.py` | Export `RubricReviewer` |
| `tests/validation/test_reviewer.py` | Unit tests with mocked grader |

Zero new files. All result models (`ReviewResult`, `RetryAttempt`, `ValidationReport`, `ValidationRuleResult`) and `OutputReviewError` are reused without modification.

---

## `RubricReviewer`

Lives in `validation/reviewer.py` alongside `OutputReviewer`.

```python
class RubricReviewer:
    def __init__(
        self,
        rubric: list[str],
        *,
        grader: AgentLike | None = None,
        max_iterations: int = 3,
        revision_prompt: str | None = None,
    ) -> None: ...

    @classmethod
    def from_rubric_file(cls, path: str | Path, **kwargs) -> "RubricReviewer": ...

    async def review(
        self,
        agent: AgentLike,
        prompt: str | Sequence[Any],
        **kwargs,
    ) -> ReviewResult: ...
```

**`rubric`** — ordered list of natural-language pass/fail statements. Must be non-empty; raises `ValueError` at construction if empty.

**`grader`** — an `AgentLike` that evaluates the output. When `None`, a default `FireflyAgent` is created using the same model as the generator (read from its `model` attribute if available, otherwise falls back to the framework default) with a system prompt focused on rubric evaluation. The grader must be a separate instance from the generator to preserve context isolation.

**`revision_prompt`** — custom template for the revision prompt sent to the generator on each failed iteration. Must contain `{gaps}` and `{original_prompt}` placeholders. When `None`, the default template is used.

**`max_iterations`** — maximum number of generation attempts (default 3, matching Anthropic's Managed Agents default). On exhaustion raises `OutputReviewError`.

**`from_rubric_file(path)`** — parses a Markdown file. H1 heading is ignored. Bullet list items (`- ` or `* `) become rubric criteria. Raises `ValueError` if no criteria are found.

---

## Loop

```
for iteration in 1..max_iterations:
    output = await agent.run(prompt)
    report = await _evaluate_rubric(output, grader, rubric)
    if report.valid:
        return ReviewResult(output, attempts=iteration, validation_report=report)
    prompt = _build_revision_prompt(original_prompt, report.errors)
raise OutputReviewError(...)
```

`_evaluate_rubric()` returns a `ValidationReport` where each `ValidationRuleResult` corresponds to one rubric criterion:
- `rule_name`: the criterion text (or `criterion_{n}`)
- `passed`: `True` if MET, `False` if NOT MET
- `message`: the gap explanation from the grader

This maps directly to `ReviewResult.validation_report` (already `ValidationReport | None`) without changing the result model.

---

## Grader prompt contract

```
Rubric:
1. <criterion_1>
2. <criterion_2>
...

Output to evaluate:
<output>

For each criterion, state MET or NOT MET followed by a colon and brief explanation if NOT MET.
End your response with either SATISFIED or NEEDS_REVISION on its own line.

Example:
MET: 1
NOT MET: 2 — no inline citation found for the claim about revenue growth
SATISFIED
```

**Malformed response handling:** if the grader response contains neither `SATISFIED` nor `NEEDS_REVISION`, treat as `NEEDS_REVISION` with a single generic gap (`"grader response could not be parsed"`). The loop continues rather than raising.

---

## Revision prompt

```
Your previous response did not satisfy the following criteria:
{gaps as bullet list}

Original request:
{original_prompt}

Please revise your response addressing these specific gaps.
```

Analogous to `OutputReviewer._DEFAULT_RETRY_TEMPLATE`. Configurable via optional `revision_prompt` parameter on `RubricReviewer.__init__`.

---

## Result

`ReviewResult` is returned unchanged:

```python
ReviewResult(
    output=final_output,
    attempts=n,                        # 1 if first try satisfied
    validation_report=ValidationReport(...),  # grader's final report
    retry_history=[RetryAttempt(...)], # one entry per failed iteration
)
```

`satisfied` is derivable from `result.validation_report.valid`. No new field needed.

---

## Testing

**Unit tests** — grader mocked, no LLM calls:

| Scenario | Expected |
|---|---|
| Grader returns `SATISFIED` on first call | `attempts == 1`, `validation_report.valid == True` |
| Grader returns `NEEDS_REVISION` then `SATISFIED` | `attempts == 2`, `retry_history` has one entry |
| Grader returns `NEEDS_REVISION` for all iterations | raises `OutputReviewError` |
| `rubric=[]` | raises `ValueError` at construction |
| Grader returns malformed response | treated as `NEEDS_REVISION`, loop continues |
| `from_rubric_file()` with valid `.md` | criteria parsed correctly |
| `from_rubric_file()` with no bullet list | raises `ValueError` |

**Integration tests** — marked `@pytest.mark.integration`, not run in CI by default:
- `RubricReviewer` with a real `FireflyAgent` generator + default grader + 3-criterion rubric → `ReviewResult` has correct shape and `satisfied` reflects actual grader decision.

---

## Out of scope

- RAG integration (`CorpusAgent`, `answer_outcome_reviewer`).
- Pipeline integration (`ReasoningStep`, `Reviewer` protocol).
- `CompositeReviewer` combining `OutputReviewer` + `RubricReviewer`.
- Observability spans per iteration.

These are natural follow-ons, each in a separate issue.
