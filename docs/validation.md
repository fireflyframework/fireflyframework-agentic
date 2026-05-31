# Validation Guide

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The Validation module provides structured output validation and quality-of-service
(QoS) checks for LLM-generated results. It helps ensure that agent outputs conform
to expected schemas, business rules, and quality thresholds before they reach
downstream consumers.

---

## Output Validation (`validation.rules`)

### Validation Rules

Rules are composable predicates that check a single field value. The framework ships
with five built-in rule types:

- **RegexRule** -- Value matches a regular expression. Accepts an optional keyword-only `description` used as the failure message.
- **FormatRule** -- Value matches one of six named formats: `email`, `date`, `iso_date`, `phone`, `url`, `uuid`. An unknown `format_type` raises `ValueError`.
- **RangeRule** -- Numeric value falls within `[min_value, max_value]` (either bound may be `None`).
- **EnumRule** -- Value is one of a predefined set. Accepts a keyword-only `case_sensitive` flag (default `True`).
- **CustomRule** -- User-supplied predicate `(value) -> bool` with an optional `description`.

Every rule exposes a `.name` property and a `.validate(value) -> ValidationRuleResult` method.

```python
from fireflyframework_agentic.validation.rules import (
    OutputValidator,
    RegexRule,
    RangeRule,
    EnumRule,
)

validator = OutputValidator({
    "invoice_number": [RegexRule("invoice_number", r"^INV-\d{6}$")],
})
report = validator.validate({"invoice_number": "INV-001234"})
assert report.valid is True
```

### OutputValidator

`OutputValidator` maps each field name to a list of rules and validates an entire
output at once. The `validate(output)` method accepts a `dict`, a Pydantic
`BaseModel` (it is dumped via `model_dump()`), or any object exposing `__dict__`.
The result is a `ValidationReport`.

```python
from fireflyframework_agentic.validation.rules import OutputValidator, RegexRule, EnumRule, RangeRule

validator = OutputValidator({
    "status": [EnumRule("status", ["approved", "rejected", "pending"])],
    "amount": [RangeRule("amount", min_value=0.0, max_value=1_000_000)],
})
report = validator.validate({"status": "approved", "amount": 42.5})
```

Rules can also be added incrementally with `add_field_rule(field_name, rule)`:

```python
validator.add_field_rule("invoice_number", RegexRule("invoice_number", r"^INV-\d{6}$"))
```

#### Cross-field rules

For checks that span multiple fields, pass `cross_field_rules` -- a sequence of
callables that receive the full output dict and return a `ValidationRuleResult`:

```python
from fireflyframework_agentic.validation.rules import OutputValidator, ValidationRuleResult

def net_below_gross(data: dict) -> ValidationRuleResult:
    ok = data.get("net", 0) <= data.get("gross", 0)
    return ValidationRuleResult(
        rule_name="net_below_gross",
        field_name="net",
        passed=ok,
        message="" if ok else "net must not exceed gross",
    )

validator = OutputValidator(cross_field_rules=[net_below_gross])
report = validator.validate({"net": 90, "gross": 100})
```

### Report and result models

`ValidationReport` aggregates the outcome of every rule:

- **valid** -- `True` when no rule failed.
- **results** -- The full list of `ValidationRuleResult` objects (passing and failing).
- **errors** -- A property returning only the failing results.
- **error_count** -- Number of failing rules.
- **field_count** -- Number of fields with configured rules.

Each `ValidationRuleResult` carries `rule_name`, `field_name`, `passed`, `message`
(empty on success), and the offending `value`. The `OutputReviewer` retry feedback
is built from the `message` of each failing result.

---

## Quality of Service (`validation.qos`)

The QoS module provides post-generation quality checks that detect low-confidence
answers, inconsistent outputs, and hallucinations.

### ConfidenceScorer

Extracts or estimates a confidence score from an LLM response by looking for explicit
confidence markers (e.g. "I'm 85% confident") or using heuristic indicators like
hedging language.

```python
from fireflyframework_agentic.validation.qos import ConfidenceScorer

scorer = ConfidenceScorer(my_agent)
score = await scorer.score("The answer is definitely 42.")
```

### ConsistencyChecker

Runs the same prompt through an agent multiple times and measures the consistency
of the outputs.

```python
from fireflyframework_agentic.validation.qos import ConsistencyChecker

checker = ConsistencyChecker(my_agent, num_runs=3)
score, outputs = await checker.check("What is the capital of France?")
print(score) # 1.0 if all answers agree
```

### GroundingChecker

Verifies that a response is grounded in provided reference text by checking how much
of the response content can be traced back to the source material.

```python
from fireflyframework_agentic.validation.qos import GroundingChecker

checker = GroundingChecker()
score, field_map = checker.check(
    source_text="France's capital is Paris.",
    extracted_fields={"capital": "Paris"},
)
print(score) # 1.0 if all fields are grounded in the source
```

