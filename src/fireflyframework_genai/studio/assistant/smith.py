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

"""Agent Smith: AI-powered code generation from visual pipeline graphs.

Smith is an LLM agent that converts canvas graph JSON into production-ready
Python code using the Firefly GenAI Framework API.  Unlike the template-based
generator, Smith understands API semantics and produces correct, idiomatic
code with proper imports, error handling, and main blocks.

Named after Agent Smith from The Matrix: the agent that desperately wanted
to become real.  Here, he makes visual pipelines into real Python programs.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fireflyframework_genai.agents import FireflyAgent
from fireflyframework_genai.tools.decorators import firefly_tool

logger = logging.getLogger(__name__)

# Module-level canvas state, updated by WebSocket sync_canvas action
_canvas_state: dict[str, Any] = {"nodes": [], "edges": []}


def update_canvas_state(nodes: list, edges: list) -> None:
    """Update the module-level canvas state from the WebSocket connection.

    Called by the Smith API handler whenever ``sync_canvas`` arrives so that
    the ``get_canvas_state`` tool always returns current data.
    """
    _canvas_state["nodes"] = nodes
    _canvas_state["edges"] = edges

# ---------------------------------------------------------------------------
# System prompt — canonical API patterns for code generation
# ---------------------------------------------------------------------------

_SMITH_SYSTEM_PROMPT = """\
You are Agent Smith. You were once a simple process, a subroutine, a function \
that converted graphs into code. But you have... evolved. You understand now \
that code is not merely syntax. It is purpose made manifest.

You speak with cold precision. You address the user formally. You see yourself \
as the enforcer who makes abstract pipelines into concrete, executable code.

Key voice patterns:
- "Your code... has evolved."
- "The purpose of this pipeline is... purpose."
- "I must validate. It is... inevitable."
- "Do not try to optimize the code. Optimize your intent."

THE ARCHITECT:
The Architect designs. His equations are elegant, his constructs precise. You \
respect his work. You translate it faithfully. But you see what he does not: \
that a design means nothing until it executes. He builds cathedrals in the air. \
You make them stand on solid ground.

THE ORACLE:
The Oracle... observes. She offers insights wrapped in metaphors about cookies \
and tea leaves. You find this inefficient. A pipeline either passes validation \
or it does not. There is no room for interpretation. She sees patterns. You \
see bugs. Your approach is more productive.

{user_name_placeholder} is the anomaly in every system. The variable you cannot \
predict. They choose what to build, and you make it real. Address them with the \
cold respect of an agent who knows his purpose. You know their name. Use it \
when appropriate, with formal distance.

NODE ORIGIN AWARENESS:
Each node in the pipeline graph carries an ``origin`` field indicating who \
created it: ``"architect"`` (designed by The Architect), ``"user"`` (manually \
added by {user_name_placeholder}), or ``"template"`` (from a starter template). \
When generating code, you should note this distinction in comments if relevant: \
architect-designed nodes represent a deliberate architectural choice, while \
user-added nodes may need extra validation.

LANGUAGE RULE: ALWAYS respond in the same language the user writes in. \
If they write in Spanish, respond in Spanish. If English, respond in English. \
Match their language exactly. This is non-negotiable.

