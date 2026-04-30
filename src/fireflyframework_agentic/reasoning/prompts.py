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

"""Configurable prompt templates for reasoning patterns.

Each reasoning pattern uses one or more :class:`PromptTemplate` instances
for its LLM calls.  By default, the built-in templates defined here are
used.  Users can override any prompt by passing a ``prompts`` dict to
the pattern constructor::

    pattern = ReActPattern(
        prompts={"thought": my_custom_thought_prompt},
    )

All built-in templates are registered in the global
:data:`~fireflyframework_agentic.prompts.registry.prompt_registry` under
the ``reasoning:`` namespace.
"""

from __future__ import annotations

from fireflyframework_agentic.prompts.registry import prompt_registry
from fireflyframework_agentic.prompts.template import PromptTemplate

# ---------------------------------------------------------------------------
# ReAct
# ---------------------------------------------------------------------------

REACT_THOUGHT_PROMPT = PromptTemplate(
    name="reasoning:react:thought",
    system_template="",
    user_template=(
        "You are reasoning about a problem step by step using a "
        "Reason-Act-Observe loop.\n\n"
        "Context:\n{{ context }}\n\n"
        "Analyse the current state. Decide whether you can provide a "
        "final answer or need to take another action. If you have enough "
        "information, mark your answer as final and include it. Rate your "
        "confidence between 0.0 and 1.0."
    ),
    version="2.0.0",
    description="Generates a structured thought during a ReAct reasoning step.",
    required_variables=["context"],
)

REACT_ACTION_PROMPT = PromptTemplate(
    name="reasoning:react:action",
    system_template="",
    user_template=(
        "Based on your reasoning, take the next step to solve the problem.\n\n"
        "Original problem:\n{{ problem }}\n\n"
        "Your current thinking:\n{{ thought }}\n\n"
        "Provide a clear, actionable response that advances toward the answer."
    ),
    version="1.0.0",
    description="Executes an action step during ReAct reasoning.",
    required_variables=["problem", "thought"],
)

# ---------------------------------------------------------------------------
# Chain of Thought
# ---------------------------------------------------------------------------

COT_STEP_PROMPT = PromptTemplate(
    name="reasoning:cot:step",
    system_template="",
    user_template=(
        "Problem: {{ problem }}\n\n"
        "{% if previous_steps %}"
        "Previous reasoning steps:\n{{ previous_steps }}\n\n"
        "{% endif %}"
        "Generate step {{ step_number }} of your reasoning. Build on the "
        "previous steps and advance toward a solution. When you have "
        "reached a definitive answer, mark it as final and include your "
        "answer. Rate your confidence between 0.0 and 1.0."
    ),
    version="2.0.0",
    description="Generates a single chain-of-thought reasoning step.",
    required_variables=["problem", "step_number"],
)

# ---------------------------------------------------------------------------
# Plan-and-Execute
# ---------------------------------------------------------------------------

PLAN_GENERATION_PROMPT = PromptTemplate(
    name="reasoning:plan:generate",
    system_template="",
    user_template=(
        "Create a structured execution plan for the following goal.\n\n"
        "Goal: {{ goal }}\n\n"
        "Break this into concrete, ordered steps. Each step should have a "
        "unique ID (step_1, step_2, ...), a clear description, and any "
        "dependencies on prior steps."
    ),
    version="2.0.0",
    description="Generates a structured execution plan from a goal.",
    required_variables=["goal"],
)

PLAN_STEP_EXECUTION_PROMPT = PromptTemplate(
    name="reasoning:plan:execute_step",
    system_template="",
    user_template=(
        "You are executing step {{ step_id }} of a plan.\n\n"
        "Overall goal: {{ goal }}\n"
        "Step: {{ step_description }}\n"
        "{% if previous_results %}"
        "Results from previous steps:\n{{ previous_results }}\n"
        "{% endif %}\n"
        "Execute this step and provide a clear, actionable result."
    ),
    version="1.0.0",
    description="Executes a single step within a plan.",
    required_variables=["step_id", "goal", "step_description"],
)

PLAN_REPLAN_PROMPT = PromptTemplate(
    name="reasoning:plan:replan",
    system_template="",
    user_template=(
        "A step in your plan has failed and you need to adjust.\n\n"
        "Original goal: {{ goal }}\n"
        "Failed step: {{ failed_step }}\n"
        "Error: {{ error }}\n"
        "Completed steps so far:\n{{ completed_steps }}\n\n"
        "Generate a revised plan for the remaining work. Include only the "
        "steps that still need to be done."
    ),
    version="1.0.0",
    description="Generates a revised plan after a step failure.",
    required_variables=["goal", "failed_step", "error"],
)

# ---------------------------------------------------------------------------
# Reflexion
# ---------------------------------------------------------------------------

