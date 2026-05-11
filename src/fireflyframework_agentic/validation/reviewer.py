# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Output reviewer with automatic retry for structured output validation.

:class:`OutputReviewer` wraps an agent call with validation and retry
logic.  When the LLM produces output that fails Pydantic parsing or
:class:`~fireflyframework_agentic.validation.rules.OutputValidator` rules,
the reviewer automatically retries with a feedback prompt that tells
the LLM exactly what was wrong.

This closes the loop between generation and validation, ensuring that
downstream consumers receive well-formed, schema-conformant data.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, ValidationError

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.exceptions import OutputReviewError
from fireflyframework_agentic.types import AgentLike
from fireflyframework_agentic.validation.rules import OutputValidator, ValidationReport, ValidationRuleResult

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class RetryAttempt(BaseModel):
    """Record of a single retry attempt during output review.

    Attributes:
        attempt: 1-based attempt number.
        raw_output: The raw LLM output that was rejected.
        errors: List of error messages explaining why the output was rejected.
    """

    attempt: int
    raw_output: str = ""
    errors: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel, Generic[T]):
    """Outcome of an output review, including the validated output.

    Attributes:
        output: The validated output (typed by ``T``).
        attempts: Total number of attempts made (1 = first try succeeded).
        validation_report: The final validation report (if an
            :class:`OutputValidator` was used).
        retry_history: Chronological list of failed attempts.
    """

    output: T = None  # type: ignore[assignment]
    attempts: int = 1
    validation_report: ValidationReport | None = None
    retry_history: list[RetryAttempt] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Default retry prompt
# ---------------------------------------------------------------------------

