# Input/Output Boundary Nodes

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

Input and Output nodes define pipeline entry and exit points, inspired by
BPM (Business Process Management) start/end events. They enable a pipeline
to declare *how* it receives data and *where* results go, which unlocks
auto-generated APIs, queue consumers, scheduled triggers, and runtime
management.

---

## Why Boundary Nodes Matter

Without boundary nodes a pipeline is a passive graph of processing steps --
you must write glue code to feed it data and route results. With boundary
nodes, the Studio runtime can:

1. Auto-generate REST endpoints from the pipeline schema.
2. Spin up queue consumers (Kafka, RabbitMQ, Redis) automatically.
3. Run pipelines on a cron schedule via APScheduler.
4. Validate inputs and outputs at the API boundary.
5. Route results to webhooks, stores, or multiple destinations.

A pipeline must have **exactly one Input node** and **at least one Output
node** when boundary nodes are used. The compiler enforces this constraint.

---

## Input Node

The Input node defines how data enters the pipeline.

### Trigger Types

| Trigger | Description | Config Object |
|---|---|---|
| `manual` | Triggered by the user or REST API call | None required |
| `http` | Triggered by an HTTP request to the auto-generated endpoint | `HttpConfig` |
| `queue` | Triggered by messages from a message broker | `QueueConfig` |
| `schedule` | Triggered on a cron schedule | `ScheduleConfig` |
| `file_upload` | Triggered by a file upload to `/upload` | `FileConfig` |

### Configuration Examples

**Manual trigger** (simplest -- no extra config needed):

```json
{
  "type": "input",
  "data": {
    "trigger_type": "manual",
    "schema": {
      "type": "object",
      "properties": {
        "query": {"type": "string"}
      },
      "required": ["query"]
    }
  }
}
```

**HTTP trigger** with custom settings:

```json
{
  "type": "input",
  "data": {
    "trigger_type": "http",
    "http_config": {
      "method": "POST",
      "path_suffix": "",
      "auth_required": false
    },
    "schema": {
      "type": "object",
      "properties": {
        "document": {"type": "string"},
        "language": {"type": "string"}
      }
    }
  }
}
```

**Queue trigger** (Kafka):

```json
{
  "type": "input",
  "data": {
    "trigger_type": "queue",
    "queue_config": {
      "broker": "kafka",
      "topic_or_queue": "incoming-documents",
      "group_id": "studio-doc-processor",
      "connection_url": "localhost:9092"
    }
  }
}
```

**Scheduled trigger** (cron):

```json
{
  "type": "input",
  "data": {
    "trigger_type": "schedule",
    "schedule_config": {
      "cron_expression": "0 */6 * * *",
      "timezone": "America/New_York",
      "payload": {"source": "scheduled_run"}
    }
  }
}
```

**File upload trigger**:

```json
{
  "type": "input",
  "data": {
    "trigger_type": "file_upload",
    "file_config": {
      "accepted_types": ["application/pdf", "text/plain"],
      "max_size_mb": 25
    }
  }
}
```

---

## Output Node

The Output node defines where pipeline results are delivered.

### Destination Types

| Destination | Description | Config Object |
|---|---|---|
| `response` | Return result in the HTTP response (default) | None required |
| `queue` | Publish result to a message broker | `QueueConfig` |
| `webhook` | POST result to an external URL | `WebhookConfig` |
| `store` | Write result to a file or database | `StoreConfig` |
| `multi` | Fan out to multiple destinations | `destinations` list |

### Configuration Examples

**Response destination** (return to caller):

```json
{
  "type": "output",
  "data": {
    "destination_type": "response",
    "response_schema": {
      "type": "object",
      "properties": {
        "classification": {"type": "string"},
        "confidence": {"type": "number"}
      }
    }
  }
}
```

**Webhook destination**:

```json
{
  "type": "output",
  "data": {
    "destination_type": "webhook",
    "webhook_config": {
      "url": "https://api.example.com/results",
      "method": "POST",
      "headers": {"Authorization": "Bearer sk-..."}
    }
  }
}
```

**Queue destination** (RabbitMQ):

```json
{
  "type": "output",
  "data": {
    "destination_type": "queue",
    "queue_config": {
      "broker": "rabbitmq",
      "topic_or_queue": "processed-results",
      "connection_url": "amqp://localhost"
    }
  }
}
```

**Store destination** (file):

```json
{
  "type": "output",
  "data": {
    "destination_type": "store",
    "store_config": {
      "storage_type": "file",
      "path_or_table": "/data/results/"
    }
  }
}
```

**Multi destination** (fan out to several targets):

```json
{
  "type": "output",
  "data": {
    "destination_type": "multi",
    "destinations": [
      {"type": "response"},
      {"type": "webhook", "url": "https://hooks.example.com/notify"}
    ]
  }
}
```

---

## Schema Definition

Both Input and Output nodes support JSON Schema-style `schema` /
`response_schema` fields. These serve two purposes:

1. **Validation** -- The API layer can validate incoming payloads against
   the input schema before pipeline execution begins.
2. **Documentation** -- The `/api/projects/{name}/schema` endpoint exposes
   the schema so API consumers know what to send and expect.

```python
# Retrieve a project's schema programmatically
import httpx

resp = httpx.get("http://localhost:8470/api/projects/my-project/schema")
schema = resp.json()
# {
#   "input_schema": {"type": "object", "properties": {...}},
#   "output_schema": {"type": "object", "properties": {...}},
#   "trigger_type": "http"
# }
```

---

## Compiler Interaction

When the pipeline compiler encounters Input/Output nodes it enforces
structural constraints and compiles them into pass-through steps:

- **Input node**: Validates the `InputNodeConfig` at compile time, then
  becomes a `CallableStep` that forwards `context.inputs` downstream.
  Schema validation happens at the API boundary, not inside the step.
- **Output node**: Validates the `OutputNodeConfig` and becomes a
  `CallableStep` that stores the output config in `context.metadata` and
  passes the result through. Destination routing (queue publish, webhook
  POST, etc.) is handled by `ProjectRuntime` after execution completes.

Compiler constraints:

| Rule | Error |
|---|---|
| More than one Input node | `CompilationError`: must have exactly one |
| Input node without any Output node | `CompilationError`: at least one Output required |
| Invalid trigger/destination type | `ValidationError` from Pydantic |

---

## Python Data Models

The configuration models live in
`fireflyframework_genai.studio.execution.io_nodes`:

```python
from fireflyframework_genai.studio.execution.io_nodes import (
    InputNodeConfig,
    OutputNodeConfig,
    QueueConfig,
    ScheduleConfig,
    HttpConfig,
    FileConfig,
    WebhookConfig,
    StoreConfig,
)

# Create an input config
input_cfg = InputNodeConfig(
    trigger_type="queue",
    queue_config=QueueConfig(
        broker="kafka",
        topic_or_queue="events",
    ),
)

# Create an output config
output_cfg = OutputNodeConfig(
    destination_type="webhook",
    webhook_config=WebhookConfig(url="https://hooks.example.com"),
)
```

---

*See also: [Project API](project-api.md) for auto-generated REST endpoints,
[Scheduling](scheduling.md) for cron configuration,
[Pipeline Guide](pipeline.md) for the broader pipeline system.*
