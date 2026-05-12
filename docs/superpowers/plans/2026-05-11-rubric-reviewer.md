# RubricReviewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `RubricReviewer` to `validation/reviewer.py` — a semantic loop reviewer that runs a rubric-based LLM grader in an isolated context and iterates until all criteria are satisfied.

**Architecture:** `RubricReviewer` lives alongside `OutputReviewer` in `reviewer.py`. It reuses `ReviewResult`, `RetryAttempt`, `ValidationReport`, `ValidationRuleResult`, and `OutputReviewError` without modification. The grader runs as a separate `AgentLike` (isolated context window); its free-text response is parsed by `_parse_grader_response()` into a `ValidationReport`. The retry loop mirrors `OutputReviewer`'s pattern.

**Tech Stack:** Python 3.13, pydantic v2, pytest-asyncio, existing `fireflyframework_agentic` framework.

---

## File Map

| File | Change |
|---|---|
| `src/fireflyframework_agentic/validation/reviewer.py` | Add `_parse_grader_response()`, `RubricReviewer` |
| `src/fireflyframework_agentic/validation/__init__.py` | Export `RubricReviewer` |
| `tests/data_validation/test_reviewer.py` | Add test functions for `RubricReviewer` and `_parse_grader_response` |

Zero new files.

---

## Task 1: `_parse_grader_response` — test then implement

This is a pure function. Write it and test it first so the loop can be built on a verified foundation.

**Files:**
- Modify: `tests/data_validation/test_reviewer.py`
- Modify: `src/fireflyframework_agentic/validation/reviewer.py`

- [ ] **Step 1: Add failing tests for `_parse_grader_response`**

Append to `tests/data_validation/test_reviewer.py` (after the existing `TestReviewResultModel` class). Add the import at the top of the file alongside the existing reviewer imports:

```python
# add to existing import line:
from fireflyframework_agentic.validation.reviewer import (
    OutputReviewer,
    RetryAttempt,
    ReviewResult,
    RubricReviewer,
    _parse_grader_response,
)
```

Then append these test functions at the bottom of the file:

```python
# ---------------------------------------------------------------------------
# _parse_grader_response
# ---------------------------------------------------------------------------


def test_parse_grader_satisfied():
    rubric = ["Criterion A", "Criterion B"]
    report = _parse_grader_response("MET: 1\nMET: 2\nSATISFIED", rubric)
    assert report.valid is True
    assert report.error_count == 0


def test_parse_grader_needs_revision():
    rubric = ["Every claim cites at least one [chunk_id]."]
    report = _parse_grader_response(
        "NOT MET: 1 — no inline citation found\nNEEDS_REVISION", rubric
    )
    assert report.valid is False
    assert report.error_count == 1
    assert report.errors[0].message == "no inline citation found"
    assert report.errors[0].passed is False


def test_parse_grader_malformed_treated_as_needs_revision():
    rubric = ["Criterion A"]
    report = _parse_grader_response("I have no idea what to say here", rubric)
    assert report.valid is False
    assert report.error_count == 1
    assert "could not be parsed" in report.errors[0].message


def test_parse_grader_field_count_matches_rubric():
    rubric = ["A", "B", "C"]
    report = _parse_grader_response("MET: 1\nMET: 2\nMET: 3\nSATISFIED", rubric)
    assert report.field_count == 3
```

- [ ] **Step 2: Run tests — confirm they fail with ImportError**

```bash
cd /home/u/signature/fireflyframework-agentic && source ~/.venvs/signature/bin/activate && pytest tests/data_validation/test_reviewer.py::test_parse_grader_satisfied -v 2>&1 | tail -15
```

Expected: `ImportError: cannot import name 'RubricReviewer'` or `ImportError: cannot import name '_parse_grader_response'`

- [ ] **Step 3: Implement `_parse_grader_response` in `reviewer.py`**

Add the following after the existing imports and before `class RetryAttempt` in `src/fireflyframework_agentic/validation/reviewer.py`:

```python
from pathlib import Path
```

Then add after the `_DEFAULT_RETRY_TEMPLATE` constant and before `class OutputReviewer`:

