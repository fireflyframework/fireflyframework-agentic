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

"""RabbitMQ consumer for agent exposure.

Requires the ``aio-pika`` optional dependency (install via
``pip install fireflyframework-genai[rabbitmq]``).
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fireflyframework_genai.exposure.queues.base import BaseQueueConsumer, QueueMessage

logger = logging.getLogger(__name__)


class RabbitMQAgentConsumer(BaseQueueConsumer):
    """Consume messages from a RabbitMQ queue and route to an agent.

    Parameters:
        agent_name: Name of the agent to invoke.
        queue_name: RabbitMQ queue to consume from.
        url: AMQP connection URL.
    """

    def __init__(
        self,
        agent_name: str,
        *,
        queue_name: str,
        url: str = "amqp://guest:guest@localhost/",
    ) -> None:
        super().__init__(agent_name)
        self._queue_name = queue_name
        self._url = url
        self._connection: Any = None

    async def start(self) -> None:
        """Connect to RabbitMQ and begin consuming."""
        try:
            import aio_pika  # type: ignore[import-not-found]
        except ImportError as _err:
            raise ImportError(
                "aio-pika is required for RabbitMQ support. "
                "Install it with: pip install fireflyframework-genai[rabbitmq]"
            ) from _err

        self._connection = await aio_pika.connect_robust(self._url)
        channel = await self._connection.channel()
        queue = await channel.declare_queue(self._queue_name, durable=True)
        self._running = True
        logger.info("RabbitMQ consumer started on queue '%s'", self._queue_name)

        async with queue.iterator() as queue_iter:
            async for amqp_message in queue_iter:
                async with amqp_message.process():
                    # Extract trace context from message headers for distributed tracing
                    from fireflyframework_genai.observability.tracer import extract_trace_context, trace_context_scope

                    headers = {}
                    if amqp_message.headers:
                        headers = {k: str(v) for k, v in amqp_message.headers.items()}
                    span_context = extract_trace_context(headers)

                    message = QueueMessage(body=amqp_message.body.decode("utf-8"))

                    # Process message within trace context scope
                    with trace_context_scope(span_context):
                        try:
                            await self._process_message(message)
                        except Exception:
                            logger.exception("Failed to process RabbitMQ message on queue '%s'", self._queue_name)
                            continue

    async def stop(self) -> None:
        """Stop the RabbitMQ consumer."""
        if self._connection:
            await self._connection.close()
        self._running = False
        logger.info("RabbitMQ consumer stopped")


class RabbitMQAgentProducer:
    """Publish messages to a RabbitMQ exchange.

    Satisfies the :class:`~fireflyframework_genai.exposure.queues.base.QueueProducer`
    protocol.

    Parameters:
        exchange_name: RabbitMQ exchange to publish to.  Use ``""`` for the
            default exchange (messages are routed by *routing_key* directly
            to a queue).
        url: AMQP connection URL.
    """

    def __init__(
        self,
        *,
        exchange_name: str = "",
        url: str = "amqp://guest:guest@localhost/",
    ) -> None:
        self._exchange_name = exchange_name
        self._url = url
        self._connection: Any = None
        self._channel: Any = None

    async def start(self) -> None:
        """Open a connection and channel."""
        try:
            import aio_pika  # type: ignore[import-not-found]
        except ImportError as _err:
            raise ImportError(
                "aio-pika is required for RabbitMQ support. "
                "Install it with: pip install fireflyframework-genai[rabbitmq]"
            ) from _err

        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        logger.info("RabbitMQ producer started (exchange='%s')", self._exchange_name)

    async def publish(self, message: QueueMessage) -> None:
        """Publish *message* to the configured exchange."""
        import aio_pika  # type: ignore[import-not-found]

        if self._channel is None:
            await self.start()

        exchange = (
            await self._channel.get_exchange(self._exchange_name)
            if self._exchange_name
            else self._channel.default_exchange
        )
        amqp_message = aio_pika.Message(
            body=message.body.encode("utf-8"),
            headers=cast("dict[str, Any]", message.headers) or None,
            reply_to=message.reply_to or None,
        )
        await exchange.publish(amqp_message, routing_key=message.routing_key)

    async def stop(self) -> None:
        """Close the connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            self._channel = None
        logger.info("RabbitMQ producer stopped")
