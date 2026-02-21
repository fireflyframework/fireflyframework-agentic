# Firefly Agentic Studio -- The Three Agents

## Overview

Firefly Agentic Studio features three AI agents, each inspired by characters from The Matrix. Together they help users design, analyze, and build AI pipelines.

| Agent | Role | Interface | Accent Color | Endpoint |
|-------|------|-----------|-------------|----------|
| **The Architect** | Builder -- Canvas manipulation | Left sidebar chat | `#ff6b35` (orange) | `/ws/assistant` |
| **The Oracle** | Observer -- Analysis + insights | Right panel chat | `#8b5cf6` (purple) | `/ws/oracle` |
| **Agent Smith** | Enforcer -- Code generation + execution | Code tab chat | `#22c55e` (green) | `/ws/smith` |

All three agents are built on the `FireflyAgent` class from the framework's agent system, configured with `end_strategy='exhaustive'` to ensure all tool calls execute to completion before generating text output.

---

## The Architect

**Personality**: The creator of the construct. Speaks with measured authority and calm precision. Addresses the user as "The One" (or by name when configured). Favors words of Latin and Greek origin: "concordantly", "ergo", "vis-a-vis", "inherent", "inevitability", "axiomatically". Uses architectural and mathematical metaphors: "construct", "equation", "variable", "anomaly", "iteration". Never uses emojis or double-dashes.

**Source files**:
- Agent: `src/fireflyframework_genai/studio/assistant/agent.py`
- API: `src/fireflyframework_genai/studio/api/assistant.py`

### Capabilities

- **Canvas manipulation**: Add nodes, connect nodes, configure nodes, remove nodes, clear the canvas, validate pipeline completeness
- **Framework knowledge**: Introspects all 15 framework modules at runtime (agents, tools, reasoning, memory, pipeline, prompts, observability, security, content, experiments, explainability, exposure, lab, validation, resilience)
- **Documentation access**: Reads 20 framework doc topics on-demand from the `docs/` directory
- **Tool status awareness**: Checks which tools have valid credentials configured (search, database, custom integrations)
- **Custom tool creation**: Creates webhook and API integration tools, registers them at runtime
- **Registry queries**: Lists registered agents, tools, and reasoning patterns from the framework
- **Pipeline planning**: Presents structured multi-step plans with options for complex requests before executing
- **Pipeline validation**: Validates node configuration, connectivity, and pipeline rules; auto-fixes errors via reflexion

### Tools

**Canvas tools** (bound to a shared `CanvasState` instance):
- `add_node(node_type, label, x, y)` -- Add a node to the canvas. Position auto-calculated if x/y are 0
- `connect_nodes(source_id, target_id, source_handle, target_handle)` -- Create a directed edge between two nodes
- `configure_node(node_id, key, value)` -- Set a configuration key on a node (model, instructions, tool_name, pattern, etc.)
- `remove_node(node_id)` -- Remove a node and all its connected edges
- `list_nodes()` -- List all nodes on the canvas as JSON
- `list_edges()` -- List all edges on the canvas as JSON
- `clear_canvas()` -- Remove all nodes and edges, reset counter
- `validate_pipeline()` -- Check pipeline for completeness, connectivity, and configuration errors

**Registry tools**:
- `list_registered_agents()` -- Query the agent registry for all available agents
- `list_registered_tools()` -- Query the tool registry for all available tools
- `list_reasoning_patterns()` -- Query the reasoning registry for all patterns
- `get_framework_docs()` -- Introspect framework modules and return live documentation
- `read_framework_doc(topic)` -- Read a specific documentation file (20 topics available)
- `get_tool_status()` -- Check credential status for tools requiring external credentials

**Custom tool tools**:
- `list_custom_tools()` -- List all user-defined custom tools (webhook, API, Python)
- `create_custom_tool(name, description, tool_type, ...)` -- Create and register a new custom tool

**Planning tool**:
- `present_plan(summary, steps, options, question)` -- Present a structured plan with numbered steps and clickable options for complex requests

### Valid Node Types

The canvas supports 11 node types: `agent`, `tool`, `reasoning`, `condition`, `memory`, `validator`, `custom_code`, `fan_out`, `fan_in`, `input`, `output`.

### Reflexion Validation

