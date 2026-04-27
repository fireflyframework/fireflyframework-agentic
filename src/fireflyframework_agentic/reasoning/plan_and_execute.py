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

"""Plan-and-Execute reasoning pattern: Goal -> Plan -> Execute steps.

The agent first generates a structured :class:`ReasoningPlan` with typed
:class:`PlanStepDef` items, then executes each step sequentially with
status tracking.  Optionally, the plan can be revised after step failures.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model

from fireflyframework_agentic.exceptions import ReasoningError
from fireflyframework_agentic.prompts.template import PromptTemplate
from fireflyframework_agentic.reasoning.base import AbstractReasoningPattern
from fireflyframework_agentic.reasoning.models import (
    PlanStepDef,
    ReasoningPlan,
    StepStatus,
)
from fireflyframework_agentic.reasoning.prompts import (
    PLAN_GENERATION_PROMPT,
    PLAN_REPLAN_PROMPT,
    PLAN_STEP_EXECUTION_PROMPT,
)
from fireflyframework_agentic.reasoning.trace import (
    ActionStep,
    ObservationStep,
    PlanStep,
    ReasoningStep,
    ThoughtStep,
)

if TYPE_CHECKING:
    from fireflyframework_agentic.validation.reviewer import OutputReviewer

logger = logging.getLogger(__name__)


class PlanAndExecutePattern(AbstractReasoningPattern):
    """Goal -> Plan -> Execute with structured step tracking.

    1. **Plan** -- generates a :class:`ReasoningPlan` via structured output.
    2. **Execute** -- each :class:`PlanStepDef` is executed in order,
       with ``status`` updated to ``running`` → ``completed`` / ``failed``.
    3. Optionally **replan** after a step failure.

    Parameters:
        max_steps: Maximum iterations (one per plan step).
        allow_replan: Whether the agent may revise the plan after failure.
        model: Optional LLM model for structured output calls.
        prompts: Optional prompt overrides.  Supported slots:
            ``"plan"``, ``"execute_step"``, ``"replan"``.
        reviewer: Optional :class:`OutputReviewer` for final output validation.
    """

    def __init__(
        self,
        *,
        max_steps: int = 15,
        allow_replan: bool = False,
        model: str | Model | None = None,
        prompts: dict[str, PromptTemplate] | None = None,
        reviewer: OutputReviewer | None = None,
        step_timeout: float | None = None,
    ) -> None:
        super().__init__(
            "plan_and_execute",
            max_steps=max_steps,
            model=model,
            prompts=prompts,
            reviewer=reviewer,
            step_timeout=step_timeout,
        )
        self._allow_replan = allow_replan

    async def _reason(self, state: dict[str, Any]) -> ReasoningStep | None:
        if "plan" not in state:
            logger.info("Generating execution plan...")
            plan = await self._generate_plan(state)
            state["plan"] = plan
            state["plan_index"] = 0
            state["results"] = []
            step_descs = [s.description for s in plan.steps]
            logger.info("Plan generated with %d steps:", len(plan.steps))
            for i, desc in enumerate(step_descs, 1):
                logger.info("  %d. %s", i, desc[:100])
            return PlanStep(
                description=f"Generated plan with {len(plan.steps)} steps",
                sub_steps=step_descs,
            )

        plan: ReasoningPlan = state["plan"]
        idx = state.get("plan_index", 0)
        if idx < len(plan.steps):
            desc = plan.steps[idx].description
            logger.info("Preparing step %d/%d: %s", idx + 1, len(plan.steps), desc[:100])
            return ThoughtStep(content=f"Executing step {idx + 1}/{len(plan.steps)}: {desc}")
        return None

    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        plan: ReasoningPlan = state["plan"]
        idx = state.get("plan_index", 0)
        if idx >= len(plan.steps):
            return None

        step_def = plan.steps[idx]
        step_def.status = StepStatus.RUNNING
        logger.info("Executing step '%s': %s", step_def.id, step_def.description[:100])
        t0 = time.monotonic()

        try:
            output = await self._execute_step(state, step_def)
            step_def.status = StepStatus.COMPLETED
            step_def.output = output
            state["results"].append(output)
            state["plan_index"] = idx + 1
            state["output"] = output
            elapsed = time.monotonic() - t0
            logger.info(
                "Step '%s' completed in %.1fs (%d/%d)",
                step_def.id,
                elapsed,
                idx + 1,
                len(plan.steps),
            )
        except Exception as exc:
            step_def.status = StepStatus.FAILED
            step_def.output = str(exc)
            elapsed = time.monotonic() - t0
            logger.warning("Plan step '%s' failed after %.1fs: %s", step_def.id, elapsed, exc)
            if self._allow_replan:
                await self._replan(state, step_def, str(exc))
            else:
                state["plan_index"] = idx + 1  # skip failed step

        return ActionStep(tool_name="execute_step", tool_args={"step": step_def.description[:100]})

    async def _observe(self, state: dict[str, Any], action: ReasoningStep | None) -> ReasoningStep | None:
        results = state.get("results", [])
        if results:
            return ObservationStep(content=str(results[-1])[:200], source="plan_execution")
        return None

    async def _should_continue(self, state: dict[str, Any]) -> bool:
        plan: ReasoningPlan = state.get("plan", ReasoningPlan(goal=""))
        remaining = len(plan.steps) - state.get("plan_index", 0)
        if remaining > 0:
            logger.debug("  %d step(s) remaining", remaining)
        return remaining > 0

    async def _extract_output(self, state: dict[str, Any]) -> Any:
        return state.get("results", [])

    # -- Plan helpers --------------------------------------------------------

    async def _generate_plan(self, state: dict[str, Any]) -> ReasoningPlan:
        """Generate a structured plan from the goal."""
        agent = state["agent"]
        memory = state.get("memory")
        goal = str(state["input"])
        template = self._get_prompt("plan", PLAN_GENERATION_PROMPT)
        prompt = template.render(goal=goal)
        prompt = self._enrich_prompt(prompt, memory)

        logger.debug("Calling LLM for plan generation...")
        t0 = time.monotonic()
        plan = await self._structured_run(agent, prompt, ReasoningPlan)
        logger.debug("Plan generation completed in %.1fs", time.monotonic() - t0)

        if not plan.goal:
            plan.goal = goal
        # Persist plan to working memory
        if memory is not None:
            memory.set_fact("reasoning:plan", plan.model_dump())
        return plan

    async def _execute_step(self, state: dict[str, Any], step_def: PlanStepDef) -> str:
        """Execute a single plan step.

        Applies :attr:`_step_timeout` when set.
        """
        agent = state["agent"]
        memory = state.get("memory")
        plan: ReasoningPlan = state["plan"]
        completed = [s for s in plan.steps if s.status == StepStatus.COMPLETED]
        prev_results = "\n".join(f"{s.id}: {s.output}" for s in completed if s.output) if completed else ""

        template = self._get_prompt("execute_step", PLAN_STEP_EXECUTION_PROMPT)
        prompt = template.render(
            step_id=step_def.id,
            goal=plan.goal,
            step_description=step_def.description,
            previous_results=prev_results,
        )
        prompt = self._enrich_prompt(prompt, memory)

        logger.debug("Calling LLM for step '%s'...", step_def.id)
        t0 = time.monotonic()

        async def _call() -> str:
            result = await agent.run(prompt)
            return str(result.output if hasattr(result, "output") else result)

        try:
            if self._step_timeout is not None:
                output = await asyncio.wait_for(_call(), timeout=self._step_timeout)
            else:
                output = await _call()
        except TimeoutError:
            elapsed = time.monotonic() - t0
            raise ReasoningError(f"Step '{step_def.id}' timed out after {elapsed:.1f}s") from None

        logger.debug("Step '%s' LLM call completed in %.1fs", step_def.id, time.monotonic() - t0)
        # Persist step result to working memory
        if memory is not None:
            memory.set_fact(f"reasoning:plan_step:{step_def.id}", output[:500])
        return output

    async def _replan(self, state: dict[str, Any], failed_step: PlanStepDef, error: str) -> None:
        """Generate a revised plan after a step failure."""
        agent = state["agent"]
        memory = state.get("memory")
        plan: ReasoningPlan = state["plan"]
        completed = [s for s in plan.steps if s.status == StepStatus.COMPLETED]
        completed_summary = "\n".join(f"{s.id}: {s.output}" for s in completed if s.output) or "None"

        template = self._get_prompt("replan", PLAN_REPLAN_PROMPT)
        prompt = template.render(
            goal=plan.goal,
            failed_step=failed_step.description,
            error=error,
            completed_steps=completed_summary,
        )
        prompt = self._enrich_prompt(prompt, memory)

        new_plan = await self._structured_run(agent, prompt, ReasoningPlan)
        if not new_plan.goal:
            new_plan.goal = plan.goal

        # Replace remaining steps with new plan
        idx = state.get("plan_index", 0)
        plan.steps = plan.steps[:idx] + new_plan.steps
        state["plan_index"] = idx  # retry from current position
