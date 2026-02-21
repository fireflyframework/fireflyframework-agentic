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

"""Multi-agent delegation with pluggable routing strategies.

A :class:`DelegationRouter` accepts a pool of agents and a
:class:`DelegationStrategy` that decides which agent handles a given input.
Users can implement the :class:`DelegationStrategy` protocol to provide
custom routing logic.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fireflyframework_genai.exceptions import DelegationError
from fireflyframework_genai.types import UserContent

if TYPE_CHECKING:
    from fireflyframework_genai.agents.base import FireflyAgent
    from fireflyframework_genai.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


@runtime_checkable
class DelegationStrategy(Protocol):
    """Protocol for agent selection strategies.

    Implement this protocol to create custom routing logic.  The framework
    ships with :class:`RoundRobinStrategy` and :class:`CapabilityStrategy`.
    """

    async def select(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> FireflyAgent[Any, Any]:
        """Choose an agent from *agents* to handle *prompt*."""
        ...


class RoundRobinStrategy:
    """Cycle through agents in order, wrapping back to the first after the last."""

    def __init__(self) -> None:
        # Lazily initialised so the cycle resets if the agent pool changes.
        self._cycle: itertools.cycle[FireflyAgent[Any, Any]] | None = None
        self._last_agents: list[FireflyAgent[Any, Any]] = []

    async def select(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> FireflyAgent[Any, Any]:
        if not agents:
            raise DelegationError("No agents available for delegation")
        if self._cycle is None or self._last_agents != list(agents):
            self._cycle = itertools.cycle(agents)
            self._last_agents = list(agents)
        return next(self._cycle)


class CapabilityStrategy:
    """Select the first agent whose tags include a required capability.

    Parameters:
        required_tag: The tag that the selected agent must possess.
    """

    def __init__(self, required_tag: str) -> None:
        self._tag = required_tag

    async def select(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> FireflyAgent[Any, Any]:
        for agent in agents:
            if hasattr(agent, "tags") and self._tag in agent.tags:
                return agent
        raise DelegationError(f"No agent found with required tag '{self._tag}'")


class ContentBasedStrategy:
    """Select an agent by asking an LLM which is best suited for the prompt.

    The strategy builds a short description of each agent (from its *name*
    and *description* attributes) and asks the routing model to pick the
    most suitable one.  This is ideal when agents have overlapping
    capabilities and a simple tag match isn't sufficient.

    Parameters:
        model: A *pydantic-ai* model name used for the routing decision
            (e.g. ``"openai:gpt-4o-mini"``).  Kept lightweight by design.
    """

    def __init__(self, model: str = "openai:gpt-4o-mini") -> None:
        self._model = model

    async def select(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> FireflyAgent[Any, Any]:
        if not agents:
            raise DelegationError("No agents available for delegation")
        if len(agents) == 1:
            return agents[0]

        # Build agent descriptions
        descriptions: list[str] = []
        for i, agent in enumerate(agents):
            name = getattr(agent, "name", f"agent_{i}")
            desc = getattr(agent, "description", "")
            descriptions.append(f"{i}: {name} - {desc or 'no description'}")

        prompt_text = prompt if isinstance(prompt, str) else str(prompt)
        routing_prompt = (
            "You are a routing assistant. Given the user prompt and the list of "
            "available agents below, respond with ONLY the index number of the "
            "agent best suited to handle the prompt.\n\n"
            f"User prompt: {prompt_text[:500]}\n\n"
            "Available agents:\n" + "\n".join(descriptions)
        )

        try:
            from pydantic_ai import Agent as PydanticAgent

            router = PydanticAgent(self._model, system_prompt="You pick the best agent.")
            result = await router.run(routing_prompt)
            idx_str = result.output.strip()
            # Extract first integer from response
            digits = "".join(c for c in idx_str if c.isdigit())[:3]
            if digits:
                idx = int(digits)
                if 0 <= idx < len(agents):
                    return agents[idx]
            logger.warning("Content-based routing got non-numeric response: %r", idx_str[:50])
        except Exception:
            logger.warning("Content-based routing failed, falling back to first agent")

        return agents[0]


class CostAwareStrategy:
    """Select the agent backed by the cheapest model.

    Agents are expected to expose a ``model_name`` attribute (which
    :class:`FireflyAgent` provides).  The strategy maps known model
    names to approximate relative cost tiers and picks the cheapest.
    Unknown models are assigned a middle-tier cost.
    """

    # Approximate relative cost tiers (lower = cheaper)
    _COST_TIERS: dict[str, int] = {
        "gpt-4o-mini": 1,
        "gpt-4.1-mini": 1,
        "gpt-4.1-nano": 0,
        "claude-3-5-haiku": 1,
        "claude-3-haiku": 1,
        "claude-4-haiku": 1,
        "gemini-2.0-flash": 1,
        "gemini-2.5-flash": 1,
        "gpt-4o": 3,
        "gpt-4.1": 3,
        "claude-3-5-sonnet": 3,
        "claude-4-sonnet": 3,
        "gemini-2.5-pro": 4,
        "claude-3-opus": 5,
        "claude-4-opus": 5,
        "o1": 5,
        "o3": 5,
        "o4-mini": 3,
    }

    def _cost_tier(self, model_name: str) -> int:
        """Return cost tier for a model, with middle-tier default."""
        lower = model_name.lower()
        # Strip provider prefix (e.g. "openai:gpt-4o" -> "gpt-4o")
        if ":" in lower:
            lower = lower.split(":", 1)[1]
        for key, tier in self._COST_TIERS.items():
            if key in lower:
                return tier
        return 3  # Default to middle tier

    async def select(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> FireflyAgent[Any, Any]:
        if not agents:
            raise DelegationError("No agents available for delegation")

        best_agent = agents[0]
        best_cost = float("inf")

        for agent in agents:
            model_name = getattr(agent, "model_name", "") or getattr(agent, "_model_identifier", "")
            cost = self._cost_tier(model_name) if model_name else 3
            if cost < best_cost:
                best_cost = cost
                best_agent = agent

        logger.debug(
            "CostAwareStrategy selected '%s' (tier=%s)",
            getattr(best_agent, "name", repr(best_agent)),
            best_cost,
        )
        return best_agent


class DelegationRouter:
    """Routes prompts to agents using a pluggable :class:`DelegationStrategy`.

    Parameters:
        agents: The pool of agents available for delegation.
        strategy: The strategy used to select among *agents*.
        memory: Optional :class:`MemoryManager` shared across all
            delegated agents.  When provided, the selected agent
            receives the memory's conversation history and working
            context automatically.
    """

    def __init__(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        strategy: DelegationStrategy,
        *,
        memory: MemoryManager | None = None,
    ) -> None:
        self._agents = list(agents)
        self._strategy = strategy
        self._memory = memory

    @property
    def memory(self) -> MemoryManager | None:
        """The shared memory manager, if any."""
        return self._memory

    @memory.setter
    def memory(self, value: MemoryManager | None) -> None:
        self._memory = value

    async def route(self, prompt: str | Sequence[UserContent], **kwargs: Any) -> Any:
        """Select an agent via the strategy and run it with *prompt*.

        *prompt* may be a plain string or a multimodal sequence.
        If a :class:`MemoryManager` is attached, the selected agent's
        memory is set to a forked scope before running.
        Returns the agent's run result.
        """
        agent = await self._strategy.select(self._agents, prompt, **kwargs)
        logger.debug("Delegated to agent '%s'", getattr(agent, "name", repr(agent)))

        # Propagate memory to the selected agent
        if self._memory is not None and hasattr(agent, "memory"):
            agent_name = getattr(agent, "name", "delegated")
            agent.memory = self._memory.fork(working_scope_id=f"delegation:{agent_name}")

        deps = kwargs.pop("deps", None)
        return await agent.run(prompt, deps=deps, **kwargs)
