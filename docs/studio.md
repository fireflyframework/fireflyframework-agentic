# Firefly Studio

**Visual agent IDE for the Firefly GenAI framework.**

Firefly Studio is a browser-based development environment for building,
testing, and debugging GenAI agent pipelines. It provides a visual canvas
where you drag and connect agent nodes, configure them through a side panel,
and see generated Python code update in real time. An integrated AI assistant
helps you build pipelines through natural language.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [Settings & Provider Credentials](#settings--provider-credentials)
- [Architecture](#architecture)
- [The Canvas](#the-canvas)
- [Node Types](#node-types)
- [Code Generation](#code-generation)
- [AI Assistant](#ai-assistant)
- [Project Management](#project-management)
- [Pipeline Execution](#pipeline-execution)
- [Checkpoints & Time-Travel Debugging](#checkpoints--time-travel-debugging)
- [Evaluation Lab](#evaluation-lab)
- [Experiments](#experiments)
- [File Browser](#file-browser)
- [Deploy](#deploy)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Input/Output Boundary Nodes](#inputoutput-boundary-nodes)
- [Project Runtime](#project-runtime)
- [Per-Project API](#per-project-api)
- [Tunnel Exposure (Share)](#tunnel-exposure-share)
- [REST API Reference](#rest-api-reference)
- [WebSocket API Reference](#websocket-api-reference)
- [Desktop App](#desktop-app)
- [Programmatic Usage](#programmatic-usage)
- [Frontend Development](#frontend-development)

---

## Installation

Firefly Studio is included in the `[studio]` extra:

```bash
# Install with Studio support
pip install "fireflyframework-genai[studio]"

# Or with UV
uv add "fireflyframework-genai[studio]"

# Or install everything
pip install "fireflyframework-genai[all]"
```

The `[studio]` extra installs:

| Dependency | Purpose |
|---|---|
| `fastapi` | REST API and WebSocket server |
| `uvicorn[standard]` | ASGI server |
| `httpx` | HTTP client for internal API calls |

The Studio frontend is pre-built and bundled inside the Python package.
No Node.js is required to run Studio.

---

## Quick Start

```bash
# Launch Studio (opens browser automatically)
firefly studio

# Or from Python
python -c "from fireflyframework_genai.studio import launch_studio; launch_studio()"
```

Studio starts at `http://127.0.0.1:8470` by default and opens your browser.

On first launch, a **Setup Wizard** guides you through configuring your
AI provider credentials (OpenAI, Anthropic, Google, etc.) and default model
settings. You can skip the wizard and configure providers later via the
Settings modal (`Cmd/Ctrl + ,`).

After setup, you'll see a dark-themed IDE with a visual canvas, a component
palette on the left, a configuration panel on the right, and a bottom panel
with code generation, console, timeline, and AI assistant tabs.

---

## CLI Reference

The `firefly` command is installed as a console script entry point.

```
firefly studio [OPTIONS]
firefly [OPTIONS]          # "studio" is the default subcommand
firefly expose [OPTIONS]   # expose Studio via Cloudflare Tunnel
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--port PORT` | `8470` | Port the Studio server listens on |
| `--host HOST` | `127.0.0.1` | Address the server binds to |
| `--no-browser` | `false` | Do not open the browser automatically |
| `--dev` | `false` | Enable development mode (verbose logging) |

### Examples

```bash
# Default launch
firefly studio

# Custom port, no browser
firefly studio --port 9000 --no-browser

# Bind to all interfaces (for remote access)
firefly studio --host 0.0.0.0

# Shorthand (omit "studio")
firefly --port 9000
```

---

## Configuration

Studio uses Pydantic Settings with the `FIREFLY_STUDIO_` prefix for
environment variable overrides.

### StudioConfig Fields

| Field | Type | Default | Env Variable |
|---|---|---|---|
| `host` | `str` | `"127.0.0.1"` | `FIREFLY_STUDIO_HOST` |
| `port` | `int` | `8470` | `FIREFLY_STUDIO_PORT` |
| `open_browser` | `bool` | `True` | `FIREFLY_STUDIO_OPEN_BROWSER` |
| `dev_mode` | `bool` | `False` | `FIREFLY_STUDIO_DEV_MODE` |
| `projects_dir` | `Path` | `~/.firefly-studio/projects` | `FIREFLY_STUDIO_PROJECTS_DIR` |
| `log_level` | `str` | `"info"` | `FIREFLY_STUDIO_LOG_LEVEL` |

### Environment Variable Example

```bash
export FIREFLY_STUDIO_PORT=9000
export FIREFLY_STUDIO_PROJECTS_DIR=/data/studio/projects
export FIREFLY_STUDIO_DEV_MODE=true
firefly studio
```

---

## Settings & Provider Credentials

Studio provides a built-in Settings system for managing AI provider
credentials and model defaults directly from the UI — no manual
environment variables required.

### How It Works

Settings are persisted at `~/.firefly-studio/settings.json` with `0600`
(owner-only) file permissions. On startup, saved API keys are injected
into `os.environ` so that PydanticAI picks them up via its standard
provider env vars. **Existing environment variables always take
precedence** over saved settings.

### First-Start Wizard

On first launch (no `settings.json` found), a 5-step wizard appears:

1. **Welcome** — Introduction to Studio
2. **Select Providers** — Choose which providers to configure (OpenAI
   pre-selected)
3. **Enter Keys** — Password inputs for selected providers only
4. **Default Model** — Set default model string, temperature, and retries
5. **Done** — Confirmation and "Open Studio" button

You can skip the wizard at any time — Studio works without credentials
if you've set API keys as environment variables.

### Settings Modal

Open the Settings modal anytime via:
- **Gear icon** in the top bar
- **Keyboard shortcut:** `Cmd/Ctrl + ,`
- **Command palette:** type "Settings"

The modal has two tabs:

| Tab | Contents |
|---|---|
| **Provider Credentials** | API key inputs for each provider, "Configured" badge for active keys |
| **Model Defaults** | Default model string, temperature slider (0–2), retries count |

### Supported Providers

| Provider | Credential Fields | Env Variable(s) |
|---|---|---|
| OpenAI | API Key | `OPENAI_API_KEY` |
| Anthropic | API Key | `ANTHROPIC_API_KEY` |
| Google Gemini | API Key | `GOOGLE_API_KEY` |
| Groq | API Key | `GROQ_API_KEY` |
| Mistral | API Key | `MISTRAL_API_KEY` |
| DeepSeek | API Key | `DEEPSEEK_API_KEY` |
| Cohere | API Key | `CO_API_KEY` |
| Azure OpenAI | API Key + Endpoint URL | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` |
| Amazon Bedrock | Access Key + Secret + Region | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` |
| Ollama | Base URL (no key needed) | `OLLAMA_BASE_URL` |

### Settings API

| Endpoint | Method | Description |
|---|---|---|
| `/api/settings` | `GET` | Current settings (API keys masked) |
| `/api/settings` | `POST` | Save/merge settings |
| `/api/settings/status` | `GET` | Check first-start and setup status |

API keys in `GET` responses are always masked (e.g., `****abc1`). The
`POST` endpoint uses merge semantics: `null` credential fields preserve
existing values; non-null values overwrite.

---

## Architecture

Studio is composed of a Python backend (FastAPI) and a SvelteKit 5 frontend
that compiles to a static SPA and is bundled inside the Python package.

```
                   Browser
                     |
          +---------+---------+
          |  SvelteKit SPA    |   (bundled in studio/static/)
          |  @xyflow/svelte   |
          |  Svelte 5 runes   |
          +---------+---------+
                     |
           REST + WebSocket
                     |
          +---------+---------+
          |  FastAPI Backend   |
          |                    |
          |  /api/settings     |   Provider credentials & model defaults
          |  /api/projects     |   Project CRUD
          |  /api/registry     |   Agent/tool/pattern discovery
          |  /api/codegen      |   Python code generation
          |  /api/monitoring   |   Usage metrics
          |  /api/checkpoints  |   Checkpoint management
          |  /api/evaluate     |   Evaluation lab
          |  /api/experiments  |   A/B experiments
          |  /api/files        |   Project file browsing
          |  /ws/execution     |   Pipeline execution (WebSocket)
          |  /ws/assistant     |   AI assistant chat (WebSocket)
          +---------+---------+
                     |
          +---------+---------+
          |  Framework Core    |
          |  Agents, Tools,    |
          |  Pipelines, etc.   |
          +--------------------+
```

### Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Frontend framework | SvelteKit 5 | Runes reactivity, small bundles, excellent DX |
| Canvas library | @xyflow/svelte | Mature node graph library with drag/drop, zoom |
| Backend | FastAPI | Async, WebSocket support, Pydantic integration |
| Delivery | Bundled SPA | Single `pip install`, no Node.js in production |
| Real-time | WebSocket | Bidirectional execution events and AI chat |

---

## The Canvas

The canvas is the central workspace. Nodes represent pipeline components
and edges represent data flow between them.

### Interactions

- **Add nodes** -- Drag from the left palette, or press `Cmd+K` and type
- **Connect** -- Drag from a source handle to a target handle
- **Select** -- Click a node to open its configuration in the right panel
- **Delete** -- Select a node and press `Delete` or `Backspace`
- **Pan** -- Click and drag on empty canvas space
- **Zoom** -- Scroll wheel or pinch gesture
- **Minimap** -- Bottom-right corner for overview navigation

### Empty State

When the canvas has no nodes, an overlay displays a call-to-action
prompting you to drag components or use the command palette.

### Execution Visualization

During pipeline execution, nodes show real-time state:

| State | Visual |
|---|---|
| Idle | Default appearance |
| Running | Rotating conic-gradient border |
| Complete | Green checkmark badge |
| Error | Red error indicator |

---

## Node Types

Studio supports ten node types that map to framework components:

| Node Type | Framework Class | Description |
|---|---|---|
| **Agent** | `FireflyAgent` / `AgentStep` | An LLM-powered agent with model, instructions, and tools |
| **Tool** | `BaseTool` / `CallableStep` | A tool that an agent can invoke |
| **Reasoning** | `ReasoningPattern` / `ReasoningStep` | A reasoning pattern (ReAct, CoT, etc.) |
| **Pipeline Step** | `CallableStep` | A generic pass-through step |
| **Fan Out** | `FanOutStep` | Split input into parallel branches |
| **Fan In** | `FanInStep` | Merge parallel branches back together |
| **Condition** | `BranchStep` | A branching condition in the pipeline |
| **Memory** | `CallableStep` | Store, retrieve, or clear values in context memory |
| **Validator** | `CallableStep` | Validate input against rules (not_empty, is_string, etc.) |
| **Custom Code** | `CallableStep` | Execute user-authored async Python code |
| **Input** | `CallableStep` | Pipeline entry point (triggers: manual, HTTP, queue, schedule, file_upload) |
| **Output** | `CallableStep` | Pipeline exit point (destinations: response, queue, webhook, store, multi) |

### Node Configuration

Click a node to open the configuration panel on the right. Available fields
depend on the node type:

- **Label** -- Display name
- **Model** -- LLM model string (e.g., `openai:gpt-4o`)
- **Instructions** -- System prompt / instructions
- **Additional fields** -- Type-specific configuration

---

## Code Generation

The **Code** tab in the bottom panel shows Python code generated from
the current canvas graph. Code updates automatically when nodes or edges
change (debounced by 800ms).

### Features

- **Auto-sync** -- Toggle on/off with the Auto button
- **Manual regenerate** -- Click the refresh button
- **Copy to clipboard** -- Click the copy button
- **Syntax highlighting** -- Python-aware syntax coloring (One Dark theme)
- **Line numbers** -- Numbered lines for easy reference

### Generated Code Structure

```python
from fireflyframework_genai.agents import FireflyAgent

# Agent definitions
agent_1 = FireflyAgent(
    name="agent-1",
    model="openai:gpt-4o",
    instructions="...",
)

# Pipeline (when edges exist)
from fireflyframework_genai.pipeline.builder import PipelineBuilder

pipeline = (
    PipelineBuilder("studio-pipeline")
    .add_node("agent-1", AgentStep(agent_1))
    .add_node("agent-2", AgentStep(agent_2))
    .chain("agent-1", "agent-2")
    .build()
)
```

---

## AI Assistant

The **Chat** tab in the bottom panel provides an AI-powered assistant that
can help you build pipelines through natural language conversation.

### Capabilities

The assistant can:
- Add, remove, and configure nodes on the canvas
- Connect nodes with edges
- List current nodes and edges
- Explain pipeline concepts
- Suggest pipeline architectures

### Requirements

The AI assistant requires a configured LLM provider. You can configure
credentials through the **Settings modal** (`Cmd/Ctrl + ,`) or via
environment variables:

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
```

The assistant uses the framework's default model (`FIREFLY_GENAI_DEFAULT_MODEL`).

### Canvas Tools

The assistant has access to six canvas manipulation tools:

| Tool | Description |
|---|---|
| `add_node` | Add a node (agent, tool, reasoning, condition) |
| `connect_nodes` | Create an edge between two nodes |
| `configure_node` | Update a node's model, instructions, or label |
| `remove_node` | Remove a node from the canvas |
| `list_nodes` | List all current nodes |
| `list_edges` | List all current edges |

---

## Project Management

Studio persists projects as directories on disk under the configured
`projects_dir` (default: `~/.firefly-studio/projects/`).

### Project Structure

```
~/.firefly-studio/projects/
  my-project/
    project.json          # name, description, created_at
    pipelines/
      main-pipeline.json  # saved graph (nodes + edges)
      backup.json
  another-project/
    project.json
    pipelines/
```

### Operations

| Action | API | Description |
|---|---|---|
| List | `GET /api/projects` | List all projects |
| Create | `POST /api/projects` | Create a new project |
| Delete | `DELETE /api/projects/{name}` | Delete a project |
| Save pipeline | `POST /api/projects/{project}/pipelines/{name}` | Save graph |
| Load pipeline | `GET /api/projects/{project}/pipelines/{name}` | Load graph |

---

## Pipeline Execution

The execution system uses a WebSocket connection at `/ws/execution` for
real-time pipeline execution with event streaming.

### Event Types

| Event | Fields | Description |
|---|---|---|
| `node_start` | `node_id`, `pipeline_name` | Node began executing |
| `node_complete` | `node_id`, `pipeline_name`, `latency_ms` | Node finished |
| `node_error` | `node_id`, `pipeline_name`, `error` | Node failed |
| `node_skip` | `node_id`, `pipeline_name`, `reason` | Node skipped |
| `pipeline_complete` | `pipeline_name`, `success`, `duration_ms` | Pipeline finished |

### How Execution Works

1. The frontend sends the current canvas graph (nodes + edges + metadata) via WebSocket.
2. The backend compiles the graph into a `PipelineEngine` using the graph-to-engine compiler.
3. The engine runs asynchronously, and the `StudioEventHandler` collects events.
4. Events are streamed back to the frontend in real time for node state visualization.
5. On completion, a `pipeline_result` message includes success status, output, and duration.

In **debug mode**, checkpoints are automatically created at each node completion for
time-travel debugging via the Timeline tab.

---

## Checkpoints & Time-Travel Debugging

The checkpoint system captures pipeline state at each node for debugging
and replay.

### Checkpoint API

| Endpoint | Description |
|---|---|
| `GET /api/checkpoints` | List all checkpoints |
| `GET /api/checkpoints/{index}` | Get a specific checkpoint |
| `POST /api/checkpoints/fork` | Fork execution from a checkpoint |
| `POST /api/checkpoints/diff` | Diff two checkpoints |
| `DELETE /api/checkpoints` | Clear all checkpoints |

### Checkpoint Data

Each checkpoint captures:
- `index` -- Sequential checkpoint number
- `node_id` -- Node that created it
- `state` -- Captured pipeline state
- `inputs` -- Node inputs at that point
- `timestamp` -- ISO 8601 timestamp
- `branch_id` -- Branch identifier (for forked executions)
- `parent_index` -- Parent checkpoint (for forks)

---

## Evaluation Lab

The Evaluation Lab lets you test your pipeline against JSONL datasets
to measure quality.

### Workflow

1. **Upload a dataset** -- JSONL file where each line has `"input"` and
   optionally `"expected_output"` fields
2. **Select a dataset** from the project's dataset list
3. **Run evaluation** -- Compiles the current canvas graph and runs each
   test case through the pipeline
4. **View results** -- Pass/fail rate, individual test results with
   input/expected/actual comparisons

### API

| Endpoint | Description |
|---|---|
| `POST /api/projects/{name}/datasets/upload` | Upload a JSONL dataset |
| `GET /api/projects/{name}/datasets` | List datasets for a project |
| `POST /api/evaluate/run` | Run a pipeline against a dataset |

---

## Experiments

Experiments let you define A/B comparisons between pipeline variants.

### Features

- **Create experiments** with named variants and traffic allocation
- **Run variants manually** against the current canvas pipeline
- **View results** per variant

Advanced features (automatic traffic splitting, statistical significance)
are planned for a future release.

### API

| Endpoint | Description |
|---|---|
| `GET /api/projects/{name}/experiments` | List experiments |
| `POST /api/projects/{name}/experiments` | Create an experiment |
| `GET /api/projects/{name}/experiments/{id}` | Get experiment details |
| `DELETE /api/projects/{name}/experiments/{id}` | Delete an experiment |
| `POST /api/projects/{name}/experiments/{id}/run` | Run a variant |

---

## File Browser

The Files page provides a read-only file explorer for project directories.

- Recursive file listing with directory tree
- File content preview for text files
- Security: path traversal protection, binary file rejection, 2 MiB size limit

### API

| Endpoint | Description |
|---|---|
| `GET /api/projects/{name}/files` | Recursive file listing |
| `GET /api/projects/{name}/files/{path}` | Read file content |

---

## Deploy

The Deploy page helps you export your pipeline:

- **Python Script** -- Generate a standalone Python script from the current
  canvas graph using the codegen API
- **Docker Container** -- Coming soon
- **REST API** -- Coming soon
- **Cloud Function** -- Coming soon

---

## Keyboard Shortcuts

### General

| Shortcut | Action |
|---|---|
| `Cmd/Ctrl + K` | Open command palette |
| `Cmd/Ctrl + ,` | Open settings |
| `?` | Toggle keyboard shortcuts help |
| `Cmd/Ctrl + /` | Toggle AI assistant panel |

### Pipeline

| Shortcut | Action |
|---|---|
| `Cmd/Ctrl + Enter` | Run pipeline |
| `Cmd/Ctrl + Shift + D` | Debug pipeline |

### Canvas

| Shortcut | Action |
|---|---|
| `Delete` / `Backspace` | Delete selected node |
| `Cmd/Ctrl + D` | Duplicate selected node |
| `Cmd/Ctrl + +` | Zoom in |
| `Cmd/Ctrl + -` | Zoom out |

### Command Palette

The command palette (`Cmd+K`) provides fuzzy search across commands
in five categories: Navigation, Add Node, Settings, Pipeline Actions,
and View.

---

## Input/Output Boundary Nodes

Input and Output nodes define pipeline entry and exit points, inspired by
BPM start/end events. They enable auto-generated REST APIs, queue
consumers, scheduled triggers, and structured schema validation.

- **Input node** -- Configure a trigger type (`manual`, `http`, `queue`,
  `schedule`, `file_upload`) and an optional JSON Schema for input
  validation.
- **Output node** -- Configure a destination type (`response`, `queue`,
  `webhook`, `store`, `multi`) and an optional response schema.

A pipeline must have exactly one Input node and at least one Output node
when boundary nodes are used.

See the [Input/Output Nodes Guide](input-output-nodes.md) for full
configuration reference.

---

## Project Runtime

The **runtime** manages background processes for a project: queue
consumers (Kafka, RabbitMQ, Redis), cron schedulers (APScheduler), and
the tunnel. Control it from the top bar:

- **Play** button -- Start the runtime
  (`POST /api/projects/{name}/runtime/start`)
- **Stop** button -- Stop the runtime
  (`POST /api/projects/{name}/runtime/stop`)
- Status indicator shows `running` / `stopped`

When started, the runtime reads the Input node configuration and
automatically starts the appropriate consumers or scheduler.

---

## Per-Project API

Every project exposes auto-generated REST endpoints:

| Endpoint | Description |
|---|---|
| `POST /api/projects/{name}/run` | Synchronous pipeline execution |
| `POST /api/projects/{name}/run/async` | Async execution |
| `GET /api/projects/{name}/runs/{id}` | Poll async result |
| `POST /api/projects/{name}/upload` | File upload trigger |
| `GET /api/projects/{name}/schema` | Input/output schema |

A GraphQL endpoint is also available at `/api/graphql` (requires
`strawberry-graphql`).

See the [Project API Guide](project-api.md) for curl examples and client
code in Python and TypeScript.

---

## Tunnel Exposure (Share)

The **Share** button in the top bar creates a Cloudflare Quick Tunnel,
giving your local Studio a public HTTPS URL without configuration or
a Cloudflare account.

- Click **Share** to start the tunnel
- The public URL appears and is copied to your clipboard
- Click again to stop the tunnel

Requires `cloudflared` to be installed. Also available via CLI:

```bash
firefly expose --port 8470
```

See the [Tunnel Exposure Guide](tunnel-exposure.md) for installation and
security details.

---

## REST API Reference

All REST endpoints are prefixed with `/api/`.

### Health

```
GET /api/health
```

Returns `{"status": "ok", "version": "26.02.07"}`.

### Settings

```
GET  /api/settings           # Current settings (keys masked)
POST /api/settings           # Save / merge settings
GET  /api/settings/status    # First-start and setup status check
```

#### Save Settings Request

```json
{
  "credentials": {"openai_api_key": "sk-...", "anthropic_api_key": null},
  "model_defaults": {"default_model": "openai:gpt-4o", "temperature": 0.7, "retries": 3},
  "setup_complete": true
}
```

Fields set to `null` are preserved from existing settings. Non-null
values overwrite.

#### Settings Status Response

```json
{"first_start": false, "setup_complete": true}
```

### Registry

```
GET /api/registry/agents     # List registered agents
GET /api/registry/tools      # List registered tools
GET /api/registry/patterns   # List registered reasoning patterns
```

### Projects

```
GET    /api/projects                                    # List all
POST   /api/projects                                    # Create
DELETE /api/projects/{name}                             # Delete
POST   /api/projects/{project}/pipelines/{pipeline}     # Save pipeline
GET    /api/projects/{project}/pipelines/{pipeline}     # Load pipeline
```

#### Create Project Request

```json
{"name": "my-project", "description": "Optional description"}
```

#### Save Pipeline Request

```json
{"graph": {"nodes": [...], "edges": [...]}}
```

### Code Generation

```
POST /api/codegen/to-code
```

#### Request Body

```json
{
  "nodes": [
    {"id": "agent-1", "type": "agent", "label": "Classifier", "data": {"model": "openai:gpt-4o"}}
  ],
  "edges": [
    {"id": "e1", "source": "agent-1", "target": "agent-2"}
  ]
}
```

#### Response

```json
{"code": "from fireflyframework_genai.agents import FireflyAgent\n..."}
```

### Files

```
GET /api/projects/{name}/files             # List all files
GET /api/projects/{name}/files/{path}      # Read file content
```

### Evaluation

```
POST /api/projects/{name}/datasets/upload  # Upload JSONL dataset
GET  /api/projects/{name}/datasets         # List datasets
POST /api/evaluate/run                     # Run pipeline against dataset
```

#### Run Evaluation Request

```json
{"project": "my-project", "dataset": "tests.jsonl", "graph": {"nodes": [...], "edges": [...]}}
```

### Experiments

```
GET    /api/projects/{name}/experiments              # List experiments
POST   /api/projects/{name}/experiments              # Create experiment
GET    /api/projects/{name}/experiments/{id}          # Get experiment
DELETE /api/projects/{name}/experiments/{id}          # Delete experiment
POST   /api/projects/{name}/experiments/{id}/run      # Run variant
```

### Monitoring

```
GET /api/monitoring/usage    # Token usage, costs, latency summary
```

### Checkpoints

```
GET    /api/checkpoints              # List all
GET    /api/checkpoints/{index}      # Get by index
POST   /api/checkpoints/fork         # Fork from checkpoint
POST   /api/checkpoints/diff         # Diff two checkpoints
DELETE /api/checkpoints              # Clear all
```

---

## WebSocket API Reference

### Execution WebSocket

```
WS /ws/execution
```

#### Send

```json
{"action": "run", "graph": {"nodes": [...], "edges": [...], "metadata": {...}}, "inputs": "optional user input"}
{"action": "debug", "graph": {"nodes": [...], "edges": [...]}, "inputs": "optional"}
```

#### Receive

```json
{"type": "node_start", "node_id": "agent-1", "pipeline_name": "my-pipeline"}
{"type": "node_complete", "node_id": "agent-1", "pipeline_name": "my-pipeline", "latency_ms": 1234.5}
{"type": "node_error", "node_id": "agent-1", "pipeline_name": "my-pipeline", "error": "..."}
{"type": "pipeline_complete", "pipeline_name": "my-pipeline", "success": true, "duration_ms": 5678.9}
{"type": "pipeline_result", "success": true, "output": "...", "duration_ms": 5678.9, "pipeline_name": "my-pipeline"}
```

### Assistant WebSocket

```
WS /ws/assistant
```

#### Send

```json
{"action": "chat", "message": "Add an agent node for classification"}
{"action": "clear_history"}
```

#### Receive (streaming)

```json
{"type": "token", "content": "I'll"}
{"type": "token", "content": " add"}
{"type": "tool_call", "tool": "add_node", "args": {"type": "agent", "label": "Classifier"}}
{"type": "tool_result", "tool": "add_node", "result": "Added node agent-1"}
{"type": "done"}
```

---

## Desktop App

Firefly Studio can be packaged as a standalone desktop application using
Tauri 2 + PyInstaller. The desktop app bundles the Python server as a
sidecar binary.

### Architecture

```
  Tauri (Rust + WebView)
         |
    spawn sidecar
         |
  PyInstaller bundle
  (FastAPI + Studio)
         |
    http://127.0.0.1:<port>
```

1. Tauri finds a free port, spawns the PyInstaller sidecar
2. Polls `/api/health` until the server is ready (30s timeout)
3. Navigates the webview to `http://127.0.0.1:<port>`
4. On window close, kills the sidecar process

### Building

```bash
# Build the PyInstaller sidecar
uv run pyinstaller studio-desktop/pyinstaller/firefly_studio.spec --noconfirm

# Build the Tauri desktop app (requires Rust toolchain)
cd studio-desktop && cargo tauri build
```

### CI/CD

The desktop build is automated via `.github/workflows/desktop.yml`:
- Triggered by `desktop-v*` tags
- Builds for macOS (arm64 + x86), Linux, and Windows
- Produces `.dmg`, `.AppImage`, `.deb`, `.msi`, `.exe` installers

---

## Programmatic Usage

### Launch Studio from Python

```python
from fireflyframework_genai.studio import launch_studio

# Starts the server and opens the browser
launch_studio()
```

### Embed the Studio App

```python
from fireflyframework_genai.studio.config import StudioConfig
from fireflyframework_genai.studio.server import create_studio_app

# Create a configured app instance
config = StudioConfig(port=9000, open_browser=False)
app = create_studio_app(config=config)

# Use with any ASGI server
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=9000)
```

### Use Studio with Custom Projects Directory

```python
from fireflyframework_genai.studio.config import StudioConfig
from fireflyframework_genai.studio.server import create_studio_app

config = StudioConfig(projects_dir="/data/my-studio-projects")
app = create_studio_app(config=config)
```

### Use the ProjectManager Directly

```python
from pathlib import Path
from fireflyframework_genai.studio.projects import ProjectManager

manager = ProjectManager(Path("/data/projects"))

# Create a project
info = manager.create("my-project", description="A new project")

# Save a pipeline
graph = {"nodes": [...], "edges": [...]}
manager.save_pipeline("my-project", "main", graph)

# Load it back
loaded = manager.load_pipeline("my-project", "main")
```

---

## Frontend Development

The frontend source lives in `studio-frontend/` and is a SvelteKit 5 SPA.

### Prerequisites

- Node.js 20+
- npm or pnpm

### Setup

```bash
cd studio-frontend
npm install
```

### Development Server

```bash
npm run dev
```

This starts the Vite dev server at `http://localhost:5173` with hot module
replacement. The backend CORS middleware allows this origin.

### Build for Production

```bash
npm run build
```

Output goes to `studio-frontend/build/`. Copy to the Python package:

```bash
cp -r studio-frontend/build/* src/fireflyframework_genai/studio/static/
```

### Tech Stack

| Technology | Version | Purpose |
|---|---|---|
| SvelteKit | 2.x | Application framework |
| Svelte | 5.x | UI components (runes syntax) |
| @xyflow/svelte | 1.x | Node graph canvas |
| Tailwind CSS | 4.x | Utility-first styling |
| Lucide Svelte | Latest | Icon library |
| Vite | 7.x | Build tool |

### Project Structure

```
studio-frontend/
  src/
    routes/
      +page.svelte           # Redirect to /build
      +layout.svelte          # App shell wrapper
      build/+page.svelte      # Visual canvas (main workspace)
      evaluate/+page.svelte   # Evaluation page
      experiments/+page.svelte
      deploy/+page.svelte
      monitor/+page.svelte
      files/+page.svelte
    lib/
      components/
        layout/               # AppShell, Sidebar, TopBar, CommandPalette,
                              # SettingsModal, FirstStartWizard
        canvas/               # Canvas, NodePalette, node components
        panels/               # BottomPanel, ConfigPanel, ChatTab, CodeTab
      stores/                 # Svelte stores (pipeline, execution, ui, chat, settings)
      api/                    # REST client, WebSocket client
      execution/              # Execution bridge
      types/                  # TypeScript type definitions
    app.css                   # Global styles and CSS custom properties
```

### Design Language

Studio uses a dark, premium developer-tool aesthetic:

- **Background:** `#0f0f17` (deep blue-black)
- **Surface:** `#16161e` (card backgrounds)
- **Accent:** `#ff6b35` (warm orange)
- **Font:** JetBrains Mono (monospace), Inter (UI)
- **Icons:** Lucide (no emojis)
- **Borders:** `1px solid #2a2a3a`
- **Reduced motion:** Respects `prefers-reduced-motion`

---

*Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.*
