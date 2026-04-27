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

"""Reflexion reasoning pattern: Execute -> Reflect -> Retry.

The agent first produces an answer, then critiques it using a structured
:class:`~fireflyframework_agentic.reasoning.models.ReflectionVerdict`.
If the verdict signals issues, the agent retries with specific feedback.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model

from fireflyframework_agentic.prompts.template import PromptTemplate
from fireflyframework_agentic.reasoning.base import AbstractReasoningPattern
from fireflyframework_agentic.reasoning.models import ReflectionVerdict
from fireflyframework_agentic.reasoning.prompts import (
    REFLEXION_CRITIQUE_PROMPT,
    REFLEXION_RETRY_PROMPT,
)
from fireflyframework_agentic.reasoning.trace import (
    ReasoningStep,
    ReflectionStep,
    ThoughtStep,
)

if TYPE_CHECKING:
    from fireflyframework_agentic.validation.reviewer import OutputReviewer

logger = logging.getLogger(__name__)


class ReflexionPattern(AbstractReasoningPattern):
    """Execute -> Reflect -> Retry.

    1. **Execute** -- the agent produces an answer.
    2. **Reflect** -- the agent critiques via :class:`ReflectionVerdict`
       using structured output.
    3. If ``is_satisfactory=False``, retry with structured feedback.

    Parameters:
        max_steps: Maximum reflection rounds.
        model: Optional LLM model for structured output calls.
        prompts: Optional prompt overrides.  Supported slots:
            ``"critique"``, ``"retry"``.
        reviewer: Optional :class:`OutputReviewer` for final output validation.
    """

    def __init__(
        self,
        *,
        max_steps: int = 5,
        model: str | Model | None = None,
        prompts: dict[str, PromptTemplate] | None = None,
        reviewer: OutputReviewer | None = None,
        step_timeout: float | None = None,
    ) -> None:
        super().__init__(
            "reflexion",
            max_steps=max_steps,
            model=model,
            prompts=prompts,
            reviewer=reviewer,
            step_timeout=step_timeout,
        )

    async def _reason(self, state: dict[str, Any]) -> ReasoningStep | None:
        agent = state["agent"]
        memory = state.get("memory")
        verdict: ReflectionVerdict | None = state.get("last_verdict")

        if verdict is not None and not verdict.is_satisfactory:
            logger.info("Reflexion: retrying with %d issue(s) feedback...", len(verdict.issues))
            template = self._get_prompt("retry", REFLEXION_RETRY_PROMPT)
            prompt = template.render(
                original_prompt=str(state["input"]),
                issues=verdict.issues,
                suggestions=verdict.suggestions,
            )
            prompt = self._enrich_prompt(prompt, memory)
        else:
            logger.info("Reflexion: generating initial answer...")
            prompt = str(state["input"])

        result = await agent.run(prompt)
        answer = str(result.output if hasattr(result, "output") else result)
        state["last_answer"] = answer
        logger.debug("Reflexion: answer preview: %s", answer[:200])
        return ThoughtStep(content=f"Generated answer: {answer[:200]}")

    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        agent = state["agent"]
        memory = state.get("memory")
        answer = state.get("last_answer", "")
        template = self._get_prompt("critique", REFLEXION_CRITIQUE_PROMPT)
        prompt = template.render(
            question=str(state["input"]),
            answer=answer,
        )
        prompt = self._enrich_prompt(prompt, memory)

        logger.info("Reflexion: critiquing answer...")
        verdict = await self._structured_run(agent, prompt, ReflectionVerdict)
        state["last_verdict"] = verdict
        if verdict.is_satisfactory:
            logger.info("Reflexion: verdict — SATISFACTORY")
        else:
            logger.info(
                "Reflexion: verdict — NOT satisfactory (%d issue(s))",
                len(verdict.issues),
            )
        return ReflectionStep(
            critique="; ".join(verdict.issues) if verdict.issues else "Satisfactory",
            should_retry=not verdict.is_satisfactory,
        )

    async def _should_continue(self, state: dict[str, Any]) -> bool:
        verdict: ReflectionVerdict | None = state.get("last_verdict")
        return verdict is not None and not verdict.is_satisfactory

    async def _extract_output(self, state: dict[str, Any]) -> Any:
        return state.get("last_answer")