```python
# ---------------------------------------------------------------------------
# Grader prompt templates (used by RubricReviewer)
# ---------------------------------------------------------------------------

_GRADER_SYSTEM_PROMPT = (
    "You are a strict evaluator. Your job is to assess whether an output satisfies "
    "a rubric of pass/fail criteria. Be precise and objective. "
    "Never rationalise or give partial credit."
)

_GRADER_PROMPT_TEMPLATE = (
    "Rubric:\n{rubric}\n\n"
    "Output to evaluate:\n{output}\n\n"
    "For each criterion, state MET or NOT MET followed by a colon and brief explanation "
    "if NOT MET. End your response with either SATISFIED or NEEDS_REVISION on its own line.\n\n"
    "Example:\n"
    "MET: 1\n"
    "NOT MET: 2 — no inline citation found\n"
    "SATISFIED"
)

_DEFAULT_REVISION_TEMPLATE = (
    "Your previous response did not satisfy the following criteria:\n{gaps}\n\n"
    "Original request:\n{original_prompt}\n\n"
    "Please revise your response addressing these specific gaps."
)


def _parse_grader_response(text: str, rubric: list[str]) -> "ValidationReport":
    """Parse a grader's free-text response into a ValidationReport.

    Looks for NOT MET lines and a terminal SATISFIED / NEEDS_REVISION keyword.
    Malformed responses (neither keyword found) are treated as NEEDS_REVISION
    with a single generic gap so the loop continues rather than crashing.
    """
    from fireflyframework_agentic.validation.rules import ValidationReport, ValidationRuleResult

    lines = text.strip().splitlines()
    satisfied: bool | None = None
    failed: list[ValidationRuleResult] = []

    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if upper == "SATISFIED":
            satisfied = True
        elif upper == "NEEDS_REVISION":
            satisfied = False
        elif upper.startswith("NOT MET"):
            rest = stripped[7:].lstrip(":").strip()
            parts = rest.split("—", 1)  # em-dash separator
            if len(parts) == 1:
                parts = rest.split("-", 1)   # fallback: regular dash
            try:
                idx = int(parts[0].strip()) - 1
                criterion = rubric[idx] if 0 <= idx < len(rubric) else parts[0].strip()
            except (ValueError, IndexError):
                criterion = parts[0].strip()
            gap = parts[1].strip() if len(parts) > 1 else "criterion not met"
            failed.append(
                ValidationRuleResult(
                    rule_name=criterion,
                    field_name=f"criterion_{parts[0].strip()}",
                    passed=False,
                    message=gap,
                )
            )

    if satisfied is None:
        satisfied = False
        if not failed:
            failed.append(
                ValidationRuleResult(
                    rule_name="parse_error",
                    field_name="grader_response",
                    passed=False,
                    message="grader response could not be parsed",
                )
            )

    return ValidationReport(
        valid=bool(satisfied),
        results=failed,
        error_count=len(failed),
        field_count=len(rubric),
    )
```

- [ ] **Step 4: Run parse tests — confirm they pass**

```bash
pytest tests/data_validation/test_reviewer.py::test_parse_grader_satisfied tests/data_validation/test_reviewer.py::test_parse_grader_needs_revision tests/data_validation/test_reviewer.py::test_parse_grader_malformed_treated_as_needs_revision tests/data_validation/test_reviewer.py::test_parse_grader_field_count_matches_rubric -v 2>&1 | tail -15
```

Expected: 4 passed.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
pytest tests/data_validation/ -v 2>&1 | tail -20
```

Expected: all existing tests pass (only the new `RubricReviewer` loop tests fail, with `NameError`).

- [ ] **Step 6: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic checkout -b feat/rubric-reviewer
git -C /home/u/signature/fireflyframework-agentic add tests/data_validation/test_reviewer.py src/fireflyframework_agentic/validation/reviewer.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(validation): add _parse_grader_response for rubric evaluation"
```

---

## Task 2: `RubricReviewer` — constructor and review loop

**Files:**
- Modify: `tests/data_validation/test_reviewer.py`
- Modify: `src/fireflyframework_agentic/validation/reviewer.py`

- [ ] **Step 1: Add failing tests for the loop**

Append to `tests/data_validation/test_reviewer.py`:

