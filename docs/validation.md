# Validation Guide

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

The Validation module provides structured output validation and quality-of-service
(QoS) checks for LLM-generated results. It helps ensure that agent outputs conform
to expected schemas, business rules, and quality thresholds before they reach
downstream consumers.

---

## Output Validation (`validation.rules`)

### Validation Rules

Rules are composable predicates that check a single field value. The framework ships
with five built-in rule types:

- **RegexRule** -- Value matches a regular expression.
- **FormatRule** -- Value matches a named format (`email`, `url`, `date`, `uuid`, `iso_date`).
- **RangeRule** -- Numeric value falls within `[min, max]`.
- **EnumRule** -- Value is one of a predefined set.
- **CustomRule** -- User-supplied predicate function.

```python
from fireflyframework_genai.validation.rules import (
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

`OutputValidator` orchestrates multiple `FieldValidator` instances to validate an
entire output dictionary at once. The result is a `ValidationReport` listing all
passing and failing fields.

```python
from fireflyframework_genai.validation.rules import OutputValidator, RegexRule, EnumRule, RangeRule

validator = OutputValidator({
    "status": [EnumRule("status", ["approved", "rejected", "pending"])],
    "amount": [RangeRule("amount", min_value=0.0, max_value=1_000_000)],
})
report = validator.validate({"status": "approved", "amount": 42.5})
```

---

## Quality of Service (`validation.qos`)

The QoS module provides post-generation quality checks that detect low-confidence
answers, inconsistent outputs, and hallucinations.

### ConfidenceScorer

Extracts or estimates a confidence score from an LLM response by looking for explicit
confidence markers (e.g. "I'm 85% confident") or using heuristic indicators like
hedging language.

```python
from fireflyframework_genai.validation.qos import ConfidenceScorer

scorer = ConfidenceScorer(my_agent)
score = await scorer.score("The answer is definitely 42.")
```

### ConsistencyChecker

Runs the same prompt through an agent multiple times and measures the consistency
of the outputs.

```python
from fireflyframework_genai.validation.qos import ConsistencyChecker

checker = ConsistencyChecker(my_agent, num_runs=3)
score, outputs = await checker.check("What is the capital of France?")
print(score) # 1.0 if all answers agree
```

### GroundingChecker

Verifies that a response is grounded in provided reference text by checking how much
of the response content can be traced back to the source material.

```python
from fireflyframework_genai.validation.qos import GroundingChecker

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
from fireflyframework_genai.validation.qos import (
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
from fireflyframework_genai.validation import OutputReviewer

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
from fireflyframework_genai.validation import OutputReviewer, OutputValidator, EnumRule

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
from fireflyframework_genai.reasoning import ReActPattern
from fireflyframework_genai.validation import OutputReviewer

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
- **retry_history** -- List of `RetryAttempt` objects (attempt number, raw output, error messages).
