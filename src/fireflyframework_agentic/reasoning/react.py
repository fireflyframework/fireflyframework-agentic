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

"""ReAct reasoning pattern: Reason-Act-Observe loop (Yao et al., 2022).

The pattern interleaves reasoning (thought generation), action (tool calls),
and observation (processing tool results) until a stopping condition is met.

Uses :class:`~fireflyframework_agentic.reasoning.models.ReasoningThought` as
structured output so that the ``is_final`` flag replaces magic stop-phrases.
Prompts are configurable via the ``prompts`` constructor argument.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model

from fireflyframework_agentic.prompts.template import PromptTemplate
from fireflyframework_agentic.reasoning.base import AbstractReasoningPattern
from fireflyframework_agentic.reasoning.models import ReasoningThought
from fireflyframework_agentic.reasoning.prompts import REACT_ACTION_PROMPT, REACT_THOUGHT_PROMPT
from fireflyframework_agentic.reasoning.trace import (
    ActionStep,
    ObservationStep,
    ReasoningStep,
    ThoughtStep,
)

if TYPE_CHECKING:
    from fireflyframework_agentic.validation.reviewer import OutputReviewer

logger = logging.getLogger(__name__)


class ReActPattern(AbstractReasoningPattern):
    """Reason-Act-Observe loop.

    Each iteration:

    1. **Thought** -- the agent reasons about the current state and
       produces a :class:`ReasoningThought` via structured output.
    2. **Action** -- the agent takes an action based on the thought.
    3. **Observation** -- the action result is recorded in working memory.

    The loop continues until the thought signals ``is_final=True`` or
    ``max_steps`` is reached.

    Parameters:
        max_steps: Maximum reasoning iterations.
        model: Optional LLM model for structured output calls.
        prompts: Optional prompt overrides.  Supported slots:
            ``"thought"``, ``"action"``.
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
            "react",
            max_steps=max_steps,
            model=model,
            prompts=prompts,
            reviewer=reviewer,
            step_timeout=step_timeout,
        )

    async def _reason(self, state: dict[str, Any]) -> ReasoningStep | None:
        agent = state["agent"]
        memory = state.get("memory")
        # Build context from last observation or original input
        context = state.get("last_observation", str(state["input"]))
        template = self._get_prompt("thought", REACT_THOUGHT_PROMPT)
        prompt = template.render(context=str(context))
        prompt = self._enrich_prompt(prompt, memory)

        logger.info("ReAct: generating thought...")
        thought = await self._structured_run(agent, prompt, ReasoningThought)
        state["last_thought"] = thought
        state["last_thought_text"] = thought.content
        if thought.is_final and thought.final_answer:
            state["output"] = thought.final_answer
            logger.info("ReAct: FINAL thought (confidence=%.2f)", thought.confidence or 0)
        else:
            logger.info("ReAct: thought (confidence=%.2f): %s", thought.confidence or 0, thought.content[:120])
        return ThoughtStep(content=thought.content, confidence=thought.confidence)

    async def _should_stop(self, state: dict[str, Any]) -> bool:
        thought: ReasoningThought | None = state.get("last_thought")
        if thought is not None and thought.is_final:
            logger.info("ReAct: early stop — final thought reached")
            return True
        return False

    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        agent = state["agent"]
        memory = state.get("memory")
        thought_text = state.get("last_thought_text", "")
        template = self._get_prompt("action", REACT_ACTION_PROMPT)
        prompt = template.render(
            problem=str(state["input"]),
            thought=thought_text,
        )
        prompt = self._enrich_prompt(prompt, memory)

        logger.info("ReAct: executing action...")
        result = await agent.run(prompt)
        raw = str(result.output if hasattr(result, "output") else result)
        state["last_action_result"] = raw
        logger.debug("ReAct: action result: %s", raw[:200])
        return ActionStep(
            tool_name="react_action",
            tool_args={"thought": thought_text[:100]},
        )

    async def _observe(self, state: dict[str, Any], action: ReasoningStep | None) -> ReasoningStep | None:
        result = state.get("last_action_result", "")
        state["last_observation"] = result
        logger.debug("ReAct: observation: %s", result[:200])
        # Persist observation in working memory if available
        memory = state.get("memory")
        if memory is not None:
            step_num = len([s for s in state.get("_obs_count", [])]) + 1
            state.setdefault("_obs_count", []).append(step_num)
            memory.set_fact(f"reasoning:observation:{step_num}", result[:500])
        return ObservationStep(content=result[:200], source="react_action")

    async def _should_continue(self, state: dict[str, Any]) -> bool:
        thought: ReasoningThought | None = state.get("last_thought")
        return thought is None or not thought.is_final

    async def _extract_output(self, state: dict[str, Any]) -> Any:
        return state.get("output", state.get("last_thought_text"))
