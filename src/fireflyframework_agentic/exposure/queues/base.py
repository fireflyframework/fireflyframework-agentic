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

"""Abstract queue consumer and producer protocols."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class QueueMessage(BaseModel):
    """A message consumed from or produced to a queue."""

    body: str
    headers: dict[str, str] = {}
    routing_key: str = ""
    reply_to: str = ""


@runtime_checkable
class QueueConsumer(Protocol):
    """Protocol for queue consumers."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class QueueProducer(Protocol):
    """Protocol for queue producers."""

    async def publish(self, message: QueueMessage) -> None: ...


class BaseQueueConsumer(ABC):
    """Abstract base class for queue consumers that route messages to agents.

    Parameters:
        agent_name: Name of the agent to route messages to.
    """

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._running = False

    @property
    def agent_name(self) -> str:
        return self._agent_name

    @property
    def is_running(self) -> bool:
        return self._running

    @abstractmethod
    async def start(self) -> None:
        """Connect and begin consuming messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop consuming and disconnect."""
        ...

    async def _process_message(self, message: QueueMessage) -> str:
        """Route the message to the configured agent and return the response."""
        from fireflyframework_agentic.agents.registry import agent_registry

        agent = agent_registry.get(self._agent_name)
        result = await agent.run(message.body)
        return str(result.output if hasattr(result, "output") else result)
