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

"""Pre-built extractor agent template.

Creates a :class:`FireflyAgent` that extracts structured fields from
documents and returns them as a user-provided Pydantic model.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.types import OutputT


def _default_extractor_tools() -> list[Any]:
    """Lazily instantiate built-in tools useful for extraction."""
    from fireflyframework_agentic.tools.builtins.json_tool import JsonTool
    from fireflyframework_agentic.tools.builtins.text_tool import TextTool

    return [JsonTool(), TextTool()]


def create_extractor_agent(
    output_type: type[OutputT],
    *,
    name: str = "extractor",
    model: str | Model | None = None,
    field_descriptions: dict[str, str] | None = None,
    extra_instructions: str = "",
    tools: Sequence[Any] = (),
    auto_register: bool = True,
    **kwargs: Any,
) -> FireflyAgent[Any, OutputT]:
    """Create a structured data extraction agent.

    Parameters:
        output_type: A Pydantic model defining the fields to extract.
        name: Agent name (default ``"extractor"``).
        model: LLM model string or :class:`pydantic_ai.models.Model` instance;
            falls back to the framework default.
        field_descriptions: Optional mapping of field name to extraction
            guidance to help the model locate each field.
        extra_instructions: Additional instructions appended to the system prompt.
        tools: Extra tools to attach to the agent.  When empty, the agent
            is equipped with :class:`JsonTool` and :class:`TextTool` for
            parsing and text analysis.
        auto_register: Whether to register in the global agent registry.
        **kwargs: Forwarded to :class:`FireflyAgent`.

    Returns:
        A configured :class:`FireflyAgent` that outputs the given *output_type*.
    """
    if not tools:
        tools = _default_extractor_tools()
    field_guidance = ""
    if field_descriptions:
        lines = [f"- {field}: {desc}" for field, desc in field_descriptions.items()]
        field_guidance = "Field extraction guidance:\n" + "\n".join(lines) + "\n\n"

    instructions = (
        "You are a precise data extraction assistant.\n"
        "Extract structured information from the provided document or text.\n\n"
        f"{field_guidance}"
        "Rules:\n"
        "- Only extract information that is explicitly present in the source.\n"
        "- If a field cannot be found, return null for that field.\n"
        "- Do not infer or hallucinate values.\n"
        "- Preserve exact values (numbers, dates, names) as they appear in the source.\n"
        "- Return the data in the requested structured format."
    )
    if extra_instructions:
        instructions += f"\n{extra_instructions}"

    return FireflyAgent(
        name,
        model=model,
        instructions=instructions,
        output_type=output_type,
        description=f"Extracts structured data into {output_type.__name__}",
        tags=["extractor", "nlp", "template"],
        tools=tools,
        auto_register=auto_register,
        **kwargs,
    )