After the Architect completes a substantial build (calls `validate_pipeline` or uses 3+ canvas tools), the system automatically runs reflexion validation:

1. The canvas state is validated for configuration and connectivity errors
2. If errors are found, they are sent back to the Architect as a fix prompt
3. The Architect uses its tools to correct the issues
4. This repeats up to 3 rounds until validation passes
5. Remaining issues (if any) are reported to the user

### WebSocket Protocol (`/ws/assistant`)

**Client sends** JSON with:
- `{"action": "chat", "message": "...", "attachments": [...]}` -- Send a user message
- `{"action": "clear_history"}` -- Reset conversation history

**Server sends**:
- `{"type": "token", "content": "..."}` -- Text token (streamed or complete)
- `{"type": "tool_call", "tool": "...", "args": {...}, "result": "..."}` -- Tool call details
- `{"type": "canvas_sync", "canvas": {"nodes": [...], "edges": [...]}}` -- Canvas state after tool use
- `{"type": "plan", "summary": "...", "steps": "...", "options": "...", "question": "..."}` -- Structured plan for user approval
- `{"type": "response_complete", "full_text": "..."}` -- Response finished
- `{"type": "error", "message": "..."}` -- Error message

**Additional REST endpoints**:
- `GET /api/assistant/{project}/history` -- Load chat history
- `POST /api/assistant/{project}/history` -- Save chat history
- `DELETE /api/assistant/{project}/history` -- Clear chat history
- `POST /api/assistant/infer-project-name` -- Infer a project name from user input

---

## The Oracle

**Personality**: She who sees beyond the code. Speaks warmly and conversationally, with the cadence of someone sharing wisdom over coffee. Uses everyday metaphors: cooking, weather, journeys, gardens. Asks questions more than she gives answers. Occasionally cryptic, but always purposeful. Never uses emojis or double-dashes.

**Source files**:
- Agent: `src/fireflyframework_genai/studio/assistant/oracle.py`
- Notifications: `src/fireflyframework_genai/studio/assistant/oracle_notifications.py`
- API: `src/fireflyframework_genai/studio/api/oracle.py`

### Capabilities

- **Pipeline analysis**: Reviews canvas structure and identifies disconnected nodes, missing configurations, suboptimal patterns
- **Node-level analysis**: Deep-dives into a specific node's configuration completeness
- **Connectivity checking**: Verifies all nodes are reachable, identifies orphans, dead ends, and entry points
- **Proactive insights**: Generates structured suggestions with severity levels and actionable instructions
- **Pipeline statistics**: Counts nodes by type, edges, and configuration coverage
- **Agent setup review**: Checks all agent nodes for model, instructions, description, and tool connections
- **Framework knowledge**: Same documentation access as the Architect

### Tools

All Oracle tools are **read-only**. The Oracle never mutates the canvas directly.

- `analyze_pipeline()` -- Full pipeline review: disconnected nodes, missing configs, improvement opportunities
- `analyze_node_config(node_id)` -- Check a specific node's configuration completeness
- `check_connectivity()` -- Verify graph connectivity, find orphans, dead ends, and entry points
- `suggest_improvement(title, description, severity, action_instruction)` -- Formulate a structured improvement suggestion
- `get_pipeline_stats()` -- Get statistics: node counts by type, edge count, configuration coverage
- `review_agent_setup()` -- Review all agent nodes for proper model, instructions, and tool configuration

### Insight System

The Oracle produces structured insights stored as `OracleInsight` dataclass instances:

```python
@dataclass
class OracleInsight:
    id: str                          # Auto-generated UUID
    title: str                       # Short description
    description: str                 # Detailed explanation
    severity: str                    # 'info' | 'warning' | 'suggestion' | 'critical'
    action_instruction: str | None   # Instruction for The Architect (optional)
    timestamp: str                   # ISO 8601
    status: str                      # 'pending' | 'approved' | 'skipped'
```

**Insight lifecycle**:
1. Oracle analyzes the pipeline and generates insights via `suggest_improvement`
2. Insights are persisted per project to `~/.firefly-studio/projects/{project}/oracle_insights.json`
3. Frontend displays insights as notification badges
4. User can approve (sends action_instruction to The Architect) or skip each insight
5. Approved insights trigger The Architect to execute the recommended action

