# Exposure Queues Guide

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

The Exposure Queues module provides an abstract consumer/producer model with concrete
implementations for Apache Kafka, RabbitMQ, and Redis Pub/Sub, plus a pattern-based
message router.

---

## Architecture

```mermaid
flowchart TD
    subgraph Message Brokers
        KAFKA[Apache Kafka]
        RABBIT[RabbitMQ]
        REDIS[Redis Pub/Sub]
    end

    subgraph Consumers
        KC[KafkaAgentConsumer]
        RC[RabbitMQAgentConsumer]
        RDC[RedisAgentConsumer]
    end

    KAFKA --> KC
    RABBIT --> RC
    REDIS --> RDC

    KC --> ROUTER[QueueRouter]
    RC --> ROUTER
    RDC --> ROUTER
    ROUTER --> REG[Agent Registry]
    REG --> AGENT[Agent]
```

---

## Quick Start

Install the queue extra for your broker:

```bash
uv add "fireflyframework-genai[kafka]" # Kafka
uv add "fireflyframework-genai[rabbitmq]" # RabbitMQ
uv add "fireflyframework-genai[redis]" # Redis
uv add "fireflyframework-genai[queues]" # All brokers
```

### Kafka

```python
from fireflyframework_genai.exposure.queues.kafka import KafkaAgentConsumer

consumer = KafkaAgentConsumer(
    agent_name="assistant",
    topic="genai-requests",
    bootstrap_servers="localhost:9092",
    group_id="genai-workers",
)
await consumer.start()
```

### RabbitMQ

```python
from fireflyframework_genai.exposure.queues.rabbitmq import RabbitMQAgentConsumer

consumer = RabbitMQAgentConsumer(
    agent_name="assistant",
    queue_name="genai-requests",
    url="amqp://guest:guest@localhost/",
)
await consumer.start()
```

### Redis

```python
from fireflyframework_genai.exposure.queues.redis import RedisAgentConsumer

consumer = RedisAgentConsumer(
    agent_name="assistant",
    channel="genai-requests",
    url="redis://localhost:6379",
)
await consumer.start()
```

---

## QueueMessage

All consumers and producers operate on `QueueMessage` objects:

```python
from fireflyframework_genai.exposure.queues import QueueMessage

message = QueueMessage(
    body="Summarise this document.",
    headers={"user": "alice"},
    routing_key="summarisation",
    reply_to="response-queue",
)
```

---

## Queue Router

The `QueueRouter` maps incoming messages to agents based on routing-key patterns.
This is useful when a single consumer receives messages for multiple agents.

```mermaid
flowchart TD
    MSG[Incoming Message] --> QR[QueueRouter]
    QR -->|routing_key ~ 'summary.*'| A1[Summariser Agent]
    QR -->|routing_key ~ 'translate.*'| A2[Translator Agent]
    QR -->|no match| A3[Default Agent]
```

```python
from fireflyframework_genai.exposure.queues import QueueRouter, QueueMessage

router = QueueRouter(default_agent="fallback")
router.add_route(r"summary\..*", "summariser")
router.add_route(r"translate\..*", "translator")

message = QueueMessage(body="Bonjour", routing_key="translate.fr")
response = await router.route(message)
```

---

## Creating a Custom Consumer

To integrate with a message broker not supported out of the box, extend
`BaseQueueConsumer` and implement the `start` and `stop` methods:

```python
from fireflyframework_genai.exposure.queues.base import BaseQueueConsumer

class MyBrokerConsumer(BaseQueueConsumer):
    async def start(self) -> None:
        # Connect to the broker and begin consuming
        ...

    async def stop(self) -> None:
        # Disconnect
        ...
```

The base class provides `_process_message(message)` which routes the message to the
configured agent automatically.

---

## Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created
    Created --> Running : start()
    Running --> Running : process message
    Running --> Stopped : stop()
    Stopped --> [*]
```

Consumers are designed to be long-running. Call `start()` to connect and begin
processing, and `stop()` to shut down gracefully.
