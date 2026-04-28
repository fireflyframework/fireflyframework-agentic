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

"""Exposure package -- REST API and message queue agent exposure."""

from fireflyframework_agentic.exposure.queues import (
    BaseQueueConsumer,
    QueueConsumer,
    QueueMessage,
    QueueProducer,
    QueueRouter,
)

__all__ = [
    "BaseQueueConsumer",
    "QueueConsumer",
    "QueueMessage",
    "QueueProducer",
    "QueueRouter",
]


def __getattr__(name: str):
    """Lazy-load REST symbols so the package works without FastAPI installed."""
    _rest_names = {"create_agentic_app", "AgentRequest", "AgentResponse", "HealthResponse"}
    if name in _rest_names:
        from fireflyframework_agentic.exposure.rest import (
            AgentRequest,
            AgentResponse,
            HealthResponse,
            create_agentic_app,
        )

        _map = {
            "create_agentic_app": create_agentic_app,
            "AgentRequest": AgentRequest,
            "AgentResponse": AgentResponse,
            "HealthResponse": HealthResponse,
        }
        return _map[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
