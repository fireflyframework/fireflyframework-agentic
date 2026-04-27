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

"""Tests for ReasoningPipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fireflyframework_agentic.memory import MemoryManager
from fireflyframework_agentic.reasoning.chain_of_thought import ChainOfThoughtPattern
from fireflyframework_agentic.reasoning.models import ReasoningThought, ReflectionVerdict
from fireflyframework_agentic.reasoning.pipeline import ReasoningPipeline
from fireflyframework_agentic.reasoning.reflexion import ReflexionPattern


@dataclass
class MockResult:
    output: Any = ""


class MockAgent:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_count = 0

    async def run(self, prompt: Any, **kwargs: Any) -> MockResult:
        resp = self._responses[self._call_count] if self._call_count < len(self._responses) else "default"
        self._call_count += 1
        return MockResult(output=resp)


class TestReasoningPipeline:
    async def test_two_pattern_pipeline(self):
        """Output of pattern 1 should become input for pattern 2."""
        agent = MockAgent(
            [
                # Pattern 1 (CoT): step 1 -> final
                ReasoningThought(content="Draft answer", is_final=True, final_answer="draft 42"),
                # Pattern 2 (Reflexion): generate answer, then critique
                "improved 42",
                ReflectionVerdict(is_satisfactory=True),
            ]
        )
        pipeline = ReasoningPipeline(
            [
                ChainOfThoughtPattern(max_steps=3),
                ReflexionPattern(max_steps=3),
            ]
        )
        result = await pipeline.execute(agent, "What is 6*7?")
        assert result.success is True
        assert result.steps_taken >= 2
        # Output should come from the last pattern
        assert "improved" in str(result.output)

    async def test_merged_trace(self):
        """Pipeline trace should contain steps from all patterns."""
        agent = MockAgent(
            [
                ReasoningThought(content="step 1", is_final=True, final_answer="ans"),
                "final answer",
                ReflectionVerdict(is_satisfactory=True),
            ]
        )
        pipeline = ReasoningPipeline(
            [
                ChainOfThoughtPattern(max_steps=3),
                ReflexionPattern(max_steps=3),
            ]
        )
        result = await pipeline.execute(agent, "test")
        assert len(result.trace.steps) >= 2

    async def test_pipeline_with_memory(self):
        """Memory should be passed through to each pattern."""
        memory = MemoryManager()
        agent = MockAgent(
            [
                ReasoningThought(content="step", is_final=True, final_answer="done"),
                "ok",
                ReflectionVerdict(is_satisfactory=True),
            ]
        )
        pipeline = ReasoningPipeline(
            [
                ChainOfThoughtPattern(max_steps=3),
                ReflexionPattern(max_steps=3),
            ]
        )
        result = await pipeline.execute(agent, "test", memory=memory)
        assert result.success is True

    async def test_pipeline_repr(self):
        pipeline = ReasoningPipeline(
            [
                ChainOfThoughtPattern(max_steps=3),
            ],
            name="my_pipe",
        )
        assert "my_pipe" in repr(pipeline)
        assert "1" in repr(pipeline)