```python
# ---------------------------------------------------------------------------
# RubricReviewer — loop
# ---------------------------------------------------------------------------


async def test_rubric_reviewer_satisfied_first_try():
    generator = MockAgent(["The answer is 42 [chunk_1]."])
    grader = MockAgent(["MET: 1\nSATISFIED"])
    reviewer = RubricReviewer(
        rubric=["Every claim cites at least one [chunk_id]."],
        grader=grader,
        max_iterations=3,
    )
    result = await reviewer.review(generator, "What is the answer?")
    assert result.attempts == 1
    assert result.validation_report.valid is True
    assert result.retry_history == []


async def test_rubric_reviewer_revision_then_satisfied():
    generator = MockAgent(["No citations here.", "The answer is 42 [chunk_1]."])
    grader = MockAgent([
        "NOT MET: 1 — no citation found\nNEEDS_REVISION",
        "MET: 1\nSATISFIED",
    ])
    reviewer = RubricReviewer(
        rubric=["Every claim cites at least one [chunk_id]."],
        grader=grader,
        max_iterations=3,
    )
    result = await reviewer.review(generator, "What is the answer?")
    assert result.attempts == 2
    assert result.validation_report.valid is True
    assert len(result.retry_history) == 1
    assert result.retry_history[0].attempt == 1
    assert "no citation found" in result.retry_history[0].errors[0]


async def test_rubric_reviewer_exhausted_raises():
    generator = MockAgent(["bad output"] * 4)
    grader = MockAgent(["NOT MET: 1 — no citation\nNEEDS_REVISION"] * 4)
    reviewer = RubricReviewer(
        rubric=["Every claim cites at least one [chunk_id]."],
        grader=grader,
        max_iterations=3,
    )
    with pytest.raises(OutputReviewError):
        await reviewer.review(generator, "question")


async def test_rubric_reviewer_empty_rubric_raises_at_construction():
    with pytest.raises(ValueError, match="at least one criterion"):
        RubricReviewer(rubric=[])


async def test_rubric_reviewer_malformed_grader_response_continues_loop():
    generator = MockAgent(["output", "fixed output"])
    grader = MockAgent(["this is not a valid grader response", "MET: 1\nSATISFIED"])
    reviewer = RubricReviewer(
        rubric=["The output is correct."],
        grader=grader,
        max_iterations=3,
    )
    result = await reviewer.review(generator, "question")
    assert result.attempts == 2


async def test_rubric_reviewer_custom_revision_prompt():
    prompts_seen: list[str] = []

    class CapturingAgent:
        def __init__(self, responses: list[str]) -> None:
            self._responses = responses
            self._idx = 0

        async def run(self, prompt: Any, **kwargs: Any) -> MockResult:
            prompts_seen.append(str(prompt))
            resp = self._responses[self._idx] if self._idx < len(self._responses) else self._responses[-1]
            self._idx += 1
            return MockResult(output=resp)

    generator = CapturingAgent(["bad", "good [chunk_1]."])
    grader = MockAgent([
        "NOT MET: 1 — missing citation\nNEEDS_REVISION",
        "MET: 1\nSATISFIED",
    ])
    reviewer = RubricReviewer(
        rubric=["Every claim cites at least one [chunk_id]."],
        grader=grader,
        max_iterations=3,
        revision_prompt="FIX: {gaps}\nORIGINAL: {original_prompt}",
    )
    result = await reviewer.review(generator, "question")
    assert result.attempts == 2
    assert "FIX:" in prompts_seen[1]
    assert "ORIGINAL:" in prompts_seen[1]
```

- [ ] **Step 2: Run — confirm they fail**

```bash
pytest tests/data_validation/test_reviewer.py::test_rubric_reviewer_satisfied_first_try -v 2>&1 | tail -10
```

Expected: `FAILED` — `RubricReviewer` not yet defined.

- [ ] **Step 3: Implement `RubricReviewer` in `reviewer.py`**

Add after the `OutputReviewer` class (at the end of `reviewer.py`):