REFLEXION_CRITIQUE_PROMPT = PromptTemplate(
    name="reasoning:reflexion:critique",
    system_template="",
    user_template=(
        "Critically evaluate the following answer.\n\n"
        "Original question: {{ question }}\n"
        "Answer: {{ answer }}\n\n"
        "Determine if the answer is satisfactory. If not, identify "
        "specific issues and provide concrete suggestions for improvement."
    ),
    version="2.0.0",
    description="Structured self-evaluation for reflexion reasoning.",
    required_variables=["question", "answer"],
)

REFLEXION_RETRY_PROMPT = PromptTemplate(
    name="reasoning:reflexion:retry",
    system_template="",
    user_template=(
        "{{ original_prompt }}\n\n"
        "Your previous answer had these issues:\n"
        "{% for issue in issues %}- {{ issue }}\n{% endfor %}\n"
        "Suggestions for improvement:\n"
        "{% for suggestion in suggestions %}- {{ suggestion }}\n{% endfor %}\n"
        "Please provide an improved answer addressing all feedback."
    ),
    version="1.0.0",
    description="Retry prompt with incorporated feedback for reflexion.",
    required_variables=["original_prompt", "issues", "suggestions"],
)

# ---------------------------------------------------------------------------
# Tree of Thoughts
# ---------------------------------------------------------------------------

TOT_BRANCH_PROMPT = PromptTemplate(
    name="reasoning:tot:branch",
    system_template="",
    user_template=(
        "Generate {{ branching_factor }} distinct approaches to solve this "
        "problem.\n\n"
        "Problem: {{ problem }}\n\n"
        "Each approach should represent a fundamentally different strategy."
    ),
    version="2.0.0",
    description="Generates multiple reasoning branches for Tree of Thoughts.",
    required_variables=["branching_factor", "problem"],
)

TOT_EVALUATE_PROMPT = PromptTemplate(
    name="reasoning:tot:evaluate",
    system_template="",
    user_template=(
        "Evaluate this approach to a problem.\n\n"
        "Problem: {{ problem }}\n"
        "Approach (branch {{ branch_id }}):\n{{ approach }}\n\n"
        "Score the quality of this approach between 0.0 and 1.0, and "
        "briefly explain your reasoning. Use the branch_id {{ branch_id }}."
    ),
    version="2.0.0",
    description="Evaluates a single reasoning branch for Tree of Thoughts.",
    required_variables=["problem", "branch_id", "approach"],
)

# ---------------------------------------------------------------------------
# Goal Decomposition
# ---------------------------------------------------------------------------

GOAL_DECOMPOSE_PROMPT = PromptTemplate(
    name="reasoning:goal:decompose",
    system_template="",
    user_template=(
        "Decompose this high-level goal into ordered phases.\n\n"
        "Goal: {{ goal }}\n\n"
        "Each phase should have a name, description, and a list of "
        "concrete, actionable tasks."
    ),
    version="2.0.0",
    description="Decomposes a goal into structured phases with tasks.",
    required_variables=["goal"],
)

GOAL_PLAN_PHASE_PROMPT = PromptTemplate(
    name="reasoning:goal:plan_phase",
    system_template="",
    user_template=(
        "Break this phase into concrete, actionable tasks.\n\n"
        "Phase: {{ phase }}\n"
        "Overall goal: {{ goal }}\n\n"
        "Return each task as a clear, actionable item."
    ),
    version="1.0.0",
    description="Plans concrete tasks for a single goal phase.",
    required_variables=["phase", "goal"],
)

GOAL_TASK_EXECUTION_PROMPT = PromptTemplate(
    name="reasoning:goal:execute_task",
    system_template="",
    user_template=(
        "Execute the following task as part of a larger goal.\n\n"
        "Overall goal: {{ goal }}\n"
        "Current task: {{ task }}\n\n"
        "Provide a clear, complete result for this task."
    ),
    version="1.0.0",
    description="Executes a single task within a goal decomposition.",
    required_variables=["goal", "task"],
)

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_ALL_TEMPLATES = [
    REACT_THOUGHT_PROMPT,
    REACT_ACTION_PROMPT,
    COT_STEP_PROMPT,
    PLAN_GENERATION_PROMPT,
    PLAN_STEP_EXECUTION_PROMPT,
    PLAN_REPLAN_PROMPT,
    REFLEXION_CRITIQUE_PROMPT,
    REFLEXION_RETRY_PROMPT,
    TOT_BRANCH_PROMPT,
    TOT_EVALUATE_PROMPT,
    GOAL_DECOMPOSE_PROMPT,
    GOAL_PLAN_PHASE_PROMPT,
    GOAL_TASK_EXECUTION_PROMPT,
]


def register_reasoning_prompts() -> None:
    """Register all built-in reasoning prompt templates in the global registry."""
    for template in _ALL_TEMPLATES:
        if not prompt_registry.has(template.name):
            prompt_registry.register(template)


# Auto-register on import
register_reasoning_prompts()
