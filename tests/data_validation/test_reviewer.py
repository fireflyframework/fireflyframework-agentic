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

"""Tests for the OutputReviewer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, Field

from fireflyframework_agentic.exceptions import OutputReviewError
from fireflyframework_agentic.validation.reviewer import OutputReviewer, RetryAttempt, ReviewResult
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