```python
# ---------------------------------------------------------------------------
# RubricReviewer
# ---------------------------------------------------------------------------


class RubricReviewer:
    """Evaluate and revise LLM outputs against a natural-language rubric.

    Runs a grader agent in an isolated context window that assesses the
    output against each criterion. When criteria are not met, a revision
    prompt is sent to the generator and the loop repeats.

    Parameters:
        rubric: Ordered list of pass/fail criteria in natural language.
            Must be non-empty.
        grader: A separate agent used to evaluate outputs. When ``None``,
            a default :class:`FireflyAgent` is created with a rubric
            evaluation system prompt, using the generator's model if
            available.
        max_iterations: Maximum generation attempts (default 3). Raises
            :class:`OutputReviewError` on exhaustion.
        revision_prompt: Custom template for the revision prompt sent to
            the generator. Must contain ``{gaps}`` and
            ``{original_prompt}`` placeholders. Defaults to
            ``_DEFAULT_REVISION_TEMPLATE``.
    """

    def __init__(
        self,
        rubric: list[str],
        *,
        grader: AgentLike | None = None,
        max_iterations: int = 3,
        revision_prompt: str | None = None,
    ) -> None:
        if not rubric:
            raise ValueError("rubric must contain at least one criterion")
        self._rubric = list(rubric)
        self._grader = grader
        self._max_iterations = max(1, max_iterations)
        self._revision_prompt = revision_prompt or _DEFAULT_REVISION_TEMPLATE

    @classmethod
    def from_rubric_file(cls, path: str | Path, **kwargs: Any) -> "RubricReviewer":
        """Load rubric criteria from a Markdown file.

        Bullet list items (``- `` or ``* ``) become criteria. The H1
        heading and any prose paragraphs are ignored.

        Raises:
            ValueError: If no bullet list items are found in the file.
        """
        criteria: list[str] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                criteria.append(stripped[2:].strip())
        if not criteria:
            raise ValueError(f"No bullet list criteria found in {path}")
        return cls(criteria, **kwargs)

    async def review(
        self,
        agent: AgentLike,
        prompt: str | Sequence[Any],
        **kwargs: Any,
    ) -> ReviewResult:
        """Run the generator and iterate until the rubric is satisfied.

        Parameters:
            agent: The generator agent to run.
            prompt: The initial prompt.
            **kwargs: Forwarded to ``agent.run()``.

        Returns:
            A :class:`ReviewResult` with the accepted output.

        Raises:
            OutputReviewError: If ``max_iterations`` is exhausted.
        """
        grader = self._grader or self._make_default_grader(agent)
        retry_history: list[RetryAttempt] = []
        current_prompt = prompt

        for attempt in range(1, self._max_iterations + 1):
            result = await agent.run(current_prompt, **kwargs)
            raw = result.output if hasattr(result, "output") else result
            raw_str = str(raw)

            report = await self._evaluate_rubric(raw_str, grader)

            if report.valid:
                return ReviewResult(
                    output=raw,
                    attempts=attempt,
                    validation_report=report,
                    retry_history=retry_history,
                )

            gaps = [r.message for r in report.errors if r.message]
            retry_history.append(
                RetryAttempt(attempt=attempt, raw_output=raw_str[:500], errors=gaps)
            )
            if attempt < self._max_iterations:
                current_prompt = self._build_revision_prompt(prompt, gaps)
                logger.debug(
                    "RubricReviewer attempt %d/%d: gaps=%s",
                    attempt,
                    self._max_iterations,
                    gaps,
                )

        all_errors = [e for r in retry_history for e in r.errors]
        raise OutputReviewError(
            f"Rubric review failed after {self._max_iterations} attempts. "
            f"Last gaps: {all_errors[-3:] if all_errors else ['unknown']}"
        )

    async def _evaluate_rubric(self, output: str, grader: AgentLike) -> "ValidationReport":
        from fireflyframework_agentic.validation.rules import ValidationReport

        rubric_text = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(self._rubric))
        grader_prompt = _GRADER_PROMPT_TEMPLATE.format(rubric=rubric_text, output=output)
        result = await grader.run(grader_prompt)
        text = str(result.output if hasattr(result, "output") else result)
        return _parse_grader_response(text, self._rubric)

    def _build_revision_prompt(self, original_prompt: Any, gaps: list[str]) -> str:
        gap_text = "\n".join(f"- {g}" for g in gaps)
        return self._revision_prompt.format(
            gaps=gap_text, original_prompt=str(original_prompt)
        )

    def _make_default_grader(self, generator: AgentLike) -> AgentLike:
        from fireflyframework_agentic.agents.base import FireflyAgent

        model = getattr(generator, "_model_identifier", None)
        return FireflyAgent(model=model, system_prompt=_GRADER_SYSTEM_PROMPT)
```

- [ ] **Step 4: Run loop tests — confirm they pass**

```bash
pytest tests/data_validation/test_reviewer.py -k "rubric_reviewer" -v 2>&1 | tail -20
```

Expected: all 6 loop tests pass.

- [ ] **Step 5: Run full test suite — confirm no regressions**

```bash
pytest tests/data_validation/ -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add tests/data_validation/test_reviewer.py src/fireflyframework_agentic/validation/reviewer.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(validation): add RubricReviewer with rubric-based grader loop"
```

---

## Task 3: `from_rubric_file` — test then implement

- [ ] **Step 1: Add failing tests**

Append to `tests/data_validation/test_reviewer.py`:

