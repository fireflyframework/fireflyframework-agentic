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

"""Tests for the OutputReviewer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, Field

from fireflyframework_agentic.exceptions import OutputReviewError
from fireflyframework_agentic.validation.reviewer import (
    OutputReviewer,
    RetryAttempt,
    ReviewResult,
    RubricReviewer,
    _parse_grader_response,
)
from fireflyframework_agentic.validation.rules import EnumRule, OutputValidator


@dataclass
class MockResult:
    output: Any = ""


class MockAgent:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def run(self, prompt: Any, **kwargs: Any) -> MockResult:
        resp = self._responses[self._idx] if self._idx < len(self._responses) else self._responses[-1]
        self._idx += 1
        return MockResult(output=resp)


class SampleOutput(BaseModel):
    name: str
    score: float = Field(ge=0.0, le=1.0)


class TestOutputReviewerBasic:
    async def test_no_validation(self):
        """With no output_type or validator, review just passes through."""
        agent = MockAgent(["hello"])
        reviewer = OutputReviewer()
        result = await reviewer.review(agent, "test")
        assert result.output == "hello"
        assert result.attempts == 1
        assert result.retry_history == []

    async def test_schema_parsing_success(self):
        """When agent returns a valid model instance, it passes immediately."""
        agent = MockAgent([SampleOutput(name="test", score=0.8)])
        reviewer = OutputReviewer(output_type=SampleOutput)
        result = await reviewer.review(agent, "test")
        assert isinstance(result.output, SampleOutput)
        assert result.output.name == "test"
        assert result.attempts == 1

    async def test_schema_parsing_dict(self):
        """When agent returns a dict, it should be parsed into the model."""
        agent = MockAgent([{"name": "foo", "score": 0.5}])
        reviewer = OutputReviewer(output_type=SampleOutput)
        result = await reviewer.review(agent, "test")
        assert isinstance(result.output, SampleOutput)
        assert result.output.name == "foo"


class TestOutputReviewerRetry:
    async def test_retry_on_invalid_schema(self):
        """Should retry when first output fails schema parsing."""
        agent = MockAgent(
            [
                "not valid json",
                SampleOutput(name="fixed", score=0.9),
            ]
        )
        reviewer = OutputReviewer(output_type=SampleOutput, max_retries=2)
        result = await reviewer.review(agent, "test")
        assert isinstance(result.output, SampleOutput)
        assert result.attempts == 2
        assert len(result.retry_history) == 1
        assert result.retry_history[0].attempt == 1

    async def test_retry_exhausted_raises(self):
        """Should raise OutputReviewError when all retries fail."""
        agent = MockAgent(
            [
                "bad 1",
                "bad 2",
                "bad 3",
                "bad 4",
            ]
        )
        reviewer = OutputReviewer(output_type=SampleOutput, max_retries=3)
        with pytest.raises(OutputReviewError, match="failed after 4 attempts"):
            await reviewer.review(agent, "test")

    async def test_validator_rules(self):
        """Should retry when output_type passes but validator rules fail."""
        validator = OutputValidator(
            {
                "name": [EnumRule("name", ["alice", "bob"])],
            }
        )
        agent = MockAgent(
            [
                SampleOutput(name="charlie", score=0.5),  # fails enum rule
                SampleOutput(name="alice", score=0.8),  # passes
            ]
        )
        reviewer = OutputReviewer(
            output_type=SampleOutput,
            validator=validator,
            max_retries=2,
        )
        result = await reviewer.review(agent, "test")
        assert result.output.name == "alice"
        assert result.attempts == 2

    async def test_custom_retry_prompt(self):
        """Custom retry prompt should be used."""
        agent = MockAgent(
            [
                "bad",
                SampleOutput(name="ok", score=0.5),
            ]
        )
        reviewer = OutputReviewer(
            output_type=SampleOutput,
            retry_prompt="FIX THIS: {errors}\nORIGINAL: {original_prompt}",
        )
        result = await reviewer.review(agent, "test")
        assert result.attempts == 2

    async def test_zero_retries(self):
        """With max_retries=0, only one attempt should be made."""
        agent = MockAgent(["bad"])
        reviewer = OutputReviewer(output_type=SampleOutput, max_retries=0)
        with pytest.raises(OutputReviewError, match="failed after 1 attempts"):
            await reviewer.review(agent, "test")


class TestRetryAttemptModel:
    def test_structure(self):
        a = RetryAttempt(attempt=1, raw_output="bad", errors=["parse error"])
        assert a.attempt == 1
        assert len(a.errors) == 1


class TestReviewResultModel:
    def test_structure(self):
        r = ReviewResult(output="ok", attempts=1)
        assert r.output == "ok"
        assert r.retry_history == []
        assert r.validation_report is None


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
    assert report.errors[0].rule_name == "Every claim cites at least one [chunk_id]."


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


def test_parse_grader_satisfied_results_empty():
    rubric = ["Criterion A"]
    report = _parse_grader_response("MET: 1\nSATISFIED", rubric)
    assert report.results == []


def test_parse_grader_field_count_in_failing_path():
    rubric = ["A", "B"]
    report = _parse_grader_response("NOT MET: 1 — missing\nNEEDS_REVISION", rubric)
    assert report.field_count == 2


def test_parse_grader_hyphen_separator():
    rubric = ["Every claim cites a source."]
    report = _parse_grader_response("NOT MET: 1 - no citation found\nNEEDS_REVISION", rubric)
    assert report.valid is False
    assert report.error_count == 1
    assert report.errors[0].message == "no citation found"


def test_parse_grader_non_numeric_criterion():
    rubric = ["A"]
    report = _parse_grader_response("NOT MET: conclusion missing\nNEEDS_REVISION", rubric)
    assert report.valid is False
    assert report.error_count == 1
    assert report.errors[0].field_name == "criterion_unknown"


def test_parse_grader_first_terminal_keyword_wins():
    rubric = ["A"]
    # SATISFIED appears first — second keyword should be ignored
    report = _parse_grader_response("MET: 1\nSATISFIED\nNEEDS_REVISION", rubric)
    assert report.valid is True


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
    with pytest.raises(OutputReviewError, match="failed after 3 attempts"):
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


def test_rubric_reviewer_default_grader_construction():
    from unittest.mock import MagicMock, patch

    mock_agent_instance = MagicMock()

    with patch(
        "fireflyframework_agentic.validation.reviewer.RubricReviewer._make_default_grader",
        return_value=mock_agent_instance,
    ) as mock_make:
        reviewer = RubricReviewer(rubric=["Criterion A."])
        # _make_default_grader is lazy — called on first review(), not at construction
        assert reviewer._grader is None
        mock_make.assert_not_called()


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
