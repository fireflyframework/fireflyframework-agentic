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

"""Kafka consumer/producer for agent exposure.

Requires the ``aiokafka`` optional dependency (install via
``pip install fireflyframework-genai[kafka]``).
"""

from __future__ import annotations

import logging
from typing import Any

from fireflyframework_genai.exposure.queues.base import BaseQueueConsumer, QueueMessage

logger = logging.getLogger(__name__)


class KafkaAgentConsumer(BaseQueueConsumer):
    """Consume messages from a Kafka topic and route to an agent.

    Parameters:
        agent_name: Name of the agent to invoke.
        topic: Kafka topic to consume from.
        bootstrap_servers: Kafka bootstrap servers.
        group_id: Consumer group ID.
    """

    def __init__(
        self,
        agent_name: str,
        *,
        topic: str,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "firefly-genai",
    ) -> None:
        super().__init__(agent_name)
        self._topic = topic
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._consumer: Any = None

    async def start(self) -> None:
        """Connect to Kafka and begin consuming."""
        try:
            from aiokafka import AIOKafkaConsumer  # type: ignore[import-not-found]
        except ImportError as _err:
            raise ImportError(
                "aiokafka is required for Kafka support. Install it with: pip install fireflyframework-genai[kafka]"
            ) from _err

        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
        )
        await self._consumer.start()
        self._running = True
        logger.info("Kafka consumer started on topic '%s'", self._topic)

        try:
            async for msg in self._consumer:
                # Extract trace context from message headers for distributed tracing
                from fireflyframework_genai.observability.tracer import extract_trace_context, trace_context_scope

                headers = {k: v.decode("utf-8") if isinstance(v, bytes) else v for k, v in (msg.headers or [])}
                span_context = extract_trace_context(headers)

                message = QueueMessage(body=msg.value.decode("utf-8"))

                # Process message within trace context scope
                with trace_context_scope(span_context):
                    await self._process_message(message)
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the Kafka consumer."""
        if self._consumer:
            await self._consumer.stop()
        self._running = False
        logger.info("Kafka consumer stopped")


class KafkaAgentProducer:
    """Publish messages to a Kafka topic.

    Satisfies the :class:`~fireflyframework_genai.exposure.queues.base.QueueProducer`
    protocol.

    Parameters:
        topic: Kafka topic to publish to.
        bootstrap_servers: Kafka bootstrap servers.
    """

    def __init__(
        self,
        *,
        topic: str,
        bootstrap_servers: str = "localhost:9092",
    ) -> None:
        self._topic = topic
        self._bootstrap_servers = bootstrap_servers
        self._producer: Any = None

    async def start(self) -> None:
        """Connect the underlying Kafka producer."""
        try:
            from aiokafka import AIOKafkaProducer  # type: ignore[import-not-found]
        except ImportError as _err:
            raise ImportError(
                "aiokafka is required for Kafka support. Install it with: pip install fireflyframework-genai[kafka]"
            ) from _err

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
        )
        await self._producer.start()
        logger.info("Kafka producer started for topic '%s'", self._topic)

    async def publish(self, message: QueueMessage) -> None:
        """Publish *message* to the configured Kafka topic."""
        if self._producer is None:
            await self.start()
        await self._producer.send_and_wait(
            self._topic,
            value=message.body.encode("utf-8"),
            headers=[(k, v.encode("utf-8")) for k, v in message.headers.items()] or None,
        )

    async def stop(self) -> None:
        """Flush and stop the Kafka producer."""
        if self._producer:
            await self._producer.stop()
            self._producer = None
        logger.info("Kafka producer stopped")