```python
# ---------------------------------------------------------------------------
# RubricReviewer.from_rubric_file
# ---------------------------------------------------------------------------


def test_from_rubric_file_dash_bullets(tmp_path):
    md = tmp_path / "rubric.md"
    md.write_text(
        "# My Rubric\n\nSome description.\n\n"
        "- Every claim cites a source.\n"
        "- No contradictions.\n"
    )
    reviewer = RubricReviewer.from_rubric_file(md)
    assert reviewer._rubric == ["Every claim cites a source.", "No contradictions."]


def test_from_rubric_file_star_bullets(tmp_path):
    md = tmp_path / "rubric.md"
    md.write_text("* Criterion one.\n* Criterion two.\n")
    reviewer = RubricReviewer.from_rubric_file(md)
    assert len(reviewer._rubric) == 2
    assert reviewer._rubric[0] == "Criterion one."


def test_from_rubric_file_no_criteria_raises(tmp_path):
    md = tmp_path / "rubric.md"
    md.write_text("# Just a heading\n\nSome prose, no bullets.\n")
    with pytest.raises(ValueError, match="No bullet list criteria"):
        RubricReviewer.from_rubric_file(md)


def test_from_rubric_file_passes_kwargs(tmp_path):
    md = tmp_path / "rubric.md"
    md.write_text("- Only criterion.\n")
    reviewer = RubricReviewer.from_rubric_file(md, max_iterations=1)
    assert reviewer._max_iterations == 1
```

- [ ] **Step 2: Run — confirm tests pass**

`from_rubric_file` was already implemented as part of `RubricReviewer` in Task 2. These tests exercise it with `tmp_path` fixtures not covered before:

```bash
pytest tests/data_validation/test_reviewer.py -k "from_rubric_file" -v 2>&1 | tail -15
```

Expected: all 4 pass.

- [ ] **Step 4: Run full `data_validation` suite**

```bash
pytest tests/data_validation/ -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add tests/data_validation/test_reviewer.py
git -C /home/u/signature/fireflyframework-agentic commit -m "test(validation): add from_rubric_file tests for RubricReviewer"
```

---

## Task 4: Export from `__init__.py` and open PR

**Files:**
- Modify: `src/fireflyframework_agentic/validation/__init__.py`

- [ ] **Step 1: Add `RubricReviewer` to the import and `__all__`**

In `src/fireflyframework_agentic/validation/__init__.py`, update the reviewer import block:

```python
from fireflyframework_agentic.validation.reviewer import (
    OutputReviewer,
    RetryAttempt,
    ReviewResult,
    RubricReviewer,
)
```

Add `"RubricReviewer"` to `__all__` in alphabetical order (between `"ReviewResult"` and `"ValidationReport"`):

```python
    "RubricReviewer",
```

- [ ] **Step 2: Verify the export works**

```bash
cd /home/u/signature/fireflyframework-agentic && source ~/.venvs/signature/bin/activate && python -c "from fireflyframework_agentic.validation import RubricReviewer; print('OK', RubricReviewer)"
```

Expected: `OK <class '...RubricReviewer'>`

- [ ] **Step 3: Run full test suite one final time**

```bash
pytest tests/data_validation/ -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 4: Commit and push**

```bash
git -C /home/u/signature/fireflyframework-agentic add src/fireflyframework_agentic/validation/__init__.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(validation): export RubricReviewer from validation package"
git -C /home/u/signature/fireflyframework-agentic push -u origin feat/rubric-reviewer
```

- [ ] **Step 5: Open PR**

```bash
gh pr create \
  --repo fireflyframework/fireflyframework-agentic \
  --title "feat(validation): RubricReviewer — rubric-based grader loop" \
  --body "$(cat <<'EOF'
## Summary

- Adds `RubricReviewer` to `validation/reviewer.py` alongside `OutputReviewer`
- Rubric is a `list[str]` of natural-language pass/fail criteria; also loadable from a Markdown file via `from_rubric_file()`
- Grader runs as a separate `AgentLike` in an isolated context window, evaluating each criterion independently
- Reuses `ReviewResult`, `RetryAttempt`, `ValidationReport`, `ValidationRuleResult`, and `OutputReviewError` — zero new models
- Iteration stops when all criteria are satisfied (`SATISFIED`) or `max_iterations` is exhausted

Closes #121

## Test plan

- [ ] `pytest tests/data_validation/test_reviewer.py` — all unit tests pass with mocked grader
- [ ] `from fireflyframework_agentic.validation import RubricReviewer` resolves correctly
EOF
)"
```
