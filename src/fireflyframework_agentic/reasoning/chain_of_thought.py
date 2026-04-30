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

"""Chain-of-Thought reasoning pattern: structured step-by-step reasoning.

The simplest pattern.  The agent reasons through the problem step by step,
validating each step, until it reaches a conclusion signalled by the
:class:`~fireflyframework_agentic.reasoning.models.ReasoningThought`
``is_final`` flag.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model

from fireflyframework_agentic.prompts.template import PromptTemplate
from fireflyframework_agentic.reasoning.base import AbstractReasoningPattern
from fireflyframework_agentic.reasoning.models import ReasoningThought
from fireflyframework_agentic.reasoning.prompts import COT_STEP_PROMPT
from fireflyframework_agentic.reasoning.trace import (
    ReasoningStep,
    ThoughtStep,
)

if TYPE_CHECKING:
    from fireflyframework_agentic.validation.reviewer import OutputReviewer

logger = logging.getLogger(__name__)


class ChainOfThoughtPattern(AbstractReasoningPattern):
    """Structured step-by-step reasoning.

    Each iteration generates a :class:`ReasoningThought` via structured
    output.  The pattern stops when the thought signals ``is_final=True``.

    Parameters:
        max_steps: Maximum number of reasoning steps.
        model: Optional LLM model for structured output calls.
        prompts: Optional prompt overrides.  Supported slot: ``"step"``.
        reviewer: Optional :class:`OutputReviewer` for final output validation.
    """

    def __init__(
        self,
        *,
        max_steps: int = 10,
        model: str | Model | None = None,
        prompts: dict[str, PromptTemplate] | None = None,
        reviewer: OutputReviewer | None = None,
        step_timeout: float | None = None,
    ) -> None:
        super().__init__(
            "chain_of_thought",
            max_steps=max_steps,
            model=model,
            prompts=prompts,
            reviewer=reviewer,
            step_timeout=step_timeout,
        )

    async def _reason(self, state: dict[str, Any]) -> ReasoningStep | None:
        agent = state["agent"]
        memory = state.get("memory")
        chain: list[str] = state.get("chain", [])
        step_num = len(chain) + 1

        logger.info("CoT step %d: generating thought...", step_num)
        previous_steps = "\n".join(f"Step {i + 1}: {s}" for i, s in enumerate(chain))
        template = self._get_prompt("step", COT_STEP_PROMPT)
        prompt = template.render(
            problem=str(state["input"]),
            previous_steps=previous_steps,
            step_number=str(step_num),
        )
        prompt = self._enrich_prompt(prompt, memory)

        thought = await self._structured_run(agent, prompt, ReasoningThought)
        chain.append(thought.content)
        state["chain"] = chain
        state["last_thought"] = thought

        if thought.is_final:
            state["output"] = thought.final_answer or thought.content
            logger.info(
                "CoT step %d: FINAL (confidence=%.2f): %s",
                step_num,
                thought.confidence or 0,
                (thought.final_answer or thought.content)[:120],
            )
        else:
            logger.info(
                "CoT step %d: (confidence=%.2f) %s",
                step_num,
                thought.confidence or 0,
                thought.content[:120],
            )
        return ThoughtStep(content=thought.content, confidence=thought.confidence)

    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        return None

    async def _should_continue(self, state: dict[str, Any]) -> bool:
        thought: ReasoningThought | None = state.get("last_thought")
        return thought is None or not thought.is_final

    async def _extract_output(self, state: dict[str, Any]) -> Any:
        return state.get("output", state.get("chain", [""])[-1] if state.get("chain") else None)
