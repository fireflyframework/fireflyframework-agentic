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

"""Queue message router: maps topic/queue patterns to specific agents."""

from __future__ import annotations

import re

from fireflyframework_agentic.agents.registry import agent_registry
from fireflyframework_agentic.exceptions import ExposureError
from fireflyframework_agentic.exposure.queues.base import QueueMessage


class QueueRouter:
    """Routes queue messages to agents based on pattern matching.

    Rules are added via :meth:`add_route` and evaluated in order.

    Parameters:
        default_agent: Agent name used when no rule matches.
    """

    def __init__(self, default_agent: str | None = None) -> None:
        self._routes: list[tuple[re.Pattern[str], str]] = []
        self._default_agent = default_agent

    def add_route(self, pattern: str, agent_name: str) -> None:
        """Add a routing rule: messages whose routing key matches *pattern*
        are sent to *agent_name*."""
        self._routes.append((re.compile(pattern), agent_name))

    async def route(self, message: QueueMessage) -> str:
        """Route *message* to the appropriate agent and return the response."""
        agent_name = self._resolve(message.routing_key)
        agent = agent_registry.get(agent_name)
        result = await agent.run(message.body)
        return str(result.output if hasattr(result, "output") else result)

    def _resolve(self, routing_key: str) -> str:
        """Find the first matching agent name for *routing_key*."""
        for pattern, agent_name in self._routes:
            if pattern.search(routing_key):
                return agent_name
        if self._default_agent:
            return self._default_agent
        raise ExposureError(f"No route matched routing key '{routing_key}' and no default agent set")
