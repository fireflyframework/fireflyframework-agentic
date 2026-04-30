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

"""Global agent registry for discovering and managing :class:`FireflyAgent` instances."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from fireflyframework_agentic.exceptions import AgentNotFoundError

if TYPE_CHECKING:
    from fireflyframework_agentic.agents.base import FireflyAgent

logger = logging.getLogger(__name__)


class AgentInfo(BaseModel):
    """Lightweight, serialisable summary of a registered agent."""

    name: str
    version: str
    description: str
    tags: list[str]


class AgentRegistry:
    """Singleton-style registry that holds references to all :class:`FireflyAgent` instances.

    The registry enables:

    * **Discovery** -- the REST exposure layer queries the registry to
      auto-generate endpoints for every agent.
    * **Delegation** -- the :class:`DelegationRouter` selects among registered
      agents based on capability tags.
    * **Lifecycle** -- the exposure layer can iterate over agents to run
      warmup / shutdown hooks.
    """

    def __init__(self) -> None:
        self._agents: dict[str, FireflyAgent[Any, Any]] = {}
        self._lock = threading.Lock()

    def register(self, agent: FireflyAgent[Any, Any]) -> None:
        """Register *agent* under its :attr:`~FireflyAgent.name`.

        If an agent with the same name is already registered it is silently
        replaced (useful during development and hot-reload scenarios).
        """
        with self._lock:
            self._agents[agent.name] = agent
        logger.debug("Registered agent '%s'", agent.name)

    def get(self, name: str) -> FireflyAgent[Any, Any]:
        """Return the agent registered under *name*.

        Raises:
            AgentNotFoundError: If no agent with *name* is registered.
        """
        with self._lock:
            try:
                return self._agents[name]
            except KeyError:
                raise AgentNotFoundError(f"No agent registered with name '{name}'") from None

    def has(self, name: str) -> bool:
        """Return *True* if an agent with *name* is registered."""
        with self._lock:
            return name in self._agents

    def unregister(self, name: str) -> None:
        """Remove the agent registered under *name*.

        Raises:
            AgentNotFoundError: If no agent with *name* is registered.
        """
        with self._lock:
            if name not in self._agents:
                raise AgentNotFoundError(f"No agent registered with name '{name}'")
            del self._agents[name]
        logger.debug("Unregistered agent '%s'", name)

    def list_agents(self) -> list[AgentInfo]:
        """Return an :class:`AgentInfo` summary for every registered agent."""
        with self._lock:
            agents = list(self._agents.values())
        return [
            AgentInfo(
                name=a.name,
                version=a.version,
                description=a.description,
                tags=a.tags,
            )
            for a in agents
        ]

    def clear(self) -> None:
        """Remove all registered agents.  Primarily useful in tests."""
        with self._lock:
            self._agents.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._agents)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._agents


# Module-level singleton
agent_registry = AgentRegistry()
