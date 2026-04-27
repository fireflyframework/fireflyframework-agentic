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

"""Integration tests for reasoning patterns with structured outputs.

Uses a mock agent that returns predictable outputs so we can verify
pattern flow, structured model parsing, and prompt template usage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fireflyframework_agentic.reasoning.chain_of_thought import ChainOfThoughtPattern
from fireflyframework_agentic.reasoning.goal_decomposition import GoalDecompositionPattern
from fireflyframework_agentic.reasoning.models import (
    BranchEvaluation,
    GoalDecompositionResult,
    GoalPhase,
    PlanStepDef,
    ReasoningPlan,
    ReasoningThought,
    ReflectionVerdict,
)
from fireflyframework_agentic.reasoning.plan_and_execute import PlanAndExecutePattern
from fireflyframework_agentic.reasoning.react import ReActPattern
from fireflyframework_agentic.reasoning.reflexion import ReflexionPattern
from fireflyframework_agentic.reasoning.tree_of_thoughts import TreeOfThoughtsPattern


@dataclass
class MockResult:
    """Mock agent run result."""

    output: Any = ""


class MockAgent:
    """Agent that returns pre-configured responses in sequence."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_count = 0
        self.prompts: list[str] = []

    async def run(self, prompt: Any, **kwargs: Any) -> MockResult:
        self.prompts.append(str(prompt))
        resp = self._responses[self._call_count] if self._call_count < len(self._responses) else "default response"
        self._call_count += 1
        return MockResult(output=resp)


class TestReActPatternStructured:
    async def test_structured_thought_final(self):
        """ReAct should stop when thought.is_final is True."""
        agent = MockAgent(
            [
                # Iteration 1: thought (non-final) + action + observe
                ReasoningThought(content="thinking about it", is_final=False),
                "action result 1",
                # Iteration 2: thought (final) -> stops before acting
                ReasoningThought(content="found the answer", is_final=True, final_answer="42"),
            ]
        )
        pattern = ReActPattern(max_steps=5)
        result = await pattern.execute(agent, "What is the answer?")
        assert result.success is True
        assert result.output == "42"
        assert result.steps_taken <= 5

    async def test_text_fallback(self):
        """When agent returns plain text, it should be treated as non-final."""
        agent = MockAgent(
            [
                # Iteration 1: thought (text fallback, non-final) + action
                "still thinking",
                "action result",
                # Iteration 2: thought (final)
                ReasoningThought(content="done", is_final=True, final_answer="ok"),
            ]
        )
        pattern = ReActPattern(max_steps=5)
        result = await pattern.execute(agent, "test")
        assert result.success is True

    async def test_prompts_override(self):
        """Custom prompts should be used when provided."""
        from fireflyframework_agentic.prompts.template import PromptTemplate, PromptVariable

        custom = PromptTemplate(
            "custom:react:thought",
            "CUSTOM: {{ context }}",
            variables=[PromptVariable(name="context")],
        )
        agent = MockAgent(
            [
                ReasoningThought(content="x", is_final=True, final_answer="y"),
            ]
        )
        pattern = ReActPattern(prompts={"thought": custom})
        await pattern.execute(agent, "test")
        assert "CUSTOM:" in agent.prompts[0]


class TestChainOfThoughtPatternStructured:
    async def test_structured_conclusion(self):
        """CoT should stop when thought.is_final is True."""
        agent = MockAgent(
            [
                ReasoningThought(content="Step 1: analyze", is_final=False),
                ReasoningThought(content="Step 2: conclude", is_final=True, final_answer="150km"),
            ]
        )
        pattern = ChainOfThoughtPattern(max_steps=5)
        result = await pattern.execute(agent, "How far does a train go?")
        assert result.success is True
        assert result.output == "150km"

    async def test_chain_accumulates(self):
        """Each step should appear in the next prompt's previous_steps."""
        agent = MockAgent(
            [
                ReasoningThought(content="first step"),
                ReasoningThought(content="second step", is_final=True, final_answer="done"),
            ]
        )
        pattern = ChainOfThoughtPattern(max_steps=5)
        await pattern.execute(agent, "problem")
        # Second prompt should reference "first step"
        assert "first step" in agent.prompts[1]


