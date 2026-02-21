# Tutorial: Building a BPM Pipeline

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

This tutorial walks through building a document processing pipeline
end-to-end using Input/Output boundary nodes, the per-project REST API,
and Cloudflare Tunnel exposure. By the end you will have a pipeline that
accepts documents via HTTP, classifies and summarizes them, and returns
structured results -- accessible from anywhere.

---

## Prerequisites

```bash
pip install "fireflyframework-genai[studio]"
```

You need a configured AI provider (OpenAI, Anthropic, etc.). Set your API
key as an environment variable or through the Studio Settings modal.

---

## Step 1: Create a Project

Launch Studio and create a new project:

```bash
firefly studio
```

In the browser, click **New Project** in the sidebar and name it
`doc-processor`. Or use the API:

```bash
curl -X POST http://localhost:8470/api/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "doc-processor", "description": "Document classification and summarization"}'
```

---

## Step 2: Add an Input Node with HTTP Trigger

Drag an **Input** node from the palette onto the canvas. Select it and
configure:

- **Trigger Type**: `http`
- **Schema** (JSON):

```json
{
  "type": "object",
  "properties": {
    "document": {
      "type": "string",
      "description": "The document text to process"
    },
    "language": {
      "type": "string",
      "description": "ISO 639-1 language code",
      "default": "en"
    }
  },
  "required": ["document"]
}
```

This tells Studio that the pipeline expects a `document` string and an
optional `language` field.

---

## Step 3: Add Agent Nodes for Processing

### Classifier Agent

Drag an **Agent** node onto the canvas. Configure it:

- **Label**: `Classifier`
- **Model**: `openai:gpt-4o` (or your preferred model)
- **Instructions**:

```
Classify the given document into one of these categories:
invoice, contract, report, letter, other.
Return ONLY the category name, no explanation.
```

Connect the Input node's output handle to the Classifier's input handle.

### Summarizer Agent

Drag another **Agent** node. Configure it:

- **Label**: `Summarizer`
- **Model**: `openai:gpt-4o`
- **Instructions**:

```
Summarize the document in 2-3 sentences.
Focus on the key facts and action items.
```

Connect the Input node to the Summarizer as well (both agents receive the
original input in parallel).

---

## Step 4: Add an Output Node with Response Destination

Drag an **Output** node onto the canvas. Configure it:

- **Destination Type**: `response`
- **Response Schema** (JSON):

```json
{
  "type": "object",
  "properties": {
    "classification": {"type": "string"},
    "summary": {"type": "string"}
  }
}
```

Connect both the Classifier and Summarizer to the Output node. The Output
node collects results from upstream nodes and returns them in the HTTP
response.

### Canvas Layout

```
  [Input: HTTP] --+--> [Classifier] --+--> [Output: Response]
                  |                    |
                  +--> [Summarizer] ---+
```

---

## Step 5: Configure Schema Validation

Save the pipeline using `Cmd/Ctrl + S` or via the API:

```bash
curl -X POST http://localhost:8470/api/projects/doc-processor/pipelines/main \
  -H "Content-Type: application/json" \
  -d '{"graph": {"nodes": [...], "edges": [...]}}'
```

Verify the schema is exposed:

```bash
curl http://localhost:8470/api/projects/doc-processor/schema
```

Expected:

```json
{
  "input_schema": {
    "type": "object",
    "properties": {
      "document": {"type": "string"},
      "language": {"type": "string"}
    },
    "required": ["document"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "classification": {"type": "string"},
      "summary": {"type": "string"}
    }
  },
  "trigger_type": "http"
}
```

---

## Step 6: Start the Runtime

Click the **Play** button in the Studio top bar, or use the API:

```bash
curl -X POST http://localhost:8470/api/projects/doc-processor/runtime/start
# {"status": "running"}
```

Verify the runtime is active:

```bash
curl http://localhost:8470/api/projects/doc-processor/runtime/status
# {"project": "doc-processor", "status": "running", "trigger_type": "http", ...}
```

---

## Step 7: Test via the API

### Synchronous Run

```bash
curl -X POST http://localhost:8470/api/projects/doc-processor/run \
  -H "Content-Type: application/json" \
  -d '{
    "input": "INVOICE #2024-001\nDate: 2026-01-15\nFrom: Acme Corp\nTo: Widget Inc\nAmount: $5,000.00\nTerms: Net 30\nDescription: Consulting services for Q4 2025"
  }'
```

Expected response:

```json
{
  "result": {
    "classification": "invoice",
    "summary": "Invoice #2024-001 from Acme Corp to Widget Inc for $5,000 in consulting services, due Net 30 from January 15, 2026."
  },
  "execution_id": "abc123...",
  "duration_ms": 2345.67
}
```

### Async Run

```bash
# Start async
curl -X POST http://localhost:8470/api/projects/doc-processor/run/async \
  -H "Content-Type: application/json" \
  -d '{"input": "Dear Sir/Madam, We are writing to confirm..."}'

# Poll
curl http://localhost:8470/api/projects/doc-processor/runs/<execution_id>
```

### File Upload

```bash
curl -X POST http://localhost:8470/api/projects/doc-processor/upload \
  -F "file=@contract.txt"
```

### Python Client

```python
import httpx

resp = httpx.post(
    "http://localhost:8470/api/projects/doc-processor/run",
    json={"input": "Annual Report 2025: Revenue grew 15% year-over-year..."},
)
result = resp.json()
print(f"Type: {result['result']['classification']}")
print(f"Summary: {result['result']['summary']}")
```

---

## Step 8: Expose via Tunnel

Open a second terminal and start a Cloudflare Tunnel:

```bash
firefly expose --port 8470
```

Output:

```
Studio is now publicly accessible at: https://random-words.trycloudflare.com
Press Ctrl+C to stop the tunnel.
```

Or click the **Share** button in the Studio top bar to start the tunnel
from the UI.

Now test from an external machine or service:

```bash
TUNNEL="https://random-words.trycloudflare.com"

curl -X POST "$TUNNEL/api/projects/doc-processor/run" \
  -H "Content-Type: application/json" \
  -d '{"input": "This agreement is entered into by..."}'
```

The public URL works for all project API endpoints, WebSocket connections,
and GraphQL queries.

---

## Next Steps

- **Add a Validator node** between the agents and the Output to enforce
  result quality (e.g., check that the classification is one of the
  allowed values).
- **Switch to a queue trigger** to process documents from Kafka or
  RabbitMQ instead of HTTP.
- **Add a schedule trigger** to run a daily batch job.
- **Use the Evaluation Lab** to test the pipeline against a JSONL dataset
  of labeled documents.
- **Deploy** the generated Python code to production.

---

*See also: [Input/Output Nodes](input-output-nodes.md),
[Project API](project-api.md), [Scheduling](scheduling.md),
[Tunnel Exposure](tunnel-exposure.md).*
