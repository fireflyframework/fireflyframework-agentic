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

"""Tests for reasoning prompt templates."""

from __future__ import annotations

from fireflyframework_agentic.prompts.registry import prompt_registry
from fireflyframework_agentic.reasoning.prompts import (
    _ALL_TEMPLATES,
    COT_STEP_PROMPT,
    GOAL_DECOMPOSE_PROMPT,
    GOAL_PLAN_PHASE_PROMPT,
    PLAN_GENERATION_PROMPT,
    PLAN_REPLAN_PROMPT,
    PLAN_STEP_EXECUTION_PROMPT,
    REACT_THOUGHT_PROMPT,
    REFLEXION_CRITIQUE_PROMPT,
    REFLEXION_RETRY_PROMPT,
    TOT_BRANCH_PROMPT,
    TOT_EVALUATE_PROMPT,
)


class TestPromptTemplateRendering:
    def test_react_thought(self):
        rendered = REACT_THOUGHT_PROMPT.render(context="user asked about weather")
        assert "weather" in rendered.user
        assert "final" in rendered.user

    def test_cot_step(self):
        rendered = COT_STEP_PROMPT.render(problem="What is 2+2?", step_number="1")
        assert "2+2" in rendered.user
        assert "step 1" in rendered.user.lower()

    def test_cot_step_with_previous(self):
        rendered = COT_STEP_PROMPT.render(
            problem="What is 2+2?",
            previous_steps="Step 1: We need to add",
            step_number="2",
        )
        assert "Previous reasoning" in rendered.user
        assert "We need to add" in rendered.user

    def test_plan_generation(self):
        rendered = PLAN_GENERATION_PROMPT.render(goal="Build a REST API")
        assert "REST API" in rendered.user
        assert "step_1" in rendered.user or "steps" in rendered.user.lower()

    def test_plan_step_execution(self):
        rendered = PLAN_STEP_EXECUTION_PROMPT.render(
            step_id="step_1",
            goal="Build app",
            step_description="Set up database",
        )
        assert "step_1" in rendered.user
        assert "database" in rendered.user

    def test_plan_replan(self):
        rendered = PLAN_REPLAN_PROMPT.render(
            goal="Build app",
            failed_step="Deploy",
            error="Connection refused",
        )
        assert "Connection refused" in rendered.user
        assert "revised" in rendered.user.lower() or "remaining" in rendered.user.lower()

    def test_reflexion_critique(self):
        rendered = REFLEXION_CRITIQUE_PROMPT.render(question="What is Python?", answer="A programming language")
        assert "Python" in rendered.user
        assert "satisfactory" in rendered.user

    def test_reflexion_retry(self):
        rendered = REFLEXION_RETRY_PROMPT.render(
            original_prompt="What is Python?",
            issues=["too brief"],
            suggestions=["add more detail"],
        )
        assert "too brief" in rendered.user
        assert "add more detail" in rendered.user

    def test_tot_branch(self):
        rendered = TOT_BRANCH_PROMPT.render(branching_factor="3", problem="Design an API")
        assert "3" in rendered.user
        assert "API" in rendered.user

    def test_tot_evaluate(self):
        rendered = TOT_EVALUATE_PROMPT.render(problem="Design an API", branch_id="0", approach="RESTful approach")
        assert "RESTful" in rendered.user
        assert "score" in rendered.user.lower()

    def test_goal_decompose(self):
        rendered = GOAL_DECOMPOSE_PROMPT.render(goal="Build a feedback pipeline")
        assert "feedback pipeline" in rendered.user
        assert "phases" in rendered.user.lower()

    def test_goal_plan_phase(self):
        rendered = GOAL_PLAN_PHASE_PROMPT.render(phase="Data collection", goal="Build pipeline")
        assert "Data collection" in rendered.user


class TestPromptRegistration:
    def test_all_templates_registered(self):
        for template in _ALL_TEMPLATES:
            assert prompt_registry.has(template.name), f"{template.name} not registered"

    def test_template_count(self):
        assert len(_ALL_TEMPLATES) == 13

    def test_retrieve_from_registry(self):
        t = prompt_registry.get("reasoning:react:thought")
        assert t is REACT_THOUGHT_PROMPT