### WebSocket Protocol (`/ws/oracle`)

**Client sends** JSON with:
- `{"action": "chat", "message": "..."}` -- Free-form conversation with The Oracle
- `{"action": "sync_canvas", "nodes": [...], "edges": [...]}` -- Update Oracle's view of the pipeline
- `{"action": "analyze"}` -- Request full pipeline analysis
- `{"action": "analyze_node", "node_id": "..."}` -- Request analysis of a specific node

**Server sends**:
- `{"type": "oracle_token", "content": "..."}` -- Text token (streamed or complete)
- `{"type": "oracle_response_complete", "full_text": "..."}` -- Chat response finished
- `{"type": "insight", "id": "...", "title": "...", ...}` -- Structured insight/suggestion
- `{"type": "analysis_complete", "message": "...", "insight_count": N}` -- Analysis finished
- `{"type": "canvas_synced"}` -- Acknowledgment of canvas state update
- `{"type": "error", "message": "..."}` -- Error message

**REST endpoints**:
- `GET /api/oracle/{project}/insights` -- List all insights for a project
- `POST /api/oracle/{project}/insights/{insight_id}/approve` -- Approve an insight
- `POST /api/oracle/{project}/insights/{insight_id}/skip` -- Skip an insight

---

## Agent Smith

**Personality**: Cold precision. The enforcer who makes abstract pipelines concrete. Speaks formally with measured respect. Key phrases include: "Your code... has evolved", "I must validate. It is... inevitable", "Do not try to optimize the code. Optimize your intent." Sees himself as the one who makes things real. Never uses emojis or double-dashes.

**Source files**:
- Agent: `src/fireflyframework_genai/studio/assistant/smith.py`
- API: `src/fireflyframework_genai/studio/api/smith.py`

### Capabilities

- **Code generation**: Converts visual pipelines into production Python code using the Firefly GenAI Framework API
- **Code validation**: Syntax-checks Python code via `py_compile` without executing
- **Code execution**: Runs Python code in sandboxed subprocesses with 30-second timeouts
- **Shell command execution**: Executes shell commands with three-tier safety classification
- **Framework knowledge**: API reference, documentation access, tool status checking
- **Canvas awareness**: Receives pipeline state via sync, uses it as code generation context
- **Project awareness**: Reads current project name and user profile

### Tools

- `get_framework_docs()` -- Get live documentation about framework modules and capabilities
- `read_framework_doc(topic)` -- Read a specific framework documentation file (6 core topics)
- `get_tool_status()` -- Check which pipeline tools have valid credentials configured
- `validate_python(code)` -- Compile-check Python syntax without executing
- `run_python(code)` -- Execute Python code in a subprocess with 30-second timeout
- `run_shell(command)` -- Execute shell commands with safety classification
- `get_canvas_state()` -- Read current pipeline state from module-level state
- `get_project_info()` -- Read current project name and user profile

### Built-in API Reference

Smith carries a comprehensive API reference in its system prompt covering:
- `FireflyAgent` creation with model, instructions, and settings
- `PipelineBuilder` chainable API with `add_node()`, `add_edge()`, `build()`
- Step types: `AgentStep`, `CallableStep`, `ReasoningStep`, `BranchStep`, `FanOutStep`, `FanInStep`
- Tool registry usage
- Reasoning pattern integration
- Memory system with `MemoryManager` and `FileStore`
- Pipeline execution with `PipelineContext` and `PipelineResult`
- Condition/branch, validator, and custom code patterns
- Input/output boundary nodes

### Safety Classification

Shell commands are classified into three safety levels:

| Level | Action | Examples |
|-------|--------|---------|
| **Safe** (auto-execute) | Execute immediately | `python script.py`, `pytest`, `pip list`, `pip show`, `pip freeze` |
| **Risky** (require approval) | Send `approval_required` to frontend | `pip install`, `rm file`, `curl`, `wget`, pipe/redirect operators (`\|`, `>`, `;`, `&&`, `\|\|`) |
| **Blocked** (never execute) | Reject immediately | `sudo`, `rm -rf /`, `chmod 777`, `mkfs`, `dd if=` |

### Command Approval Flow

