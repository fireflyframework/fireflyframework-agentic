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

"""Goal Decomposition reasoning pattern: Goal -> Phases -> Tasks.

Hierarchically decomposes a high-level goal into structured
:class:`~fireflyframework_genai.reasoning.models.GoalPhase` objects
with typed task lists.  Each task can optionally be delegated to
another reasoning pattern (e.g. ReAct).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model

from fireflyframework_genai.prompts.template import PromptTemplate
from fireflyframework_genai.reasoning.base import AbstractReasoningPattern
from fireflyframework_genai.reasoning.models import (
    GoalDecompositionResult,
)
from fireflyframework_genai.reasoning.prompts import (
    GOAL_DECOMPOSE_PROMPT,
    GOAL_PLAN_PHASE_PROMPT,
    GOAL_TASK_EXECUTION_PROMPT,
)
from fireflyframework_genai.reasoning.trace import (
    ActionStep,
    ObservationStep,
    PlanStep,
    ReasoningResult,
    ReasoningStep,
    ReasoningTrace,
)
from fireflyframework_genai.types import AgentLike, UserContent

if TYPE_CHECKING:
    from fireflyframework_genai.validation.reviewer import OutputReviewer

logger = logging.getLogger(__name__)


class GoalDecompositionPattern(AbstractReasoningPattern):
    """Goal -> Phases -> Tasks.

    1. **Decompose** -- break the goal into :class:`GoalPhase` objects
       via structured output.
    2. **Plan** -- break each phase into tasks.
    3. **Execute** -- execute each task (optionally delegating).

    Parameters:
        max_steps: Maximum total tasks across all phases.
        task_pattern: An optional reasoning pattern to delegate individual
            tasks to.  If ``None``, tasks are executed directly by the agent.
        model: Optional LLM model for structured output calls.
        prompts: Optional prompt overrides.  Supported slots:
            ``"decompose"``, ``"plan_phase"``, ``"execute_task"``.
        reviewer: Optional :class:`OutputReviewer` for final output validation.
    """

    def __init__(
        self,
        *,
        max_steps: int = 20,
        task_pattern: Any | None = None,
        model: str | Model | None = None,
        prompts: dict[str, PromptTemplate] | None = None,
        reviewer: OutputReviewer | None = None,
        step_timeout: float | None = None,
    ) -> None:
        super().__init__(
            "goal_decomposition",
            max_steps=max_steps,
            model=model,
            prompts=prompts,
            reviewer=reviewer,
            step_timeout=step_timeout,
        )
        self._task_pattern = task_pattern

    async def execute(self, agent: AgentLike, input: str | Sequence[UserContent], **kwargs: Any) -> ReasoningResult:
        """Override execute for the full decomposition flow with memory support."""
        t_start = time.monotonic()
        logger.info("GoalDecomposition: starting...")
        trace = ReasoningTrace(pattern_name=self._name)
        raw_memory = kwargs.pop("memory", None)
        memory = self._init_memory(raw_memory, self._name)
        steps = 0

        # Phase 1: Decompose goal into structured phases
        decomposition = await self._decompose_goal(agent, input)
        phase_names = [p.name for p in decomposition.phases]
        logger.info("GoalDecomposition: %d phases: %s", len(phase_names), ", ".join(phase_names))
        plan_step = PlanStep(
            description=f"Decomposed into {len(decomposition.phases)} phases",
            sub_steps=phase_names,
        )
        trace.add_step(plan_step)
        self._persist_step(memory, plan_step, 1)
        steps += 1

        # Persist decomposition to working memory
        if memory is not None:
            memory.set_fact("reasoning:decomposition", decomposition.model_dump())

        all_results: list[str] = []

        for phase_idx, phase in enumerate(decomposition.phases):
            # Phase 2: Get tasks for this phase
            tasks = phase.tasks
            if not tasks:
                tasks = await self._plan_phase(agent, phase.name, str(input))
            logger.info(
                "GoalDecomposition: phase %d/%d '%s' — %d task(s)",
                phase_idx + 1,
                len(decomposition.phases),
                phase.name,
                len(tasks),
            )
            phase_step = PlanStep(
                description=f"Phase {phase_idx + 1}: {phase.name}",
                sub_steps=tasks,
            )
            trace.add_step(phase_step)
            self._persist_step(memory, phase_step, steps + 1)
            steps += 1

            for task_idx, task in enumerate(tasks):
                if steps >= self._max_steps:
                    logger.info("GoalDecomposition: max_steps reached, stopping")
                    break

                logger.info("GoalDecomposition: executing task %d/%d: %s", task_idx + 1, len(tasks), task[:100])
                result = await self._execute_task(agent, task, goal=str(input), memory=memory, **kwargs)
                all_results.append(result)
                action_step = ActionStep(tool_name="execute_task", tool_args={"task": task[:100]})
                obs_step = ObservationStep(content=result[:200], source="goal_decomposition")
                trace.add_step(action_step)
                trace.add_step(obs_step)
                self._persist_step(memory, obs_step, steps + 1)
                steps += 1

        trace.complete()

        output: Any = all_results
        if self._reviewer is not None:
            output = await self._review_output({"agent": agent}, output)

        if memory is not None:
            memory.set_fact("reasoning:output", str(output)[:1000] if output else "")

        logger.info("GoalDecomposition: completed in %.1fs (%d steps)", time.monotonic() - t_start, steps)
        return ReasoningResult(
            output=output,
            trace=trace,
            steps_taken=steps,
            success=True,
        )

    async def _decompose_goal(self, agent: AgentLike, goal: str | Sequence[Any]) -> GoalDecompositionResult:
        """Break a high-level goal into structured phases."""
        template = self._get_prompt("decompose", GOAL_DECOMPOSE_PROMPT)
        prompt = template.render(goal=str(goal))
        decomp = await self._structured_run(agent, prompt, GoalDecompositionResult)
        if not decomp.goal:
            decomp.goal = str(goal)
        return decomp

    async def _plan_phase(self, agent: AgentLike, phase: str, goal: str) -> list[str]:
        """Break a phase into concrete tasks."""
        template = self._get_prompt("plan_phase", GOAL_PLAN_PHASE_PROMPT)
        prompt = template.render(phase=phase, goal=goal)
        result = await agent.run(prompt)
        text = str(result.output if hasattr(result, "output") else result)
        return [t.strip() for t in text.strip().split("\n") if t.strip()]

    async def _execute_task(
        self,
        agent: AgentLike,
        task: str,
        *,
        goal: str = "",
        memory: Any = None,
        **kwargs: Any,
    ) -> str:
        """Execute a single task, optionally delegating to a sub-pattern."""
        if self._task_pattern is not None:
            sub_result: ReasoningResult = await self._task_pattern.execute(agent, task, memory=memory, **kwargs)
            return str(sub_result.output)
        template = self._get_prompt("execute_task", GOAL_TASK_EXECUTION_PROMPT)
        prompt = template.render(goal=goal, task=task)
        prompt = self._enrich_prompt(prompt, memory)
        result = await agent.run(prompt)
        return str(result.output if hasattr(result, "output") else result)

    # Unused hooks (execute is fully overridden)
    async def _reason(self, state: dict[str, Any]) -> ReasoningStep | None:
        return None

    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        return None
