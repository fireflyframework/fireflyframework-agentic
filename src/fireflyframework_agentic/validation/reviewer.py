# Copyright 2026 Firefly Software Solutions Inc
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
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, ValidationError

from fireflyframework_agentic.exceptions import OutputReviewError
from fireflyframework_agentic.types import AgentLike
from fireflyframework_agentic.validation.rules import OutputValidator, ValidationReport

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
