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

"""Pre-built conversational agent template.

Creates a :class:`FireflyAgent` with memory for multi-turn conversations,
a configurable personality, and optional domain focus.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent

if TYPE_CHECKING:
    from fireflyframework_agentic.memory.manager import MemoryManager


def _default_conversational_tools() -> list[Any]:
    """Lazily instantiate built-in tools useful for conversation."""
    from fireflyframework_agentic.tools.builtins.calculator_tool import CalculatorTool
    from fireflyframework_agentic.tools.builtins.datetime_tool import DateTimeTool
    from fireflyframework_agentic.tools.builtins.text_tool import TextTool

    return [DateTimeTool(), CalculatorTool(), TextTool()]


def create_conversational_agent(
    *,
    name: str = "assistant",
    model: str | Model | None = None,
    personality: str = "helpful and professional",
    domain: str = "",
    memory: MemoryManager | None = None,
    extra_instructions: str = "",
    tools: Sequence[Any] = (),
    auto_register: bool = True,
    **kwargs: Any,
) -> FireflyAgent[Any, str]:
    """Create a memory-enabled conversational agent.

    Parameters:
        name: Agent name (default ``"assistant"``).
        model: LLM model string or :class:`pydantic_ai.models.Model` instance;
            falls back to the framework default.
        personality: Description of the assistant's personality and tone.
        domain: Optional domain focus (e.g. ``"healthcare"``,
            ``"finance"``, ``"customer support"``).  When provided, the
            agent's instructions are scoped to that domain.
        memory: Optional :class:`MemoryManager` for multi-turn history.
        extra_instructions: Additional instructions appended to the system prompt.
        tools: Extra tools to attach to the agent.  When empty, the agent
            is equipped with :class:`DateTimeTool`, :class:`CalculatorTool`,
            and :class:`TextTool` so it can answer time, math, and text
            questions without additional configuration.
        auto_register: Whether to register in the global agent registry.
        **kwargs: Forwarded to :class:`FireflyAgent`.

    Returns:
        A configured :class:`FireflyAgent` for multi-turn conversation.
    """
    if not tools:
        tools = _default_conversational_tools()
    domain_clause = f" specialising in {domain}" if domain else ""

    instructions = (
        f"You are a {personality} conversational assistant{domain_clause}.\n"
        "Guidelines:\n"
        "- Answer questions accurately and thoroughly.\n"
        "- If you are unsure, say so rather than guessing.\n"
        "- Reference information from earlier in the conversation when relevant.\n"
        "- Be concise but complete.\n"
        "- Ask clarifying questions when the request is ambiguous."
    )
    if extra_instructions:
        instructions += f"\n{extra_instructions}"

    description = f"Multi-turn conversational assistant ({personality})"
    if domain:
        description += f" focused on {domain}"

    return FireflyAgent(
        name,
        model=model,
        instructions=instructions,
        description=description,
        tags=["conversational", "assistant", "template"],
        memory=memory,
        tools=tools,
        auto_register=auto_register,
        **kwargs,
    )
