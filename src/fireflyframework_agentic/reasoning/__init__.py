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

"""Reasoning subpackage -- patterns, traces, models, prompts, registry, and pipeline."""

from fireflyframework_agentic.reasoning.base import (
    AbstractReasoningPattern,
    ReasoningPattern,
)
from fireflyframework_agentic.reasoning.chain_of_thought import ChainOfThoughtPattern
from fireflyframework_agentic.reasoning.goal_decomposition import GoalDecompositionPattern
from fireflyframework_agentic.reasoning.models import (
    BranchEvaluation,
    BranchList,
    GoalDecompositionResult,
    GoalPhase,
    PlanStepDef,
    ReasoningAction,
    ReasoningPlan,
    ReasoningThought,
    ReflectionVerdict,
    StepStatus,
)
from fireflyframework_agentic.reasoning.pipeline import ReasoningPipeline
from fireflyframework_agentic.reasoning.plan_and_execute import PlanAndExecutePattern
from fireflyframework_agentic.reasoning.prompts import (
    COT_STEP_PROMPT,
    GOAL_DECOMPOSE_PROMPT,
    GOAL_PLAN_PHASE_PROMPT,
    GOAL_TASK_EXECUTION_PROMPT,
    PLAN_GENERATION_PROMPT,
    PLAN_REPLAN_PROMPT,
    PLAN_STEP_EXECUTION_PROMPT,
    REACT_ACTION_PROMPT,
    REACT_THOUGHT_PROMPT,
    REFLEXION_CRITIQUE_PROMPT,
    REFLEXION_RETRY_PROMPT,
    TOT_BRANCH_PROMPT,
    TOT_EVALUATE_PROMPT,
    register_reasoning_prompts,
)
from fireflyframework_agentic.reasoning.react import ReActPattern
from fireflyframework_agentic.reasoning.reflexion import ReflexionPattern
from fireflyframework_agentic.reasoning.registry import (
    ReasoningPatternRegistry,
    reasoning_registry,
)
from fireflyframework_agentic.reasoning.trace import (
    ActionStep,
    ObservationStep,
    PlanStep,
    ReasoningResult,
    ReasoningStep,
    ReasoningTrace,
    ReflectionStep,
    ThoughtStep,
)
from fireflyframework_agentic.reasoning.tree_of_thoughts import TreeOfThoughtsPattern

__all__ = [
    "AbstractReasoningPattern",
    "ActionStep",
    "BranchEvaluation",
    "BranchList",
    "COT_STEP_PROMPT",
    "ChainOfThoughtPattern",
    "GOAL_DECOMPOSE_PROMPT",
    "GOAL_PLAN_PHASE_PROMPT",
    "GOAL_TASK_EXECUTION_PROMPT",
    "GoalDecompositionPattern",
    "GoalDecompositionResult",
    "GoalPhase",
    "ObservationStep",
    "PLAN_GENERATION_PROMPT",
    "PLAN_REPLAN_PROMPT",
    "PLAN_STEP_EXECUTION_PROMPT",
    "PlanAndExecutePattern",
    "PlanStep",
    "PlanStepDef",
    "REACT_ACTION_PROMPT",
    "REACT_THOUGHT_PROMPT",
    "REFLEXION_CRITIQUE_PROMPT",
    "REFLEXION_RETRY_PROMPT",
    "ReActPattern",
    "ReasoningAction",
    "ReasoningPattern",
    "ReasoningPatternRegistry",
    "ReasoningPipeline",
    "ReasoningPlan",
    "ReasoningResult",
    "ReasoningStep",
    "ReasoningThought",
    "ReasoningTrace",
    "ReflectionStep",
    "ReflectionVerdict",
    "ReflexionPattern",
    "StepStatus",
    "TOT_BRANCH_PROMPT",
    "TOT_EVALUATE_PROMPT",
    "ThoughtStep",
    "TreeOfThoughtsPattern",
    "reasoning_registry",
    "register_reasoning_prompts",
]
