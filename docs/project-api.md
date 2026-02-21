# Per-Project API

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

Every Studio project gets an auto-generated set of REST endpoints for
running pipelines, managing the runtime, and querying execution history.
A GraphQL endpoint and WebSocket streaming protocol are also available.

---

## REST Endpoints

All project endpoints are scoped under `/api/projects/{name}/`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/{name}/run` | Synchronous pipeline execution |
| `POST` | `/{name}/run/async` | Asynchronous execution (returns immediately) |
| `GET` | `/{name}/runs/{execution_id}` | Poll an async execution result |
| `POST` | `/{name}/upload` | Trigger pipeline via file upload |
| `GET` | `/{name}/schema` | Retrieve input/output schema |
| `POST` | `/{name}/runtime/start` | Start the project runtime |
| `POST` | `/{name}/runtime/stop` | Stop the project runtime |
| `GET` | `/{name}/runtime/status` | Query runtime status |
| `GET` | `/{name}/runtime/executions` | List recent executions |

### Synchronous Execution

```bash
curl -X POST http://localhost:8470/api/projects/my-project/run \
  -H "Content-Type: application/json" \
  -d '{"input": "Classify this document"}'
```

Response:

```json
{
  "result": "invoice",
  "execution_id": "a1b2c3d4-...",
  "duration_ms": 1234.56
}
```

### Asynchronous Execution

Start a run that returns immediately:

```bash
curl -X POST http://localhost:8470/api/projects/my-project/run/async \
  -H "Content-Type: application/json" \
  -d '{"input": "Process this batch"}'
```

Response:

```json
{"execution_id": "e5f6g7h8-...", "status": "running"}
```

Poll for results:

```bash
curl http://localhost:8470/api/projects/my-project/runs/e5f6g7h8-...
```

Response (when complete):

```json
{
  "execution_id": "e5f6g7h8-...",
  "status": "completed",
  "result": "...",
  "duration_ms": 5678.90
}
```

Status values: `running`, `completed`, `failed`.

### File Upload

```bash
curl -X POST http://localhost:8470/api/projects/my-project/upload \
  -F "file=@document.pdf"
```

The uploaded file is passed to the pipeline as:

```json
{
  "file_name": "document.pdf",
  "content_type": "application/pdf",
  "content": "<decoded text>",
  "size": 45321
}
```

### Schema Introspection

```bash
curl http://localhost:8470/api/projects/my-project/schema
```

Response:

```json
{
  "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
  "output_schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
  "trigger_type": "http"
}
```

Returns `null` for fields when no Input/Output nodes are configured.

### Runtime Management

Start the runtime (queue consumers, schedulers):

```bash
curl -X POST http://localhost:8470/api/projects/my-project/runtime/start
# {"status": "running"}
```

Check status:

```bash
curl http://localhost:8470/api/projects/my-project/runtime/status
```

```json
{
  "project": "my-project",
  "status": "running",
  "trigger_type": "queue",
  "consumers": 1,
  "scheduler_active": false
}
```

Stop the runtime:

```bash
curl -X POST http://localhost:8470/api/projects/my-project/runtime/stop
# {"status": "stopped"}
```

### Execution History

```bash
curl http://localhost:8470/api/projects/my-project/runtime/executions
```

```json
{
  "executions": [
    {"execution_id": "a1b2c3d4-...", "status": "completed", "duration_ms": 1234.56},
    {"execution_id": "e5f6g7h8-...", "status": "failed", "duration_ms": 890.12}
  ]
}
```

---

## Client Examples

### Python

```python
import httpx

BASE = "http://localhost:8470/api/projects/my-project"

# Synchronous run
resp = httpx.post(f"{BASE}/run", json={"input": "Hello"})
print(resp.json()["result"])

# Async run with polling
resp = httpx.post(f"{BASE}/run/async", json={"input": "Long task"})
eid = resp.json()["execution_id"]

import time
while True:
    status = httpx.get(f"{BASE}/runs/{eid}").json()
    if status["status"] != "running":
        print(status["result"])
        break
    time.sleep(1)

# File upload
with open("invoice.pdf", "rb") as f:
    resp = httpx.post(f"{BASE}/upload", files={"file": f})
    print(resp.json()["result"])
```

### TypeScript / JavaScript

```typescript
const BASE = "http://localhost:8470/api/projects/my-project";

// Synchronous run
const res = await fetch(`${BASE}/run`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ input: "Classify this" }),
});
const { result, execution_id, duration_ms } = await res.json();

// Async run with polling
const asyncRes = await fetch(`${BASE}/run/async`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ input: "Process batch" }),
});
const { execution_id: eid } = await asyncRes.json();

const poll = async () => {
  while (true) {
    const status = await fetch(`${BASE}/runs/${eid}`).then((r) => r.json());
    if (status.status !== "running") return status;
    await new Promise((r) => setTimeout(r, 1000));
  }
};
const final = await poll();
```

---

## WebSocket Streaming

For real-time execution events, connect to `/ws/execution`:

```javascript
const ws = new WebSocket("ws://localhost:8470/ws/execution");

ws.onopen = () => {
  ws.send(JSON.stringify({
    action: "run",
    graph: { nodes: [...], edges: [...], metadata: {} },
    inputs: "Hello world",
  }));
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  // msg.type: "node_start" | "node_complete" | "node_error" |
  //           "pipeline_complete" | "pipeline_result"
  console.log(msg.type, msg);
};
```

Event types:

| Type | Key Fields |
|---|---|
| `node_start` | `node_id`, `pipeline_name` |
| `node_complete` | `node_id`, `pipeline_name`, `latency_ms` |
| `node_error` | `node_id`, `pipeline_name`, `error` |
| `pipeline_complete` | `pipeline_name`, `success`, `duration_ms` |
| `pipeline_result` | `success`, `output`, `duration_ms` |

---

## GraphQL API

A Strawberry-based GraphQL endpoint is available at `/api/graphql`.
Requires `strawberry-graphql` to be installed (falls back to a 501 stub
otherwise).

### Schema Types

```graphql
type Project {
  name: String!
  description: String!
  createdAt: String!
}

type RuntimeStatus {
  project: String!
  status: String!
  triggerType: String
  consumers: Int!
  schedulerActive: Boolean!
}

type ExecutionResult {
  executionId: String!
  status: String!
  result: String
  durationMs: Float
}
```

### Queries

```graphql
# List all projects
query {
  projects {
    name
    description
    createdAt
  }
}

# Get a single project
query {
  project(name: "my-project") {
    name
    description
  }
}

# Check runtime status
query {
  runtimeStatus(project: "my-project") {
    status
    triggerType
    consumers
    schedulerActive
  }
}
```

### Mutations

```graphql
# Run a pipeline
mutation {
  runPipeline(project: "my-project", input: "Classify this document") {
    executionId
    status
    result
    durationMs
  }
}
```

### curl Example

```bash
curl -X POST http://localhost:8470/api/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ projects { name description } }"}'
```

---

## Schema Generation

Input/Output schemas are extracted from the pipeline's boundary nodes.
The `/api/projects/{name}/schema` endpoint reads the saved pipeline graph,
finds nodes with type `input` and `output`, and returns their schemas.

This enables API consumers to discover what a project expects and returns
without inspecting the pipeline visually.

---

*See also: [Input/Output Nodes](input-output-nodes.md) for boundary node
configuration, [API Reference](api-reference.md) for the complete endpoint
listing, [Tunnel Exposure](tunnel-exposure.md) for sharing externally.*