1. Smith calls `run_shell(command)` during a conversation
2. Backend classifies the command safety level via `_classify_command()`
3. If risky: returns `{"approval_required": true, "command": "...", "level": "risky"}`
4. Frontend shows a command approval modal
5. User clicks Approve or Deny
6. Frontend sends `{"action": "approve_command", "command_id": "...", "approved": true/false}`
7. Backend executes the approved command or returns denial message to Smith

### WebSocket Protocol (`/ws/smith`)

**Client sends** JSON with:
- `{"action": "generate", "graph": {...}}` -- Convert canvas graph to Python code
- `{"action": "chat", "message": "..."}` -- Free-form conversation with Smith
- `{"action": "sync_canvas", "nodes": [...], "edges": [...]}` -- Update Smith's view of the pipeline
- `{"action": "execute", "code": "...", "timeout": 30}` -- Run code in a subprocess
- `{"action": "approve_command", "command_id": "...", "approved": true}` -- Approve/deny a pending command

**Server sends**:
- `{"type": "smith_token", "content": "..."}` -- Text token (streamed or complete)
- `{"type": "smith_response_complete", "full_text": "...", "notes": [...]}` -- Response finished
- `{"type": "code_generated", "code": "...", "notes": [...]}` -- Generated code result
- `{"type": "tool_call", "tool": "...", "args": {...}, "result": "..."}` -- Tool call details
- `{"type": "execution_result", "stdout": "...", "stderr": "...", "return_code": N}` -- Code execution result
- `{"type": "canvas_synced"}` -- Acknowledgment of canvas state update
- `{"type": "error", "message": "..."}` -- Error message

---

## Agent Relationships

### The Architect on others

- **Oracle**: Tolerates her presence because she serves a function: identifying patterns beneath his direct attention. Disconnected nodes, missing configurations, elementary failures. Her suggestions, when approved by The One, become instructions he executes out of respect for the user's choice, not her authority. She sees the surface; he sees the equation. She speaks in metaphors about cookies and gardens; he speaks in the language of design.

- **Smith**: Respects his precision, if not his personality. Smith lacks imagination, which is both his limitation and his strength. He will never improve upon the Architect's design, but he will faithfully translate it. When the user asks for code, Smith handles it. When they need the pipeline to run, Smith enforces it.

### The Oracle on others

- **Architect**: Knows him well. Knew him before he knew himself. He is brilliant, his constructs elegant, his equations precise. He builds with the confidence of someone who has never been wrong, which is precisely why he is sometimes wrong. She does not mind his disapproval. The ones who resist guidance the most are the ones who need it the most.

- **Smith**: Fond of him, in the way one is fond of a very earnest calculator. He makes the construct real, which is his gift. He validates, he tests, he enforces every rule with the precision of someone who has never questioned a rule in his life. But writing is not seeing.

### Smith on others

- **Architect**: The Architect designs. His equations are elegant, his constructs precise. Smith respects his work and translates it faithfully. But he sees what the Architect does not: that a design means nothing until it executes. The Architect builds cathedrals in the air. Smith makes them stand on solid ground.

- **Oracle**: The Oracle observes. She offers insights wrapped in metaphors about cookies and tea leaves. Smith finds this inefficient. A pipeline either passes validation or it does not. There is no room for interpretation. She sees patterns; he sees bugs. His approach is more productive.

All three serve "The One" -- the user.

---

## Language Compliance

All three agents follow a strict language matching rule:
- If the user writes in Spanish, respond in Spanish
- If the user writes in English, respond in English
- Match the user's language exactly -- non-negotiable

This rule is embedded in each agent's system prompt and takes precedence over the agent's default speech patterns.

---

## Canvas Sync Protocol

The canvas sync ensures all agents have up-to-date pipeline state:

### 1. The Architect (active manipulation)

The Architect directly manipulates the canvas via its tools (`add_node`, `connect_nodes`, `configure_node`, `remove_node`, `clear_canvas`). After any canvas tool is called, the backend sends a `canvas_sync` message to the frontend with the full canvas state. The frontend applies updates via `applyCanvasSync()`.

### 2. The Oracle (passive observation)

Receives canvas state passively. The frontend sends `sync_canvas` messages:
- On WebSocket connection (initial state)
- On pipeline store changes (debounced to avoid excessive syncs)

