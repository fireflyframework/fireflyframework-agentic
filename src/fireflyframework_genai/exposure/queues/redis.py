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

"""Redis Pub/Sub consumer for agent exposure.

Requires the ``redis`` optional dependency (install via
``pip install fireflyframework-genai[redis]``).
"""

from __future__ import annotations

import logging
from typing import Any

from fireflyframework_genai.exposure.queues.base import BaseQueueConsumer, QueueMessage

logger = logging.getLogger(__name__)


class RedisAgentConsumer(BaseQueueConsumer):
    """Subscribe to a Redis Pub/Sub channel and route messages to an agent.

    Parameters:
        agent_name: Name of the agent to invoke.
        channel: Redis Pub/Sub channel to subscribe to.
        url: Redis connection URL.
    """

    def __init__(
        self,
        agent_name: str,
        *,
        channel: str,
        url: str = "redis://localhost:6379",
    ) -> None:
        super().__init__(agent_name)
        self._channel = channel
        self._url = url
        self._client: Any = None

    async def start(self) -> None:
        """Connect to Redis and begin subscribing."""
        try:
            import redis.asyncio as aioredis  # type: ignore[import-not-found]
        except ImportError as _err:
            raise ImportError(
                "redis[hiredis] is required for Redis support. "
                "Install it with: pip install fireflyframework-genai[redis]"
            ) from _err

        self._client = aioredis.from_url(self._url)
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel)
        self._running = True
        logger.info("Redis consumer started on channel '%s'", self._channel)

        try:
            async for raw_message in pubsub.listen():
                if raw_message["type"] == "message":
                    body = raw_message["data"]
                    if isinstance(body, bytes):
                        body = body.decode("utf-8")

                    # Try to parse as JSON to extract trace context
                    # If not JSON, treat as plain text
                    import json

                    from fireflyframework_genai.observability.tracer import extract_trace_context, trace_context_scope

                    span_context = None
                    try:
                        data = json.loads(body)
                        if isinstance(data, dict) and "headers" in data and "body" in data:
                            # Message is wrapped with metadata for trace propagation
                            span_context = extract_trace_context(data.get("headers", {}))
                            body = data["body"]
                    except (json.JSONDecodeError, KeyError):
                        # Not a wrapped message, use body as-is
                        pass

                    message = QueueMessage(body=body)

                    # Process message within trace context scope
                    with trace_context_scope(span_context):
                        try:
                            await self._process_message(message)
                        except Exception:
                            logger.exception("Failed to process Redis message on channel '%s'", self._channel)
                            continue
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the Redis consumer."""
        if self._client:
            await self._client.close()
        self._running = False
        logger.info("Redis consumer stopped")


class RedisAgentProducer:
    """Publish messages to a Redis Pub/Sub channel.

    Satisfies the :class:`~fireflyframework_genai.exposure.queues.base.QueueProducer`
    protocol.

    Parameters:
        channel: Redis Pub/Sub channel to publish to.
        url: Redis connection URL.
    """

    def __init__(
        self,
        *,
        channel: str,
        url: str = "redis://localhost:6379",
    ) -> None:
        self._channel = channel
        self._url = url
        self._client: Any = None

    async def start(self) -> None:
        """Open a Redis connection."""
        try:
            import redis.asyncio as aioredis  # type: ignore[import-not-found]
        except ImportError as _err:
            raise ImportError(
                "redis[hiredis] is required for Redis support. "
                "Install it with: pip install fireflyframework-genai[redis]"
            ) from _err

        self._client = aioredis.from_url(self._url)
        logger.info("Redis producer started for channel '%s'", self._channel)

    async def publish(self, message: QueueMessage) -> None:
        """Publish *message* to the configured Redis channel."""
        if self._client is None:
            await self.start()
        await self._client.publish(self._channel, message.body.encode("utf-8"))

    async def stop(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
        logger.info("Redis producer stopped")