### QoSGuard

`QoSGuard` composes the above checks into a single gate that can be wired into a
pipeline node or used standalone. It produces a `QoSResult` with a pass/fail verdict.

```python
from fireflyframework_agentic.validation.qos import (
    QoSGuard, ConfidenceScorer, ConsistencyChecker, GroundingChecker,
)

guard = QoSGuard(
    confidence_scorer=ConfidenceScorer(my_agent),
    consistency_checker=ConsistencyChecker(my_agent, num_runs=3),
    grounding_checker=GroundingChecker(),
    min_confidence=0.7,
    min_consistency=0.6,
)
result = await guard.evaluate("4", prompt="What is 2+2?")
if result.passed:
    print("Quality check passed")
```

---

## Output Reviewer (`validation.reviewer`)

The `OutputReviewer` closes the loop between generation and validation by wrapping
an agent call with schema parsing + rule validation + automatic retry. When the LLM
produces output that fails Pydantic parsing or `OutputValidator` rules, the reviewer
automatically retries with a feedback prompt describing exactly what was wrong.

### Basic Usage

```python
from pydantic import BaseModel, Field
from fireflyframework_agentic.validation import OutputReviewer

class InvoiceData(BaseModel):
    vendor: str
    amount: float = Field(ge=0)
    date: str

reviewer = OutputReviewer(output_type=InvoiceData, max_retries=3)
result = await reviewer.review(agent, "Extract invoice data from: Acme Corp, $1,234, 2026-01-15")
print(result.output) # InvoiceData(vendor="Acme Corp", amount=1234.0, date="2026-01-15")
print(result.attempts) # 1 if first try succeeded, 2+ if retries were needed
```

### With Validation Rules

Combine schema parsing with field-level validation rules:

```python
from fireflyframework_agentic.validation import OutputReviewer, OutputValidator, EnumRule

validator = OutputValidator({
    "vendor": [EnumRule("vendor", ["Acme Corp", "Globex", "Initech"])],
})
reviewer = OutputReviewer(
    output_type=InvoiceData,
    validator=validator,
    max_retries=2,
)
result = await reviewer.review(agent, "Extract invoice data from: ...")
```

### With Reasoning Patterns

Attach a reviewer to any reasoning pattern to validate the final output:

```python
from fireflyframework_agentic.reasoning import ReActPattern
from fireflyframework_agentic.validation import OutputReviewer

reviewer = OutputReviewer(output_type=InvoiceData, max_retries=2)
pattern = ReActPattern(reviewer=reviewer)
result = await pattern.execute(agent, "Extract invoice data from the document.")
```

### Parameters

- **output_type** -- A Pydantic `BaseModel` subclass to parse the output into. When `None`, no schema parsing.
- **validator** -- An optional `OutputValidator` for field-level and cross-field rules.
- **max_retries** -- Maximum retry attempts after the initial call (default 3).
- **retry_prompt** -- Custom retry prompt template with `{errors}` and `{original_prompt}` placeholders.

### Result Model

`ReviewResult` contains:

- **output** -- The validated output.
- **attempts** -- Total attempts made (1 = first try succeeded).
- **validation_report** -- The final `ValidationReport` if a validator was used.
- **retry_history** -- List of `RetryAttempt` objects (`attempt` number, `raw_output`, `errors`).

---

## Rubric Reviewer (`validation.reviewer`)

`RubricReviewer` is an LLM-as-judge variant: instead of a schema, it evaluates output
against a list of natural-language pass/fail criteria using a separate **grader**
agent that runs in its own context window. When criteria are not met, a revision
prompt describing the gaps is sent back to the generator and the loop repeats.

```python
from fireflyframework_agentic.validation import RubricReviewer

reviewer = RubricReviewer(
    rubric=[
        "The answer cites at least one source.",
        "The tone is professional and free of slang.",
        "No claim is unsupported by the cited material.",
    ],
    max_iterations=3,
)
result = await reviewer.review(agent, "Summarise the attached policy document.")
print(result.output)   # the accepted output
print(result.attempts) # number of generation passes
```

By default a `FireflyAgent` grader is created automatically (reusing the generator's
model when available). Supply your own with `grader=...`. The rubric may also be
loaded from a Markdown file -- each `- ` / `* ` bullet becomes a criterion:

```python
reviewer = RubricReviewer.from_rubric_file("rubric.md", max_iterations=2)
```

### Parameters

- **rubric** -- Ordered list of pass/fail criteria (must be non-empty).
- **grader** -- Optional grader agent; defaults to an auto-created `FireflyAgent`.
- **max_iterations** -- Maximum generation passes (default 3).
- **revision_prompt** -- Custom revision template with `{gaps}` and `{original_prompt}` placeholders.

`review(agent, prompt, **kwargs)` is async, returns a `ReviewResult`, and raises
`OutputReviewError` once `max_iterations` is exhausted without satisfying the rubric.
