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

"""Pre-built summarizer agent template.

Creates a :class:`FireflyAgent` configured for text and document
summarization with tuneable length, style, and format.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent


def _default_summarizer_tools() -> list[Any]:
    """Lazily instantiate built-in tools useful for summarization."""
    from fireflyframework_agentic.tools.builtins.text_tool import TextTool

    return [TextTool()]


def create_summarizer_agent(
    *,
    name: str = "summarizer",
    model: str | Model | None = None,
    max_length: str = "concise",
    style: str = "professional",
    output_format: str = "paragraph",
    extra_instructions: str = "",
    tools: Sequence[Any] = (),
    auto_register: bool = True,
    **kwargs: Any,
) -> FireflyAgent[Any, str]:
    """Create a summarization agent.

    Parameters:
        name: Agent name (default ``"summarizer"``).
        model: LLM model string or :class:`pydantic_ai.models.Model` instance;
            falls back to the framework default.
        max_length: ``"concise"`` (1-2 sentences), ``"short"`` (1 paragraph),
            ``"medium"`` (2-3 paragraphs), or ``"detailed"`` (comprehensive).
        style: ``"professional"``, ``"casual"``, ``"technical"``, or ``"academic"``.
        output_format: ``"paragraph"``, ``"bullets"``, or ``"numbered"``.
        extra_instructions: Additional instructions appended to the system prompt.
        tools: Extra tools to attach to the agent.  When empty, the agent
            is equipped with :class:`TextTool` for word/sentence counting
            and text analysis.
        auto_register: Whether to register in the global agent registry.
        **kwargs: Forwarded to :class:`FireflyAgent`.

    Returns:
        A configured :class:`FireflyAgent` for summarization.
    """
    if not tools:
        tools = _default_summarizer_tools()
    length_map = {
        "concise": "Produce a concise summary of 1-2 sentences.",
        "short": "Produce a short summary of one paragraph (3-5 sentences).",
        "medium": "Produce a medium-length summary of 2-3 paragraphs.",
        "detailed": "Produce a detailed, comprehensive summary preserving all key information.",
    }
    format_map = {
        "paragraph": "Write in flowing paragraph form.",
        "bullets": "Use bullet points for the summary.",
        "numbered": "Use a numbered list for the summary.",
    }

    length_instruction = length_map.get(max_length, length_map["concise"])
    format_instruction = format_map.get(output_format, format_map["paragraph"])

    instructions = (
        f"You are a {style} summarization assistant.\n"
        f"{length_instruction}\n"
        f"{format_instruction}\n"
        "Preserve all key facts, names, dates, numbers, and conclusions.\n"
        "Do not add information that is not present in the source.\n"
        "Do not include preamble like 'Here is a summary'."
    )
    if extra_instructions:
        instructions += f"\n{extra_instructions}"

    return FireflyAgent(
        name,
        model=model,
        instructions=instructions,
        description=f"Summarizes text and documents ({max_length}, {style}, {output_format})",
        tags=["summarizer", "nlp", "template"],
        tools=tools,
        auto_register=auto_register,
        **kwargs,
    )
