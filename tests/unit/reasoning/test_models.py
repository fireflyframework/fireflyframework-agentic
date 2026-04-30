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

"""Tests for structured reasoning models."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.reasoning.models import (
    BranchEvaluation,
    GoalDecompositionResult,
    GoalPhase,
    PlanStepDef,
    ReasoningAction,
    ReasoningPlan,
    ReasoningThought,
    ReflectionVerdict,
    StepStatus,
)


class TestReasoningThought:
    def test_defaults(self):
        t = ReasoningThought(content="thinking")
        assert t.content == "thinking"
        assert t.confidence is None
        assert t.is_final is False
        assert t.final_answer is None

    def test_final_thought(self):
        t = ReasoningThought(content="done", is_final=True, final_answer="42", confidence=0.95)
        assert t.is_final is True
        assert t.final_answer == "42"
        assert t.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(ValueError):
            ReasoningThought(content="x", confidence=1.5)
        with pytest.raises(ValueError):
            ReasoningThought(content="x", confidence=-0.1)

    def test_from_dict(self):
        data = {"content": "step 1", "is_final": False}
        t = ReasoningThought.model_validate(data)
        assert t.content == "step 1"


class TestReasoningAction:
    def test_defaults(self):
        a = ReasoningAction(tool_name="search")
        assert a.tool_name == "search"
        assert a.tool_args == {}
        assert a.reasoning == ""

    def test_with_args(self):
        a = ReasoningAction(tool_name="calc", tool_args={"expr": "1+1"}, reasoning="need math")
        assert a.tool_args["expr"] == "1+1"


class TestStepStatus:
    def test_values(self):
        assert StepStatus.PENDING == "pending"
        assert StepStatus.RUNNING == "running"
        assert StepStatus.COMPLETED == "completed"
        assert StepStatus.FAILED == "failed"
        assert StepStatus.SKIPPED == "skipped"


class TestPlanStepDef:
    def test_defaults(self):
        s = PlanStepDef(id="step_1", description="Do thing")
        assert s.status == StepStatus.PENDING
        assert s.dependencies == []
        assert s.output is None

    def test_with_deps(self):
        s = PlanStepDef(id="step_2", description="After", dependencies=["step_1"])
        assert s.dependencies == ["step_1"]

    def test_status_update(self):
        s = PlanStepDef(id="s1", description="x")
        s.status = StepStatus.COMPLETED
        s.output = "done"
        assert s.status == StepStatus.COMPLETED
        assert s.output == "done"


class TestReasoningPlan:
    def test_empty_plan(self):
        p = ReasoningPlan(goal="test")
        assert p.goal == "test"
        assert p.steps == []

    def test_with_steps(self):
        p = ReasoningPlan(
            goal="build app",
            steps=[
                PlanStepDef(id="s1", description="design"),
                PlanStepDef(id="s2", description="code", dependencies=["s1"]),
            ],
        )
        assert len(p.steps) == 2
        assert p.steps[1].dependencies == ["s1"]

    def test_from_dict(self):
        data = {
            "goal": "test",
            "steps": [{"id": "s1", "description": "first"}],
        }
        p = ReasoningPlan.model_validate(data)
        assert p.steps[0].id == "s1"


class TestReflectionVerdict:
    def test_satisfactory(self):
        v = ReflectionVerdict(is_satisfactory=True)
        assert v.issues == []
        assert v.suggestions == []

    def test_not_satisfactory(self):
        v = ReflectionVerdict(
            is_satisfactory=False,
            issues=["lacks detail"],
            suggestions=["add examples"],
        )
        assert not v.is_satisfactory
        assert len(v.issues) == 1


class TestBranchEvaluation:
    def test_valid(self):
        e = BranchEvaluation(branch_id=0, score=0.8, reasoning="good")
        assert e.score == 0.8

    def test_score_bounds(self):
        with pytest.raises(ValueError):
            BranchEvaluation(branch_id=0, score=1.5)
        with pytest.raises(ValueError):
            BranchEvaluation(branch_id=0, score=-0.1)


class TestGoalPhase:
    def test_defaults(self):
        p = GoalPhase(name="Phase 1")
        assert p.description == ""
        assert p.tasks == []

    def test_with_tasks(self):
        p = GoalPhase(name="Design", tasks=["wireframes", "architecture"])
        assert len(p.tasks) == 2


class TestGoalDecompositionResult:
    def test_structure(self):
        r = GoalDecompositionResult(
            goal="build app",
            phases=[
                GoalPhase(name="Design", tasks=["wireframes"]),
                GoalPhase(name="Implement", tasks=["code", "test"]),
            ],
        )
        assert r.goal == "build app"
        assert len(r.phases) == 2
        assert r.phases[1].tasks == ["code", "test"]

    def test_from_dict(self):
        data = {
            "goal": "x",
            "phases": [{"name": "A", "tasks": ["a1"]}],
        }
        r = GoalDecompositionResult.model_validate(data)
        assert r.phases[0].name == "A"
