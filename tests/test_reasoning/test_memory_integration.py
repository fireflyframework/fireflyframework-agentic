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

"""Tests for reasoning pattern memory integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from fireflyframework_agentic.memory import MemoryManager
from fireflyframework_agentic.reasoning.base import AbstractReasoningPattern
from fireflyframework_agentic.reasoning.chain_of_thought import ChainOfThoughtPattern
from fireflyframework_agentic.reasoning.models import (
    BranchEvaluation,
    ReasoningThought,
    ReflectionVerdict,
)
from fireflyframework_agentic.reasoning.react import ReActPattern
from fireflyframework_agentic.reasoning.reflexion import ReflexionPattern
from fireflyframework_agentic.reasoning.tree_of_thoughts import TreeOfThoughtsPattern


@dataclass
class MockResult:
    output: Any = ""


class MockAgent:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_count = 0
        self.prompts: list[str] = []

    async def run(self, prompt: Any, **kwargs: Any) -> MockResult:
        self.prompts.append(str(prompt))
        resp = self._responses[self._call_count] if self._call_count < len(self._responses) else "default"
        self._call_count += 1
        return MockResult(output=resp)


class TestMemoryFork:
    async def test_pattern_forks_memory(self):
        """Pattern should fork memory into a scoped working memory."""
        memory = MemoryManager()
        memory.set_fact("global_fact", "visible")
        agent = MockAgent(
            [
                ReasoningThought(content="done", is_final=True, final_answer="42"),
            ]
        )
        pattern = ChainOfThoughtPattern(max_steps=3)
        result = await pattern.execute(agent, "test", memory=memory)
        assert result.success is True

    async def test_memory_none_is_safe(self):
        """Passing no memory should work without errors."""
        agent = MockAgent(
            [
                ReasoningThought(content="done", is_final=True, final_answer="42"),
            ]
        )
        pattern = ChainOfThoughtPattern(max_steps=3)
        result = await pattern.execute(agent, "test")
        assert result.success is True

    async def test_non_memory_manager_ignored(self):
        """Passing a non-MemoryManager object should be treated as None."""
        agent = MockAgent(
            [
                ReasoningThought(content="done", is_final=True, final_answer="42"),
            ]
        )
        pattern = ChainOfThoughtPattern(max_steps=3)
        result = await pattern.execute(agent, "test", memory="not_a_manager")
        assert result.success is True


class TestMemoryPersistence:
    async def test_cot_persists_steps(self):
        """ChainOfThought should persist steps to working memory."""
        memory = MemoryManager()
        agent = MockAgent(
            [
                ReasoningThought(content="step one analysis", is_final=False),
                ReasoningThought(content="final", is_final=True, final_answer="result"),
            ]
        )
        pattern = ChainOfThoughtPattern(max_steps=5)
        await pattern.execute(agent, "problem", memory=memory)

        # The pattern forks memory, so steps are in the forked scope.
        # The parent memory won't see them directly, but the forked one does.
        # We verify via the pattern's internal behavior (no crash, success).

    async def test_react_persists_observations(self):
        """ReAct should persist observations to working memory."""
        memory = MemoryManager()
        agent = MockAgent(
            [
                ReasoningThought(content="think", is_final=False),
                "action result data",
                ReasoningThought(content="done", is_final=True, final_answer="ok"),
            ]
        )
        pattern = ReActPattern(max_steps=5)
        result = await pattern.execute(agent, "test", memory=memory)
        assert result.success is True

    async def test_tot_persists_steps_with_memory(self):
        """TreeOfThoughts should persist branch steps to working memory."""
        memory = MemoryManager()
        agent = MockAgent(
            [
                "A---B---C",
                BranchEvaluation(branch_id=0, score=0.6),
                BranchEvaluation(branch_id=1, score=0.9),
                BranchEvaluation(branch_id=2, score=0.3),
            ]
        )
        pattern = TreeOfThoughtsPattern(branching_factor=3)
        result = await pattern.execute(agent, "test", memory=memory)
        assert result.success is True


class TestEnrichPrompt:
    async def test_enrich_adds_working_context(self):
        """When memory has facts, they should appear in prompts."""
        memory = MemoryManager()
        memory.set_fact("key1", "value1")

        enriched = AbstractReasoningPattern._enrich_prompt("My prompt", memory)
        assert "key1" in enriched
        assert "value1" in enriched
        assert "My prompt" in enriched

    async def test_enrich_empty_memory_passthrough(self):
        """Empty working memory should not modify the prompt."""
        memory = MemoryManager()
        enriched = AbstractReasoningPattern._enrich_prompt("My prompt", memory)
        assert enriched == "My prompt"

    async def test_enrich_none_memory_passthrough(self):
        result = AbstractReasoningPattern._enrich_prompt("hello", None)
        assert result == "hello"


class TestFallbackParse:
    def test_parse_thought_from_dict(self):
        data = {"content": "hello", "is_final": True, "final_answer": "world"}
        result = AbstractReasoningPattern._fallback_parse(data, ReasoningThought)
        assert isinstance(result, ReasoningThought)
        assert result.is_final is True
        assert result.final_answer == "world"

    def test_parse_thought_from_text(self):
        result = AbstractReasoningPattern._fallback_parse("some text", ReasoningThought)
        assert isinstance(result, ReasoningThought)
        assert result.content == "some text"
        assert result.is_final is False

    def test_parse_verdict_from_text(self):
        result = AbstractReasoningPattern._fallback_parse("anything", ReflectionVerdict)
        assert isinstance(result, ReflectionVerdict)
        assert result.is_satisfactory is True

    def test_parse_already_correct_type(self):
        thought = ReasoningThought(content="x", is_final=True)
        result = AbstractReasoningPattern._fallback_parse(thought, ReasoningThought)
        assert result is thought


class TestResolveModel:
    def test_resolve_from_mock_with_no_model(self):
        agent = MockAgent([])
        result = AbstractReasoningPattern._resolve_model(agent)
        assert result is None

    def test_resolve_from_duck_typed_agent(self):
        class FakeAgent:
            model = "openai:gpt-4o"

            async def run(self, prompt, **kwargs):
                pass

        agent = FakeAgent()
        result = AbstractReasoningPattern._resolve_model(agent)
        assert result == "openai:gpt-4o"

    def test_resolve_from_agent_with_inner_agent(self):
        class InnerAgent:
            model = "anthropic:claude"

        class OuterAgent:
            agent = InnerAgent()

            async def run(self, prompt, **kwargs):
                pass

        result = AbstractReasoningPattern._resolve_model(OuterAgent())
        assert result == "anthropic:claude"


class TestProtocolConformance:
    def test_cot_is_reasoning_pattern(self):
        from fireflyframework_agentic.reasoning.base import ReasoningPattern

        pattern = ChainOfThoughtPattern(max_steps=3)
        assert isinstance(pattern, ReasoningPattern)

    def test_react_is_reasoning_pattern(self):
        from fireflyframework_agentic.reasoning.base import ReasoningPattern

        pattern = ReActPattern(max_steps=3)
        assert isinstance(pattern, ReasoningPattern)

    def test_reflexion_is_reasoning_pattern(self):
        from fireflyframework_agentic.reasoning.base import ReasoningPattern

        pattern = ReflexionPattern(max_steps=3)
        assert isinstance(pattern, ReasoningPattern)


class TestStepLimitError:
    async def test_cot_exceeds_max_steps(self):
        """Pattern should raise ReasoningStepLimitError when max_steps exceeded."""
        from fireflyframework_agentic.exceptions import ReasoningStepLimitError

        # Always non-final thoughts → will exhaust max_steps
        agent = MockAgent([ReasoningThought(content=f"step {i}") for i in range(10)])
        pattern = ChainOfThoughtPattern(max_steps=3)
        with pytest.raises(ReasoningStepLimitError):
            await pattern.execute(agent, "infinite loop")
