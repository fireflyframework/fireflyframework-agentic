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

"""Tree of Thoughts reasoning pattern: Branch -> Evaluate -> Select.

Explores multiple reasoning branches, evaluates each with a structured
:class:`~fireflyframework_agentic.reasoning.models.BranchEvaluation`, and
selects the best.  Prompts are configurable.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model

from fireflyframework_agentic.prompts.template import PromptTemplate
from fireflyframework_agentic.reasoning.base import AbstractReasoningPattern
from fireflyframework_agentic.reasoning.models import BranchEvaluation, BranchList
from fireflyframework_agentic.reasoning.prompts import TOT_BRANCH_PROMPT, TOT_EVALUATE_PROMPT
from fireflyframework_agentic.reasoning.trace import (
    ReasoningResult,
    ReasoningStep,
    ReasoningTrace,
    ThoughtStep,
)
from fireflyframework_agentic.types import AgentLike, UserContent

if TYPE_CHECKING:
    from fireflyframework_agentic.validation.reviewer import OutputReviewer

logger = logging.getLogger(__name__)


class TreeOfThoughtsPattern(AbstractReasoningPattern):
    """Branch -> Evaluate -> Select.

    1. **Branch** -- generate *branching_factor* distinct approaches via
       structured output (:class:`BranchList`).
    2. **Evaluate** -- score each branch via :class:`BranchEvaluation`.
    3. **Select** -- pick the highest-scoring branch.

    Parameters:
        branching_factor: Number of branches to explore per step.
        max_depth: Maximum tree depth (maps to max_steps).
        model: Optional LLM model for structured output calls.
        prompts: Optional prompt overrides.  Supported slots:
            ``"branch"``, ``"evaluate"``.
        reviewer: Optional :class:`OutputReviewer` for final output validation.
    """

    def __init__(
        self,
        *,
        branching_factor: int = 3,
        max_depth: int = 3,
        model: str | Model | None = None,
        prompts: dict[str, PromptTemplate] | None = None,
        reviewer: OutputReviewer | None = None,
        step_timeout: float | None = None,
    ) -> None:
        super().__init__(
            "tree_of_thoughts",
            max_steps=max_depth,
            model=model,
            prompts=prompts,
            reviewer=reviewer,
            step_timeout=step_timeout,
        )
        self._branching_factor = branching_factor

    async def execute(self, agent: AgentLike, input: str | Sequence[UserContent], **kwargs: Any) -> ReasoningResult:
        """Override execute to implement branching logic with memory support."""
        t_start = time.monotonic()
        logger.info("ToT: starting (branching_factor=%d)", self._branching_factor)
        trace = ReasoningTrace(pattern_name=self._name)
        raw_memory = kwargs.pop("memory", None)
        memory = self._init_memory(raw_memory, self._name)

        branches = await self._generate_branches(agent, input)
        logger.info("ToT: generated %d branches", len(branches))

        for i, branch in enumerate(branches):
            step = ThoughtStep(content=f"Branch: {branch[:200]}")
            trace.add_step(step)
            self._persist_step(memory, step, i + 1)

        evaluations = await self._evaluate_branches(agent, input, branches)
        for ev in evaluations:
            logger.info("ToT: branch %d score=%.2f", ev.branch_id, ev.score)
        best_eval = max(evaluations, key=lambda e: e.score)
        best = branches[best_eval.branch_id] if best_eval.branch_id < len(branches) else branches[0]
        logger.info("ToT: selected branch %d (score=%.2f)", best_eval.branch_id + 1, best_eval.score)

        selection_step = ThoughtStep(
            content=(f"Selected branch {best_eval.branch_id + 1} (score={best_eval.score:.2f}): {best[:200]}"),
            confidence=best_eval.score,
        )
        trace.add_step(selection_step)
        self._persist_step(memory, selection_step, len(branches) + 1)
        trace.complete()

        output = best
        if self._reviewer is not None:
            output = await self._review_output({"agent": agent}, output)

        if memory is not None:
            memory.set_fact("reasoning:output", str(output)[:1000])

        logger.info("ToT: completed in %.1fs", time.monotonic() - t_start)
        return ReasoningResult(
            output=output,
            trace=trace,
            steps_taken=len(branches) + 1,
            success=True,
        )

    async def _generate_branches(self, agent: AgentLike, input: str | Sequence[Any]) -> list[str]:
        """Generate multiple reasoning branches via structured output.

        Uses ``_structured_run`` with :class:`BranchList` to get a clean
        list.  The fallback parse in the base class splits on ``---`` when
        the LLM returns plain text, so backward compatibility is maintained.
        """
        template = self._get_prompt("branch", TOT_BRANCH_PROMPT)
        prompt = template.render(
            branching_factor=str(self._branching_factor),
            problem=str(input),
        )
        branch_list = await self._structured_run(agent, prompt.user, BranchList)
        branches = [b for b in branch_list.branches if b.strip()]
        return branches[: self._branching_factor] or [str(input)]

    async def _evaluate_branches(
        self, agent: AgentLike, input: str | Sequence[Any], branches: list[str]
    ) -> list[BranchEvaluation]:
        """Score each branch using structured evaluations."""
        evaluations: list[BranchEvaluation] = []
        for idx, branch in enumerate(branches):
            template = self._get_prompt("evaluate", TOT_EVALUATE_PROMPT)
            prompt = template.render(
                problem=str(input),
                branch_id=str(idx),
                approach=branch,
            )
            evaluation = await self._structured_run(agent, prompt.user, BranchEvaluation)
            # Ensure branch_id is correct even if LLM returns wrong id
            if evaluation.branch_id != idx:
                evaluation = BranchEvaluation(
                    branch_id=idx,
                    score=evaluation.score,
                    reasoning=evaluation.reasoning,
                )
            evaluations.append(evaluation)
        return evaluations

    # Unused hooks (execute is fully overridden)
    async def _reason(self, state: dict[str, Any]) -> ReasoningStep | None:
        return None

    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        return None