_DEFAULT_RETRY_TEMPLATE = (
    "Your previous response did not meet the required format.\n\n"
    "Errors:\n{errors}\n\n"
    "Original request:\n{original_prompt}\n\n"
    "Please try again, ensuring your response exactly matches the "
    "required output schema."
)


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
    lines = text.strip().splitlines()
    satisfied: bool | None = None
    failed: list[ValidationRuleResult] = []

    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if upper == "SATISFIED":
            satisfied = True
            break
        elif upper == "NEEDS_REVISION":
            satisfied = False
            break
        elif upper.startswith("NOT MET:"):
            rest = stripped[7:].lstrip(":").strip()
            parts = rest.split("—", 1)
            if len(parts) == 1:
                parts = rest.split(" - ", 1)
            try:
                idx = int(parts[0].strip()) - 1
                criterion = rubric[idx] if 0 <= idx < len(rubric) else parts[0].strip()
                field_name = f"criterion_{idx + 1}"
            except (ValueError, IndexError):
                criterion = parts[0].strip()
                field_name = "criterion_unknown"
            gap = parts[1].strip() if len(parts) > 1 else "criterion not met"
            failed.append(
                ValidationRuleResult(
                    rule_name=criterion,
                    field_name=field_name,
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


# ---------------------------------------------------------------------------
# RubricReviewer (placeholder — full implementation in subsequent tasks)
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

    async def _evaluate_rubric(self, output: str, grader: AgentLike) -> ValidationReport:
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
        model = getattr(generator, "_model_identifier", None)
        return FireflyAgent(model=model, system_prompt=_GRADER_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# OutputReviewer
# ---------------------------------------------------------------------------


class OutputReviewer:
    """Validate and retry LLM outputs until they conform to a schema.

    The reviewer performs up to ``max_retries + 1`` total attempts
    (1 initial + N retries).  On each failure it builds a feedback
    prompt describing the errors and asks the agent to try again.

    Parameters:
        output_type: A Pydantic ``BaseModel`` subclass to parse the
            output into.  When ``None``, no schema parsing is performed.
        validator: An optional :class:`OutputValidator` for field-level
            and cross-field rules.
        max_retries: Maximum number of retry attempts after the initial
            call (default 3).
        retry_prompt: Custom retry prompt template.  Must contain
            ``{errors}`` and ``{original_prompt}`` placeholders.
    """

    def __init__(
        self,
        *,
        output_type: type[BaseModel] | None = None,
        validator: OutputValidator | None = None,
        max_retries: int = 3,
        retry_prompt: str | None = None,
    ) -> None:
        self._output_type = output_type
        self._validator = validator
        self._max_retries = max(0, max_retries)
        self._retry_prompt = retry_prompt or _DEFAULT_RETRY_TEMPLATE

    @property
    def output_type(self) -> type[BaseModel] | None:
        return self._output_type

    @property
    def max_retries(self) -> int:
        return self._max_retries

    async def review(
        self,
        agent: AgentLike,
        prompt: str | Sequence[Any],
        **kwargs: Any,
    ) -> ReviewResult[Any]:
        """Run the agent and validate/retry the output.

        Parameters:
            agent: An object with an async ``run(prompt, **kwargs)`` method.
            prompt: The prompt to send to the agent.
            **kwargs: Extra keyword arguments forwarded to ``agent.run()``.

        Returns:
            A :class:`ReviewResult` containing the validated output.

        Raises:
            OutputReviewError: If all retry attempts are exhausted
                without producing valid output.
        """
        retry_history: list[RetryAttempt] = []
        current_prompt = prompt
        # Total attempts = 1 initial + max_retries.  On each failure, a
        # feedback prompt is constructed that tells the LLM what was wrong,
        # closing the generation-validation loop.
        total_attempts = self._max_retries + 1

        for attempt in range(1, total_attempts + 1):
            result = await agent.run(current_prompt, **kwargs)
            raw = result.output if hasattr(result, "output") else result
            raw_str = str(raw)

            # Step 1: Schema parsing (if output_type set)
            parsed, parse_errors = self._parse_output(raw)
            if parse_errors:
                retry_history.append(
                    RetryAttempt(
                        attempt=attempt,
                        raw_output=raw_str[:500],
                        errors=parse_errors,
                    )
                )
                if attempt < total_attempts:
                    current_prompt = self._build_retry_prompt(prompt, parse_errors)
                    logger.debug(
                        "Reviewer attempt %d/%d failed (parse): %s",
                        attempt,
                        total_attempts,
                        parse_errors,
                    )
                continue

            # Step 2: Validator rules (if validator set)
            report = self._validate_output(parsed if parsed is not None else raw)
            if report is not None and not report.valid:
                rule_errors = [r.message for r in report.errors if r.message]
                retry_history.append(
                    RetryAttempt(
                        attempt=attempt,
                        raw_output=raw_str[:500],
                        errors=rule_errors,
                    )
                )
                if attempt < total_attempts:
                    current_prompt = self._build_retry_prompt(prompt, rule_errors)
                    logger.debug(
                        "Reviewer attempt %d/%d failed (validation): %s",
                        attempt,
                        total_attempts,
                        rule_errors,
                    )
                continue

            # Success
            return ReviewResult(
                output=parsed if parsed is not None else raw,
                attempts=attempt,
                validation_report=report,
                retry_history=retry_history,
            )

        # All attempts exhausted
        all_errors = []
        for r in retry_history:
            all_errors.extend(r.errors)
        raise OutputReviewError(
            f"Output review failed after {total_attempts} attempts. "
            f"Last errors: {all_errors[-3:] if all_errors else ['unknown']}"
        )

    # -- Internal helpers ----------------------------------------------------

    def _parse_output(self, raw: Any) -> tuple[BaseModel | None, list[str]]:
        """Try to parse *raw* into ``self._output_type``.

        Returns ``(parsed_model, [])`` on success or ``(None, errors)``
        on failure.

        The parsing cascade tries three approaches in order:
        1. Already the correct Pydantic model type → return as-is.
        2. A ``dict`` → ``model_validate()``.
        3. A string → ``model_validate_json()``.
        """
        if self._output_type is None:
            return None, []

        if isinstance(raw, self._output_type):
            return raw, []

        if isinstance(raw, dict):
            try:
                return self._output_type.model_validate(raw), []
            except ValidationError as exc:
                return None, [str(e["msg"]) for e in exc.errors()]

        # Try parsing from JSON string
        raw_str = str(raw)
        try:
            return self._output_type.model_validate_json(raw_str), []
        except (ValidationError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                return None, [str(e["msg"]) for e in exc.errors()]
            return None, [f"Invalid JSON: {exc}"]

    def _validate_output(self, output: Any) -> ValidationReport | None:
        """Run ``self._validator`` against *output* if configured."""
        if self._validator is None:
            return None
        return self._validator.validate(output)

    def _build_retry_prompt(self, original_prompt: Any, errors: list[str]) -> str:
        """Build a retry prompt that includes error feedback."""
        error_text = "\n".join(f"- {e}" for e in errors)
        prompt_str = str(original_prompt)
        return self._retry_prompt.format(
            errors=error_text,
            original_prompt=prompt_str,
        )