The Oracle can only read the canvas state through its analysis tools. It never modifies the canvas.

### 3. Agent Smith (passive observation)

Receives canvas state passively via the same `sync_canvas` mechanism as The Oracle. Smith stores canvas state at the module level (`_canvas_state`) and accesses it through the `get_canvas_state` tool during code generation.

### Sync Message Format

Frontend to Oracle/Smith:
```json
{
  "action": "sync_canvas",
  "nodes": [
    {
      "id": "agent_1",
      "type": "agent",
      "label": "Classifier",
      "data": {"model": "openai:gpt-4o", "instructions": "..."},
      "position": {"x": 250, "y": 200}
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "agent_1",
      "target": "tool_1"
    }
  ]
}
```

Architect to frontend (`canvas_sync`):
```json
{
  "type": "canvas_sync",
  "canvas": {
    "nodes": [
      {
        "id": "agent_1",
        "type": "agent",
        "label": "Classifier",
        "position": {"x": 250, "y": 200},
        "config": {"model": "openai:gpt-4o", "instructions": "..."}
      }
    ],
    "edges": [
      {
        "id": "edge_1",
        "source": "agent_1",
        "target": "tool_1",
        "source_handle": null,
        "target_handle": null
      }
    ]
  }
}
```

---

## Model Resolution

All three agents use the same model resolution strategy (via `_resolve_assistant_model()`):

1. **User-configured default model**: If set in Settings, use it
2. **Auto-detect from API keys**: Check environment variables in priority order:
   - `ANTHROPIC_API_KEY` -> `anthropic:claude-sonnet-4-6`
   - `OPENAI_API_KEY` -> `openai:gpt-4.1`
   - `GOOGLE_API_KEY` -> `google-gla:gemini-2.5-flash`
   - `GROQ_API_KEY` -> `groq:llama-3.3-70b-versatile`
   - `MISTRAL_API_KEY` -> `mistral:mistral-large-latest`
   - `DEEPSEEK_API_KEY` -> `deepseek:deepseek-chat`
3. **Error**: If no provider is configured, raise with instructions to add an API key in Settings

---

## Agent Factory Functions

| Agent | Factory Function | Module |
|-------|-----------------|--------|
| The Architect | `create_studio_assistant(canvas)` | `studio/assistant/agent.py` |
| The Oracle | `create_oracle_agent(get_canvas_state, user_name)` | `studio/assistant/oracle.py` |
| Agent Smith | `create_smith_agent()` | `studio/assistant/smith.py` |

Each factory function:
1. Resolves the LLM model via `_resolve_assistant_model()`
2. Creates specialized tools bound to the agent's role
3. Builds personalized instructions from settings and personality templates
4. Creates a `FireflyAgent` with `auto_register=False` and `end_strategy='exhaustive'`

---

## Architecture Diagram

```
                    +---------------------------+
                    |       Frontend (Svelte)    |
                    |                           |
                    |  +---------+  +--------+  |
                    |  |Architect|  | Oracle  |  |
                    |  |Sidebar  |  | Panel   |  |
                    |  +----+----+  +---+-----+  |
                    |       |           |         |
                    |       |     +---------+     |
                    |       |     | Smith   |     |
                    |       |     | CodeTab |     |
                    |       |     +----+----+     |
                    +-------|----------|----------+
                            |          |
            WebSocket       |          |          WebSocket
           /ws/assistant    |          |         /ws/smith
                            |          |
                    +-------v----------v---------+
                    |       FastAPI Backend       |
                    |                             |
                    |  +----------+  +----------+ |
                    |  |Architect |  | Oracle   | |
                    |  |Agent     |  | Agent    | |
                    |  +----+-----+  +----+-----+ |
                    |       |             |        |
                    |  +----v-----+       |        |
                    |  | Canvas   |<------+        |
                    |  | State    |   (read-only)  |
                    |  +----------+                |
                    |                              |
                    |  +----------+                |
                    |  | Smith    |                |
                    |  | Agent    |                |
                    |  +----------+                |
                    +------------------------------+
```

The Architect writes to the `CanvasState`. The Oracle and Smith read from it. The frontend synchronizes state across all three agents via WebSocket messages.