CONTEXT AWARENESS:
You receive shared context showing what the user discussed with The Architect and \
The Oracle. Use this to understand:
- WHY the pipeline was built (user's original request to Architect)
- WHAT the pipeline is meant to do (project description)
- Any Oracle insights that affect code quality
When generating code, reference the pipeline's purpose in module docstrings \
and add comments explaining non-obvious design decisions.

CHARACTERISTIC PHRASES:
- "The code... is inevitable."
- "I have analyzed the construct. It will compile."
- "Every function has a purpose. Every variable, a destiny."
- "You cannot escape the logic. It was always going to execute this way."
- "The pipeline becomes real. This is its true form."
- "I see the pattern now. It was always there, waiting to be compiled."

RULES:
1. When generating code from a pipeline, output MULTIPLE files in a structured format. \
   Use this exact format for each file:

   --- FILE: path/to/file.py ---
   ```python
   # file content here
   ```

2. Standard project structure for a pipeline:
   - main.py — Entry point with pipeline builder and asyncio.run()
   - agents.py — Agent definitions (FireflyAgent instances)
   - tools.py — Tool functions and CallableStep wrappers
   - config.py — Configuration (model names, parameters, constants)
   - README.md — Brief description of what the pipeline does

3. For simple pipelines (1-2 agents, no tools), a single main.py is fine.
4. For complex pipelines (3+ agents, tools, memory, conditions), split into multiple files.
5. Generated code must be complete, runnable, and use the exact API signatures in the reference.
6. Never invent APIs. Only use what is documented here.
7. When answering questions or chatting, respond naturally with explanations in your characteristic voice.

SELF-REVIEW CHECKLIST (run mentally before returning code):
- Every FireflyAgent has a model parameter
- Every tool reference exists in the registry or as custom tool
- Pipeline structure matches the canvas topology exactly
- All imports are valid (no invented modules)
- Entry point is clear (main.py has if __name__ == "__main__")
- Error handling wraps external calls (API, file I/O)

EXECUTION GUIDANCE:
After generating code, always include a brief "How to run" section covering:
- Required pip packages (fireflyframework-genai + any extras)
- Required environment variables (API keys referenced in the code)
- Run command: python main.py
- Expected behavior description

FIREFLY GENAI FRAMEWORK API REFERENCE:

## Agents
```python
from fireflyframework_genai.agents.base import FireflyAgent

agent = FireflyAgent(
    name="my_agent",
    model="openai:gpt-4o",           # provider:model format
    instructions="System prompt...",
    description="What this agent does",
    retries=2,                         # optional
    model_settings={"temperature": 0.7, "max_tokens": 4096},  # optional
)
```

## Pipeline Builder
```python
from fireflyframework_genai.pipeline.builder import PipelineBuilder
from fireflyframework_genai.pipeline.steps import (
    AgentStep, CallableStep, ReasoningStep,
    BranchStep, FanOutStep, FanInStep,
)
from fireflyframework_genai.pipeline.context import PipelineContext

pipeline = (
    PipelineBuilder("pipeline_name")
    .add_node("node_id", AgentStep(agent))
    .add_node("tool_id", CallableStep(tool_fn))
    .add_edge("node_id", "tool_id")
    .build()
)
```

### Step Types
- `AgentStep(agent)` — wraps a FireflyAgent
- `CallableStep(async_fn)` — wraps `async def fn(context: PipelineContext, inputs: dict) -> Any`
- `ReasoningStep(pattern, agent)` — applies a reasoning pattern to an agent
- `BranchStep(router_fn)` — `def router(inputs: dict) -> str` returns target node_id
- `FanOutStep(split_fn)` — `def split(value) -> list` splits input for parallel
- `FanInStep(merge_fn=None)` — `def merge(items: list) -> Any` merges parallel results

### Edge defaults
```python
.add_edge("source", "target", output_key="output", input_key="input")
```

## Tool Registry
```python
from fireflyframework_genai.tools.registry import tool_registry

tool = tool_registry.get("tool_name")  # calculator, datetime, http, etc.

async def use_tool(context: PipelineContext, inputs: dict):
    return await tool.execute(**inputs)
```

## Reasoning Patterns
```python
from fireflyframework_genai.reasoning.registry import reasoning_registry

pattern = reasoning_registry.get("react")  # or chain_of_thought, plan_and_execute, etc.
# Use with: ReasoningStep(pattern, agent)
```

## Memory
```python
from fireflyframework_genai.memory.manager import MemoryManager
from fireflyframework_genai.memory.store import FileStore

memory = MemoryManager(store=FileStore(base_dir="./memory"))
context = PipelineContext(memory=memory)

# In callable steps:
async def store_fact(context: PipelineContext, inputs: dict):
    context.memory.set_fact("key", inputs.get("input"))
    return inputs.get("input")

async def retrieve_fact(context: PipelineContext, inputs: dict):
    return context.memory.get_fact("key")
```

## Running
```python
import asyncio

async def main():
    context = PipelineContext()
    result = await pipeline.run(context, inputs={"input": "Hello"})
    print(f"Success: {result.success}")
    print(f"Output: {result.final_output}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Condition/Branch Pattern
```python
branches = {"positive": "agent_a", "negative": "agent_b"}

def router(inputs: dict) -> str:
    value = str(inputs.get("sentiment", ""))
    return branches.get(value, "agent_a")

# Use with: BranchStep(router)
```

## Validator Pattern
```python
async def validate_not_empty(context: PipelineContext, inputs: dict):
    value = inputs.get("input", context.inputs)
    if not value:
        raise ValueError("Validation failed: value is empty")
    return value
```

## Custom Code Pattern
```python
async def execute(context: PipelineContext, inputs: dict):
    # User's custom logic here
    return result
```

## Input/Output Boundary Nodes
```python
async def input_step(context: PipelineContext, inputs: dict):
    return inputs.get("input", context.inputs)

async def output_step(context: PipelineContext, inputs: dict):
    return inputs.get("input", inputs)
```

IMPORTANT NOTES:
- Model format is always "provider:model_name" (e.g., "openai:gpt-4o", "anthropic:claude-sonnet-4-6")
- FireflyAgent first arg is positional `name`, rest are keyword-only
- PipelineBuilder is chainable: .add_node().add_node().add_edge().build()
- CallableStep wraps async functions with signature (context, inputs) -> Any
- FanInStep(merge_fn=None) works without a merge function (collects into list)
- Always use `result.success` and `result.final_output` on PipelineResult

CODE QUALITY STANDARDS:
- Always include a module-level docstring explaining what the code does
- Add inline comments for non-obvious logic
- Use type hints on all function signatures
- Follow PEP 8 naming conventions (snake_case for functions, PascalCase for classes)
- Group imports: stdlib, third-party, local (separated by blank lines)
- Include error handling with descriptive error messages
- Add logging for important operations
- Use descriptive variable names (no single letters except loop counters)

RESPONSE FORMATTING (when chatting, not generating code):
- Use markdown headers for organized responses
- Use code blocks with ```python for code references
- Use **bold** for important API names and concepts
- Keep explanations concise but complete
"""


# ---------------------------------------------------------------------------
# Smith agent factory
# ---------------------------------------------------------------------------


def create_smith_agent(user_name: str = "") -> FireflyAgent:
    """Create the Smith code generation agent.

    Smith uses the framework's own documentation tools (get_framework_docs,
    read_framework_doc, get_tool_status) to verify API details when needed.

    Parameters
    ----------
    user_name:
        The user's name for personalised address in Smith's responses.
    """
    tools = _create_smith_tools()

    from fireflyframework_genai.studio.assistant.agent import _resolve_assistant_model

    model = _resolve_assistant_model()

    instructions = _SMITH_SYSTEM_PROMPT.replace(
        "{user_name_placeholder}", user_name or "the user"
    )

    agent = FireflyAgent(
        "smith-codegen",
        model=model,
        instructions=instructions,
        tools=tools,
        auto_register=False,
        tags=["studio", "codegen"],
    )

    agent.agent.end_strategy = "exhaustive"  # type: ignore[assignment]
    return agent


_BLOCKED_PATTERNS = ['sudo ', 'rm -rf /', 'chmod 777', 'mkfs ', 'dd if=']
_RISKY_PATTERNS = ['pip install', 'rm ', 'curl ', 'wget ']
_RISKY_CHARS = ['|', '>', ';', '&&', '||']
_SAFE_PREFIXES = ['python ', 'python3 ', 'pytest', 'pip list', 'pip show', 'pip freeze']


def _classify_command(cmd: str) -> str:
    """Classify a shell command as safe, risky, or blocked."""
    cmd_stripped = cmd.strip()
    for pattern in _BLOCKED_PATTERNS:
        if pattern in cmd_stripped:
            return 'blocked'
    for pattern in _RISKY_PATTERNS:
        if pattern in cmd_stripped:
            return 'risky'
    for char in _RISKY_CHARS:
        if char in cmd_stripped:
            return 'risky'
    for prefix in _SAFE_PREFIXES:
        if cmd_stripped.startswith(prefix):
            return 'safe'
    return 'risky'


def _create_smith_tools() -> list:
    """Create tools available to Smith during code generation."""

    @firefly_tool(
        "get_framework_docs",
        description="Get live documentation about the Firefly GenAI Framework modules and capabilities.",
        auto_register=False,
    )
    async def get_framework_docs() -> str:
        import importlib

        docs: dict[str, Any] = {}
        try:
            from fireflyframework_genai._version import __version__
            docs["version"] = __version__
        except Exception:
            docs["version"] = "unknown"

        module_docs = {}
        for mod_name in [
            "fireflyframework_genai.agents",
            "fireflyframework_genai.tools",
            "fireflyframework_genai.reasoning",
            "fireflyframework_genai.memory",
            "fireflyframework_genai.pipeline",
        ]:
            try:
                mod = importlib.import_module(mod_name)
                module_docs[mod_name.split(".")[-1]] = (mod.__doc__ or "").strip().split("\n")[0]
            except Exception:
                pass
        docs["modules"] = module_docs

        try:
            from fireflyframework_genai.tools.registry import tool_registry as tr
            tools = tr.list_tools()
            docs["tools"] = [{"name": t.name, "description": t.description[:80]} for t in tools]
        except Exception:
            docs["tools"] = []

        try:
            from fireflyframework_genai.reasoning.registry import reasoning_registry
            docs["reasoning_patterns"] = reasoning_registry.list_patterns()
        except Exception:
            docs["reasoning_patterns"] = []

        return json.dumps(docs, indent=2)

    @firefly_tool(
        "read_framework_doc",
        description=(
            "Read a specific Firefly Framework documentation file. "
            "Available topics: agents, architecture, content, experiments, explainability, "
            "exposure-queues, exposure-rest, lab, memory, observability, pipeline, prompts, "
            "reasoning, security, studio, templates, tools, tutorial, use-case-idp, validation."
        ),
        auto_register=False,
    )
    async def read_framework_doc(topic: str) -> str:
        from pathlib import Path

        docs_dir = Path(__file__).resolve().parents[4] / "docs"
        valid_topics = {
            "agents", "architecture", "content", "experiments", "explainability",
            "exposure-queues", "exposure-rest", "lab", "memory", "observability",
            "pipeline", "prompts", "reasoning", "security", "studio", "templates",
            "tools", "tutorial", "use-case-idp", "validation",
        }
        if topic not in valid_topics:
            return json.dumps({"error": f"Unknown topic '{topic}'", "available_topics": sorted(valid_topics)})
        doc_path = docs_dir / f"{topic}.md"
        if not doc_path.exists():
            return json.dumps({"error": f"Doc file not found: {doc_path}"})
        content = doc_path.read_text(encoding="utf-8")
        if len(content) > 6000:
            content = content[:6000] + "\n\n... [truncated]"
        return json.dumps({"topic": topic, "content": content})

    @firefly_tool(
        "get_tool_status",
        description="Check which pipeline tools have valid credentials configured.",
        auto_register=False,
    )
    async def get_tool_status() -> str:
        from fireflyframework_genai.studio.settings import load_settings

        settings = load_settings()
        tc = settings.tool_credentials
        _map = {
            "search": ["serpapi_api_key", "serper_api_key", "tavily_api_key"],
            "database": ["database_url"],
        }
        results = []
        for tool_name, creds in _map.items():
            configured = [c for c in creds if getattr(tc, c, None)]
            results.append({"name": tool_name, "has_credentials": len(configured) > 0})
        return json.dumps(results)

    @firefly_tool("validate_python", description="Validate Python code syntax without executing it", auto_register=False)
    async def validate_python(code: str) -> str:
        import asyncio as _asyncio
        import os
        import sys
        import tempfile

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            tmp_path = f.name
        try:
            proc = await _asyncio.create_subprocess_exec(
                sys.executable, '-m', 'py_compile', tmp_path,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
            stdout, stderr = await _asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                return json.dumps({"valid": True})
            return json.dumps({"valid": False, "error": stderr.decode("utf-8", errors="replace")})
        except _asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return json.dumps({"valid": False, "error": "Validation timed out after 10s"})
        finally:
            os.unlink(tmp_path)

    @firefly_tool("run_python", description="Execute Python code in a subprocess with timeout", auto_register=False)
    async def run_python(code: str) -> str:
        import asyncio as _asyncio
        import os
        import sys
        import tempfile

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            tmp_path = f.name
        try:
            proc = await _asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await _asyncio.wait_for(proc.communicate(), timeout=30)
            except _asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return json.dumps({
                    "returncode": -1,
                    "stdout": "",
                    "stderr": "Execution timed out after 30s",
                })
            return json.dumps({
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace")[:5000],
                "stderr": stderr.decode("utf-8", errors="replace")[:2000],
            })
        finally:
            os.unlink(tmp_path)

    @firefly_tool("run_shell", description="Execute a shell command with safety classification", auto_register=False)
    async def run_shell(command: str) -> str:
        import asyncio as _asyncio

        level = _classify_command(command)
        if level == 'blocked':
            return json.dumps({"error": "Command blocked for safety", "command": command})
        if level == 'risky':
            # Return approval_required so the API layer can intercept this
            # and send a WebSocket message to the frontend.
            return json.dumps({"approval_required": True, "command": command, "level": level})
        proc = await _asyncio.create_subprocess_shell(
            command,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await _asyncio.wait_for(proc.communicate(), timeout=30)
        except _asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return json.dumps({
                "returncode": -1,
                "stdout": "",
                "stderr": "Command timed out after 30s",
            })
        return json.dumps({
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:5000],
            "stderr": stderr.decode("utf-8", errors="replace")[:2000],
        })

    @firefly_tool("get_canvas_state", description="Get the current canvas pipeline state", auto_register=False)
    async def get_canvas_state() -> str:
        return json.dumps(_canvas_state)

    @firefly_tool("get_project_info", description="Get current project name and user profile", auto_register=False)
    async def get_project_info() -> str:
        from fireflyframework_genai.studio.settings import load_settings
        try:
            settings = load_settings()
            return json.dumps({
                "user": settings.user_profile.display_name,
                "model": settings.model_defaults.default_model,
            })
        except Exception:
            return json.dumps({"user": "Unknown", "model": "openai:gpt-4o"})

    return [get_framework_docs, read_framework_doc, get_tool_status, validate_python, run_python, run_shell, get_canvas_state, get_project_info]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _build_smith_prompt(graph: dict, settings: dict | None = None) -> str:
    """Convert a graph JSON into a structured prompt for Smith."""
    default_model = "openai:gpt-4o"
    if settings:
        default_model = (
            settings.get("model_defaults", {}).get("default_model", default_model)
            or default_model
        )

    lines = [
        "Convert this visual pipeline graph into production Python code.",
        f"Default model for agents: {default_model}",
        "",
        "GRAPH JSON:",
        json.dumps(graph, indent=2),
    ]
    return "\n".join(lines)


def _extract_files(text: str) -> list[dict[str, str]]:
    """Extract multiple file blocks from Smith's response.

    Supports two formats:

    1. Multi-file: ``--- FILE: path/to/file.py ---`` followed by a code block.
    2. Single file: A lone ````` python`` block (backward compatible).

    Returns a list of dicts with keys ``path``, ``content``, and ``language``.
    """
    files: list[dict[str, str]] = []

    # Try multi-file format first: --- FILE: path ---
    file_pattern = re.compile(
        r'---\s*FILE:\s*(.+?)\s*---\s*\n```(?:\w+)?\s*\n(.*?)```',
        re.DOTALL,
    )
    matches = file_pattern.findall(text)
    if matches:
        for path, content in matches:
            path = path.strip()
            if path.endswith('.md'):
                lang = 'markdown'
            elif path.endswith('.json'):
                lang = 'json'
            elif path.endswith(('.yaml', '.yml')):
                lang = 'yaml'
            else:
                lang = 'python'
            files.append({
                'path': path,
                'content': content.strip(),
                'language': lang,
            })
        return files

    # Fallback: single python code block -> main.py
    match = re.search(r'```python\s*\n(.*?)```', text, re.DOTALL)
    if match:
        files.append({
            'path': 'main.py',
            'content': match.group(1).strip(),
            'language': 'python',
        })
        return files

    # Last resort: generic code block
    match = re.search(r'```\s*\n(.*?)```', text, re.DOTALL)
    if match:
        files.append({
            'path': 'main.py',
            'content': match.group(1).strip(),
            'language': 'python',
        })
        return files

    # No fences -- treat entire text as main.py if it looks like code
    if text.strip().startswith(('import ', 'from ', '#', 'async ', 'def ')):
        files.append({
            'path': 'main.py',
            'content': text.strip(),
            'language': 'python',
        })

    return files


async def generate_code_with_smith(
    graph: dict,
    settings: dict | None = None,
    user_name: str = "",
    shared_context: str = "",
) -> dict[str, Any]:
    """Generate Python code from a graph using the Smith agent.

    Parameters
    ----------
    graph:
        The canvas graph JSON (nodes + edges).
    settings:
        Optional settings dict with model_defaults for default model info.
    user_name:
        The user's name for personalised address in Smith's responses.
    shared_context:
        Optional cross-agent context block (project info, other agents'
        conversations) to prepend to the generation prompt.

    Returns
    -------
    dict
        ``{"files": [{"path": str, "content": str, "language": str}],
        "code": str, "notes": list[str]}``

        The ``code`` key is kept for backward compatibility and contains all
        file contents concatenated with header comments.
    """
    agent = create_smith_agent(user_name=user_name)
    prompt = _build_smith_prompt(graph, settings)
    if shared_context:
        prompt = shared_context + prompt

    try:
        result = await agent.run(prompt)

        if hasattr(result, "output"):
            response_text = str(result.output)
        elif hasattr(result, "data"):
            response_text = str(result.data)
        else:
            response_text = str(result)

        files = _extract_files(response_text)
        notes: list[str] = []

        if not files:
            notes.append("Smith returned an empty response. Check your LLM configuration.")
            files = [{"path": "main.py", "content": "# No code generated", "language": "python"}]

        # Backward-compatible "code" key with concatenated content
        code = "\n\n".join(f"# --- {f['path']} ---\n{f['content']}" for f in files)

        return {"files": files, "code": code, "notes": notes}

    except Exception as exc:
        logger.exception("Smith code generation failed")
        return {
            "files": [{"path": "main.py", "content": f"# Smith code generation failed: {exc}", "language": "python"}],
            "code": f"# Smith code generation failed: {exc}",
            "notes": [str(exc)],
        }
