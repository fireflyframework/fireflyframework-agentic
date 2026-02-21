# API Reference

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

Complete reference for all Firefly Agentic Studio API endpoints. The server
runs on `http://127.0.0.1:8470` by default.

---

## Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Server health check |

**Response**: `{"status": "ok", "version": "26.02.07"}`

---

## Settings

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/settings` | Current settings (API keys masked) |
| `POST` | `/api/settings` | Save / merge settings |
| `GET` | `/api/settings/status` | First-start and setup status |

**POST /api/settings** body:

```json
{
  "credentials": {"openai_api_key": "sk-...", "anthropic_api_key": null},
  "model_defaults": {"default_model": "openai:gpt-4o", "temperature": 0.7, "retries": 3},
  "setup_complete": true
}
```

Fields set to `null` preserve existing values.

**GET /api/settings/status** response:

```json
{"first_start": false, "setup_complete": true}
```

---

## Projects

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create a project |
| `DELETE` | `/api/projects/{name}` | Delete a project |
| `POST` | `/api/projects/{project}/pipelines/{pipeline}` | Save pipeline graph |
| `GET` | `/api/projects/{project}/pipelines/{pipeline}` | Load pipeline graph |
| `GET` | `/api/projects/{name}/history` | List version history |
| `GET` | `/api/projects/{name}/history/{version}` | Get specific version |

**POST /api/projects** body:

```json
{"name": "my-project", "description": "Optional description"}
```

**Save pipeline** body:

```json
{"graph": {"nodes": [...], "edges": [...], "metadata": {}}}
```

---

## Registry

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/registry/agents` | List registered agents |
| `GET` | `/api/registry/tools` | List registered tools |
| `GET` | `/api/registry/patterns` | List reasoning patterns |

Each returns an array of `{"name": "...", "description": "..."}` objects.

---

## Execution (WebSocket)

| Protocol | Path | Description |
|---|---|---|
| `WS` | `/ws/execution` | Real-time pipeline execution |

**Send** (run):

```json
{
  "action": "run",
  "graph": {"nodes": [...], "edges": [...], "metadata": {}},
  "inputs": "user input string"
}
```

**Send** (debug):

```json
{
  "action": "debug",
  "graph": {"nodes": [...], "edges": [...]},
  "inputs": "optional"
}
```

**Receive** events:

| Type | Fields |
|---|---|
| `node_start` | `node_id`, `pipeline_name` |
| `node_complete` | `node_id`, `pipeline_name`, `latency_ms` |
| `node_error` | `node_id`, `pipeline_name`, `error` |
| `node_skip` | `node_id`, `pipeline_name`, `reason` |
| `pipeline_complete` | `pipeline_name`, `success`, `duration_ms` |
| `pipeline_result` | `success`, `output`, `duration_ms`, `pipeline_name` |

---

## Checkpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/checkpoints` | List all checkpoints |
| `GET` | `/api/checkpoints/{index}` | Get checkpoint by index |
| `POST` | `/api/checkpoints/fork` | Fork execution from checkpoint |
| `POST` | `/api/checkpoints/diff` | Diff two checkpoints |
| `DELETE` | `/api/checkpoints` | Clear all checkpoints |

**Checkpoint object**:

```json
{
  "index": 0,
  "node_id": "agent-1",
  "state": {...},
  "inputs": {...},
  "timestamp": "2026-02-21T10:00:00Z",
  "branch_id": "main",
  "parent_index": null
}
```

---

## Code Generation

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/codegen/to-code` | Generate Python code from graph |

**Request**:

```json
{
  "nodes": [{"id": "a1", "type": "agent", "label": "Classifier", "data": {"model": "openai:gpt-4o"}}],
  "edges": [{"id": "e1", "source": "a1", "target": "a2"}]
}
```

**Response**: `{"code": "from fireflyframework_genai.agents import FireflyAgent\n..."}`

---

## Evaluation

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/projects/{name}/datasets/upload` | Upload JSONL dataset |
| `GET` | `/api/projects/{name}/datasets` | List datasets |
| `POST` | `/api/evaluate/run` | Run pipeline against dataset |

**Run evaluation** body:

```json
{
  "project": "my-project",
  "dataset": "tests.jsonl",
  "graph": {"nodes": [...], "edges": [...]}
}
```

---

