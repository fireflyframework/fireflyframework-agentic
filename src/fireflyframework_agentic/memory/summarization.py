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

"""LLM-based conversation summarization.

:func:`create_llm_summarizer` returns a callable suitable for
:class:`~fireflyframework_agentic.memory.conversation.ConversationMemory`'s
``summarizer`` parameter.  It compresses evicted turns into a concise
summary using an LLM agent.

Usage::

    from fireflyframework_agentic.memory.summarization import create_llm_summarizer

    summarizer = create_llm_summarizer(model="openai:gpt-4o-mini")
    memory = ConversationMemory(summarizer=summarizer)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fireflyframework_agentic.memory.types import ConversationTurn

logger = logging.getLogger(__name__)

_DEFAULT_SUMMARIZE_PROMPT = (
    "Summarize the following conversation turns into a concise paragraph "
    "that preserves key facts, decisions, user preferences, and context "
    "needed for continuing the conversation. Do NOT include greetings or "
    "filler.\n\n{turns_text}"
)


def create_llm_summarizer(
    *,
    model: str | Any | None = None,
    prompt_template: str | None = None,
    max_summary_tokens: int = 500,
) -> Callable[[list[ConversationTurn]], str]:
    """Create an LLM-based summarizer function for conversation memory.

    The returned callable can be passed directly to
    :class:`ConversationMemory(summarizer=...)`.

    Parameters:
        model: Pydantic AI model string or ``Model`` instance.  When
            *None*, uses the framework default model.
        prompt_template: Custom prompt template.  Must contain a
            ``{turns_text}`` placeholder.
        max_summary_tokens: Soft limit on summary length (passed to the
            LLM as guidance, not enforced).
    """
    template = prompt_template or _DEFAULT_SUMMARIZE_PROMPT

    def _summarize(turns: list[ConversationTurn]) -> str:
        """Synchronous wrapper that calls the async summarizer."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _async_summarize(turns)).result()
        return asyncio.run(_async_summarize(turns))

    async def _async_summarize(turns: list[ConversationTurn]) -> str:
        """Use an ephemeral Pydantic AI agent to summarize the turns."""
        turns_text = _format_turns(turns)
        prompt = template.format(turns_text=turns_text)

        try:
            from pydantic_ai import Agent as PydanticAgent

            resolved_model = model
            if resolved_model is None:
                from fireflyframework_agentic.config import get_config

                resolved_model = get_config().default_model

            agent = PydanticAgent(resolved_model, output_type=str)
            result = await agent.run(prompt)
            summary = result.output if hasattr(result, "output") else str(result)
            logger.debug("Summarized %d turns into %d chars", len(turns), len(summary))
            return summary
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM summarization failed: %s. Falling back to truncation.", exc)
            return _fallback_summarize(turns)

    return _summarize


def _format_turns(turns: list[ConversationTurn]) -> str:
    """Format turns as numbered user/assistant exchanges."""
    lines: list[str] = []
    for i, turn in enumerate(turns, 1):
        lines.append(f"Turn {i}:")
        lines.append(f"  User: {turn.user_prompt[:500]}")
        lines.append(f"  Assistant: {turn.assistant_response[:500]}")
    return "\n".join(lines)


def _fallback_summarize(turns: list[ConversationTurn]) -> str:
    """Non-LLM fallback: extract key sentences from each turn."""
    parts: list[str] = []
    for turn in turns[-5:]:  # Keep last 5 turns at most
        if turn.assistant_response:
            first_sentence = turn.assistant_response.split(".")[0].strip()
            if first_sentence:
                parts.append(first_sentence + ".")
    return " ".join(parts) if parts else "Previous conversation context."
