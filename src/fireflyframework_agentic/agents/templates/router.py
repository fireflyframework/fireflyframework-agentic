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

"""Pre-built router (supervisor) agent template.

Creates a :class:`FireflyAgent` that analyses user intent and returns
the name of the best-suited child agent, enabling intelligent
delegation without hard-coded routing rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent


class RoutingDecision(BaseModel):
    """Structured output from the router agent.

    Attributes:
        target_agent: Name of the agent that should handle the request.
        confidence: Confidence in the routing decision (0.0-1.0).
        reasoning: Brief explanation of why this agent was chosen.
    """

    target_agent: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


def create_router_agent(
    agent_map: dict[str, str],
    *,
    name: str = "router",
    model: str | Model | None = None,
    fallback_agent: str | None = None,
    extra_instructions: str = "",
    tools: Sequence[Any] = (),
    auto_register: bool = True,
    **kwargs: Any,
) -> FireflyAgent[Any, RoutingDecision]:
    """Create an intent-routing supervisor agent.

    Parameters:
        agent_map: Mapping of agent name to a description of what that
            agent handles.  For example::

                {
                    "billing": "Handles billing inquiries, invoices, payments",
                    "technical": "Handles technical support and troubleshooting",
                    "sales": "Handles product questions and purchasing",
                }

        name: Agent name (default ``"router"``).
        model: LLM model string or :class:`pydantic_ai.models.Model` instance;
            falls back to the framework default.
        fallback_agent: Agent name to use when no confident match is found.
            When *None*, the router must always pick from *agent_map*.
        extra_instructions: Additional instructions appended to the system prompt.
        tools: Extra tools to attach to the agent.
        auto_register: Whether to register in the global agent registry.
        **kwargs: Forwarded to :class:`FireflyAgent`.

    Returns:
        A configured :class:`FireflyAgent` that outputs :class:`RoutingDecision`.
    """
    agent_descriptions = "\n".join(f"- {agent_name}: {description}" for agent_name, description in agent_map.items())

    fallback_clause = ""
    if fallback_agent:
        fallback_clause = f"\nIf no agent is a confident match, route to '{fallback_agent}'."

    instructions = (
        "You are an intelligent request router.\n"
        "Analyse the user's message and determine which agent should handle it.\n\n"
        "Available agents:\n"
        f"{agent_descriptions}\n"
        f"{fallback_clause}\n"
        "Return the exact agent name from the list above.\n"
        "Provide a confidence score between 0.0 and 1.0.\n"
        "Include brief reasoning for your routing decision."
    )
    if extra_instructions:
        instructions += f"\n{extra_instructions}"

    return FireflyAgent(
        name,
        model=model,
        instructions=instructions,
        output_type=RoutingDecision,
        description=f"Routes requests to: {', '.join(agent_map.keys())}",
        tags=["router", "supervisor", "template"],
        tools=tools,
        auto_register=auto_register,
        **kwargs,
    )