## Experiments

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/projects/{name}/experiments` | List experiments |
| `POST` | `/api/projects/{name}/experiments` | Create experiment |
| `GET` | `/api/projects/{name}/experiments/{id}` | Get experiment |
| `DELETE` | `/api/projects/{name}/experiments/{id}` | Delete experiment |
| `POST` | `/api/projects/{name}/experiments/{id}/run` | Run variant |

---

## File Browser

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/projects/{name}/files` | List project files |
| `GET` | `/api/projects/{name}/files/{path}` | Read file content |

Security: path traversal protection, binary file rejection, 2 MiB limit.

---

## Monitoring

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/monitoring/usage` | Token usage, costs, latency |

---

## Assistant (WebSocket)

| Protocol | Path | Description |
|---|---|---|
| `WS` | `/ws/assistant` | AI assistant chat |

**Send**:

```json
{"action": "chat", "message": "Add an agent node for classification"}
{"action": "clear_history"}
```

**Receive** (streaming):

| Type | Fields |
|---|---|
| `token` | `content` (partial text) |
| `tool_call` | `tool`, `args` |
| `tool_result` | `tool`, `result` |
| `done` | (end of response) |

---

## Oracle (WebSocket + REST)

| Protocol | Path | Description |
|---|---|---|
| `WS` | `/ws/oracle` | Proactive AI suggestions |
| `GET` | `/api/oracle/notifications` | Pending notifications |
| `POST` | `/api/oracle/dismiss/{id}` | Dismiss a notification |

---

## Project Runtime & Execution

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/projects/{name}/run` | Synchronous pipeline run |
| `POST` | `/api/projects/{name}/run/async` | Async pipeline run |
| `GET` | `/api/projects/{name}/runs/{execution_id}` | Poll async result |
| `POST` | `/api/projects/{name}/upload` | File upload trigger |
| `GET` | `/api/projects/{name}/schema` | Input/output schema |
| `POST` | `/api/projects/{name}/runtime/start` | Start runtime |
| `POST` | `/api/projects/{name}/runtime/stop` | Stop runtime |
| `GET` | `/api/projects/{name}/runtime/status` | Runtime status |
| `GET` | `/api/projects/{name}/runtime/executions` | Execution history |

**Run** body: `{"input": <any>}`

**Runtime status** response:

```json
{
  "project": "my-project",
  "status": "running",
  "trigger_type": "http",
  "consumers": 0,
  "scheduler_active": false
}
```

See [Project API](project-api.md) for full curl examples.

---

## GraphQL

| Protocol | Path | Description |
|---|---|---|
| `POST` | `/api/graphql` | Strawberry GraphQL endpoint |

Requires `strawberry-graphql` to be installed.

**Queries**: `projects`, `project(name)`, `runtimeStatus(project)`

**Mutations**: `runPipeline(project, input)`

```bash
curl -X POST http://localhost:8470/api/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ projects { name description } }"}'
```

See [Project API](project-api.md) for the full schema and examples.

---

## Tunnel

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/tunnel/status` | Tunnel status |
| `POST` | `/api/tunnel/start` | Start Cloudflare Tunnel |
| `POST` | `/api/tunnel/stop` | Stop tunnel |

**Status** response:

```json
{"active": true, "url": "https://random-words.trycloudflare.com", "port": 8470}
```

See [Tunnel Exposure](tunnel-exposure.md) for setup instructions.

---

## Custom Tools

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/custom-tools` | List custom tools |
| `GET` | `/api/custom-tools/catalog` | Pre-built connector catalog |
| `POST` | `/api/custom-tools/catalog/{id}/install` | Install connector |
| `POST` | `/api/custom-tools/catalog/{id}/verify` | Verify connector credentials |
| `GET` | `/api/custom-tools/{name}` | Get tool definition |
| `POST` | `/api/custom-tools` | Create or update tool |
| `DELETE` | `/api/custom-tools/{name}` | Delete tool |
| `POST` | `/api/custom-tools/{name}/test` | Test tool execution |
| `POST` | `/api/custom-tools/{name}/register` | Register in runtime |

**Create tool** body:

```json
{
  "name": "my-webhook",
  "description": "Call an external service",
  "tool_type": "webhook",
  "webhook_url": "https://api.example.com/hook",
  "webhook_method": "POST",
  "parameters": [
    {"name": "message", "type": "string", "required": true}
  ]
}
```

Tool types: `python`, `webhook`, `api`.

---

*See also: [Studio](studio.md) for general documentation,
[Project API](project-api.md) for detailed examples.*