class TestPlanAndExecutePatternStructured:
    async def test_structured_plan(self):
        """Should generate and execute a structured plan."""
        plan = ReasoningPlan(
            goal="Build app",
            steps=[
                PlanStepDef(id="step_1", description="Design"),
                PlanStepDef(id="step_2", description="Code"),
            ],
        )
        agent = MockAgent(
            [
                plan,  # plan generation
                "designed",  # execute step 1 (thought + act)
                "coded",  # execute step 2
            ]
        )
        pattern = PlanAndExecutePattern(max_steps=10)
        result = await pattern.execute(agent, "Build app")
        assert result.success is True
        assert isinstance(result.output, list)

    async def test_text_plan_fallback(self):
        """When agent returns plain text for plan, it should be parsed as lines."""
        agent = MockAgent(
            [
                "1. Design\n2. Code\n3. Test",  # plan generation
                "designed",
                "coded",
                "tested",
            ]
        )
        pattern = PlanAndExecutePattern(max_steps=10)
        result = await pattern.execute(agent, "Build app")
        assert result.success is True


class TestReflexionPatternStructured:
    async def test_satisfactory_on_first_try(self):
        """Reflexion should stop when verdict.is_satisfactory is True."""
        agent = MockAgent(
            [
                "My answer is 42",
                ReflectionVerdict(is_satisfactory=True),
            ]
        )
        pattern = ReflexionPattern(max_steps=3)
        result = await pattern.execute(agent, "What is 6*7?")
        assert result.success is True
        assert result.output == "My answer is 42"

    async def test_retry_on_issues(self):
        """Reflexion should retry when verdict has issues."""
        agent = MockAgent(
            [
                "first attempt",
                ReflectionVerdict(
                    is_satisfactory=False,
                    issues=["too brief"],
                    suggestions=["add more detail"],
                ),
                "improved attempt with more detail",
                ReflectionVerdict(is_satisfactory=True),
            ]
        )
        pattern = ReflexionPattern(max_steps=5)
        result = await pattern.execute(agent, "Explain Python")
        assert result.success is True
        assert "improved" in result.output


class TestTreeOfThoughtsPatternStructured:
    async def test_structured_evaluation(self):
        """ToT should use BranchEvaluation for scoring."""
        agent = MockAgent(
            [
                "Approach A---Approach B---Approach C",  # branches
                BranchEvaluation(branch_id=0, score=0.6, reasoning="ok"),
                BranchEvaluation(branch_id=1, score=0.9, reasoning="great"),
                BranchEvaluation(branch_id=2, score=0.3, reasoning="weak"),
            ]
        )
        pattern = TreeOfThoughtsPattern(branching_factor=3)
        result = await pattern.execute(agent, "Design an API")
        assert result.success is True
        # Best branch should be selected (branch_id=1 -> "Approach B")
        assert "Approach B" in result.output

    async def test_numeric_fallback(self):
        """When agent returns plain numbers, they should be parsed as scores."""
        agent = MockAgent(
            [
                "A---B---C",
                "0.8",
                "0.5",
                "0.3",
            ]
        )
        pattern = TreeOfThoughtsPattern(branching_factor=3)
        result = await pattern.execute(agent, "test")
        assert result.success is True
        assert "A" in result.output  # highest score branch


class TestGoalDecompositionPatternStructured:
    async def test_structured_decomposition(self):
        """GoalDecomposition should use GoalDecompositionResult."""
        decomp = GoalDecompositionResult(
            goal="Build pipeline",
            phases=[
                GoalPhase(name="Design", tasks=["wireframes"]),
                GoalPhase(name="Build", tasks=["code"]),
            ],
        )
        agent = MockAgent(
            [
                decomp,  # decompose goal (via _structured_run fallback)
                "wireframed",  # execute task 1
                "coded",  # execute task 2
            ]
        )
        pattern = GoalDecompositionPattern(max_steps=10)
        result = await pattern.execute(agent, "Build pipeline")
        assert result.success is True
        assert isinstance(result.output, list)
        assert len(result.output) == 2

    async def test_text_fallback(self):
        """When agent returns text for decomposition, parse as lines."""
        agent = MockAgent(
            [
                "Phase 1: Design\nPhase 2: Build",  # decomposition (text fallback)
                "task 1",  # plan phase tasks for Phase 1
                "done 1",  # execute task 1
                "task 2",  # plan phase tasks for Phase 2
                "done 2",  # execute task 2
            ]
        )
        pattern = GoalDecompositionPattern(max_steps=15)
        result = await pattern.execute(agent, "Build app")
        assert result.success is True
