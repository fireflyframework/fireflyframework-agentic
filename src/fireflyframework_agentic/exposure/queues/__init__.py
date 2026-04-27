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

"""Queues exposure subpackage -- Kafka, RabbitMQ, Redis consumers, producers, and routing."""

from fireflyframework_agentic.exposure.queues.base import (
    BaseQueueConsumer,
    QueueConsumer,
    QueueMessage,
    QueueProducer,
)
from fireflyframework_agentic.exposure.queues.router import QueueRouter

__all__ = [
    "BaseQueueConsumer",
    "QueueConsumer",
    "QueueMessage",
    "QueueProducer",
    "QueueRouter",
]


def __getattr__(name: str):
    """Lazy-load queue backend implementations so the package works without
    their optional dependencies (aiokafka, aio-pika, redis) installed."""
    _kafka_names = {"KafkaAgentConsumer", "KafkaAgentProducer"}
    _rabbitmq_names = {"RabbitMQAgentConsumer", "RabbitMQAgentProducer"}
    _redis_names = {"RedisAgentConsumer", "RedisAgentProducer"}

    if name in _kafka_names:
        from fireflyframework_agentic.exposure.queues.kafka import (
            KafkaAgentConsumer,
            KafkaAgentProducer,
        )

        return {"KafkaAgentConsumer": KafkaAgentConsumer, "KafkaAgentProducer": KafkaAgentProducer}[name]

    if name in _rabbitmq_names:
        from fireflyframework_agentic.exposure.queues.rabbitmq import (
            RabbitMQAgentConsumer,
            RabbitMQAgentProducer,
        )

        return {"RabbitMQAgentConsumer": RabbitMQAgentConsumer, "RabbitMQAgentProducer": RabbitMQAgentProducer}[name]

    if name in _redis_names:
        from fireflyframework_agentic.exposure.queues.redis import (
            RedisAgentConsumer,
            RedisAgentProducer,
        )

        return {"RedisAgentConsumer": RedisAgentConsumer, "RedisAgentProducer": RedisAgentProducer}[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
