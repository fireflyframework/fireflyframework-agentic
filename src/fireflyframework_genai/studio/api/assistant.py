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

"""WebSocket endpoint for the Studio AI assistant chat.

Provides a ``/ws/assistant`` WebSocket route that accepts user messages
and streams AI assistant responses token-by-token back to the frontend.

Uses a hybrid approach:
- ``run_stream()`` for text-only responses (fast token streaming)
- ``run()`` for tool-heavy responses (reliable multi-turn exhaustive execution)
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect  # type: ignore[import-not-found]
from pydantic import BaseModel  # type: ignore[import-not-found]
from pydantic_ai.usage import UsageLimits  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

# Generous limit for complex multi-tool pipelines (each tool call = 1 request).
_DEFAULT_REQUEST_LIMIT = 200

_CANVAS_TOOL_NAMES = frozenset(
    {
        "add_node",
        "connect_nodes",
        "configure_node",
        "remove_node",
        "clear_canvas",
    }
)


def _canvas_to_dict(canvas: Any) -> dict[str, Any]:
    """Serialize canvas state into a dict the frontend can apply."""
    return {
        "nodes": [
            {
                "id": n.id,
                "type": n.type,
                "label": n.label,
                "position": n.position,
                "config": n.config,
            }
            for n in canvas.nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source": e.source,
                "target": e.target,
                "source_handle": e.source_handle,
                "target_handle": e.target_handle,
            }
            for e in canvas.edges
        ],
    }


async def _send_canvas_sync(websocket: WebSocket, canvas: Any) -> None:
    """Push the full canvas state to the frontend after tool calls."""
    await websocket.send_json(
        {
            "type": "canvas_sync",
            "canvas": _canvas_to_dict(canvas),
        }
    )


def _normalize_args(args: Any) -> dict[str, Any]:
    """Ensure tool call args are always a dict.

    PydanticAI's ``ToolCallPart.args`` can be either a ``dict`` or a JSON
    ``str``.  The frontend expects a dict so it can render key-value pairs.
    """
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return {"raw": args}
    return {}


def _extract_tool_calls(result: Any) -> list[dict[str, Any]]:
    """Extract tool call information from PydanticAI result messages.

    Works with both ``RunResult`` (from ``run()``) and ``StreamedRunResult``
    (from ``run_stream()``).  Args are normalized to dicts so the frontend
    can render them as key-value pairs.
    """
    tool_calls: list[dict[str, Any]] = []
    try:
        if not hasattr(result, "new_messages"):
            return tool_calls
        for msg in result.new_messages():
            parts = getattr(msg, "parts", [])
            for part in parts:
                part_kind = getattr(part, "part_kind", "")
                if part_kind == "tool-call":
                    tool_calls.append(
                        {
                            "tool": getattr(part, "tool_name", "unknown"),
                            "args": _normalize_args(getattr(part, "args", {})),
                            "result": None,
                        }
                    )
                elif part_kind == "tool-return":
                    content = getattr(part, "content", "")
                    tool_name = getattr(part, "tool_name", "")
                    for tc in tool_calls:
                        if tc["tool"] == tool_name and tc["result"] is None:
                            tc["result"] = str(content)[:500] if content else ""
                            break
    except Exception as exc:
        logger.warning("Could not extract tool calls: %s", exc)
    return tool_calls


def _process_attachments(attachments: list[dict[str, Any]]) -> str:
    """Convert file attachments into text context for the LLM.

    Images are described by metadata (the LLM can't see raw images in
    text mode).  Text-based files have their content decoded and
    included inline.  Binary documents (PDF, DOCX, XLSX, PPTX) include
    metadata only — full extraction requires optional dependencies.
    """
    if not attachments:
        return ""

    parts: list[str] = []
    for att in attachments:
        name = att.get("name", "file")
        category = att.get("category", "other")
        size = att.get("size", 0)
        data_b64 = att.get("data", "")

        if category in ("text",):
            # Decode text content directly
            try:
                content = base64.b64decode(data_b64).decode("utf-8", errors="replace")
                # Truncate very large files
                if len(content) > 30_000:
                    content = content[:30_000] + "\n\n... [truncated]"
                parts.append(f"--- File: {name} ---\n{content}\n--- End of {name} ---")
            except Exception:
                parts.append(f"[Attached file: {name} ({size} bytes) — could not decode]")
        elif category == "spreadsheet" and name.lower().endswith(".csv"):
            # CSV is text-based
            try:
                content = base64.b64decode(data_b64).decode("utf-8", errors="replace")
                if len(content) > 30_000:
                    content = content[:30_000] + "\n\n... [truncated]"
                parts.append(f"--- CSV File: {name} ---\n{content}\n--- End of {name} ---")
            except Exception:
                parts.append(f"[Attached CSV: {name} ({size} bytes) — could not decode]")
        elif category == "image":
            parts.append(f"[Attached image: {name} ({size} bytes, type: {att.get('type', 'unknown')})]")
        elif category == "pdf":
            parts.append(
                f"[Attached PDF: {name} ({size} bytes) — "
                f"PDF text extraction not available in this session. "
                f"The user has shared a PDF document.]"
            )
        elif category == "document":
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            parts.append(
                f"[Attached document: {name} ({size} bytes, .{ext}) — "
                f"Document text extraction not available in this session.]"
            )
        elif category == "spreadsheet":
            parts.append(
                f"[Attached spreadsheet: {name} ({size} bytes) — "
                f"Spreadsheet data extraction not available in this session.]"
            )
        elif category == "presentation":
            parts.append(
                f"[Attached presentation: {name} ({size} bytes) — "
                f"Presentation text extraction not available in this session.]"
            )
        else:
            parts.append(f"[Attached file: {name} ({size} bytes)]")

    return "\n\n".join(parts)


async def _handle_chat_streaming(
    websocket: WebSocket,
    agent: Any,
    effective_message: str,
    message_history: list[Any],
    canvas: Any,
) -> list[dict[str, Any]]:
    """Stream tokens in real-time using ``run_stream()``.

    Yields text tokens one-by-one to the frontend as they arrive from the
    LLM.  After the stream completes, extracts tool call information and
    sends canvas sync if canvas tools were used.

    Returns the list of tool calls made during the response so the caller
    can decide whether to trigger reflexion validation.
    """
    tool_calls: list[dict[str, Any]] = []
    full_text_parts: list[str] = []

    async with await agent.run_stream(
        effective_message,
        message_history=message_history,
        usage_limits=UsageLimits(request_limit=_DEFAULT_REQUEST_LIMIT),
    ) as stream:
        async for token in stream.stream_text(delta=True):
            full_text_parts.append(token)
            await websocket.send_json({"type": "token", "content": token})

    full_text = "".join(full_text_parts)

    # Extract tool calls and update history from the completed stream
    tool_calls = _extract_tool_calls(stream)

    if hasattr(stream, "new_messages"):
        message_history.extend(stream.new_messages())

    logger.info(
        "Streaming complete (%d chars, %d tool calls, canvas: %d nodes, %d edges)",
        len(full_text),
        len(tool_calls),
        len(canvas.nodes),
        len(canvas.edges),
    )

    # Send tool call details so the UI shows what happened
    for tc in tool_calls:
        await websocket.send_json(
            {
                "type": "tool_call",
                "tool": tc["tool"],
                "args": tc["args"],
                "result": tc["result"],
            }
        )

    # Check if present_plan was called
    plan_call = next(
        (tc for tc in tool_calls if tc["tool"] == "present_plan"),
        None,
    )
    if plan_call and plan_call["args"]:
        args = plan_call["args"]
        await websocket.send_json(
            {
                "type": "plan",
                "summary": args.get("summary", ""),
                "steps": args.get("steps", "[]"),
                "options": args.get("options", "[]"),
                "question": args.get("question", ""),
            }
        )

    await websocket.send_json(
        {
            "type": "response_complete",
            "full_text": full_text,
        }
    )

    # Canvas sync after tool use
    used_canvas_tools = any(tc["tool"] in _CANVAS_TOOL_NAMES for tc in tool_calls)
    if used_canvas_tools:
        logger.info(
            "Canvas tools used, sending sync (%d nodes, %d edges)",
            len(canvas.nodes),
            len(canvas.edges),
        )
        await _send_canvas_sync(websocket, canvas)

    return tool_calls


async def _handle_chat_blocking(
    websocket: WebSocket,
    agent: Any,
    effective_message: str,
    message_history: list[Any],
    canvas: Any,
) -> list[dict[str, Any]]:
    """Blocking fallback using ``agent.run()``.

    Used when streaming is not available or fails.  Sends the full text
    as a single token message after completion.

    Returns the list of tool calls made during the response.
    """
    result = await agent.run(
        effective_message,
        message_history=message_history,
        usage_limits=UsageLimits(request_limit=_DEFAULT_REQUEST_LIMIT),
    )

    full_text = (str(result.output) if result.output else "") if hasattr(result, "output") else str(result)

    tool_calls = _extract_tool_calls(result)

    if hasattr(result, "new_messages"):
        message_history.extend(result.new_messages())

    logger.info(
        "Blocking complete (%d chars, %d tool calls, canvas: %d nodes, %d edges)",
        len(full_text),
        len(tool_calls),
        len(canvas.nodes),
        len(canvas.edges),
    )

    for tc in tool_calls:
        await websocket.send_json(
            {
                "type": "tool_call",
                "tool": tc["tool"],
                "args": tc["args"],
                "result": tc["result"],
            }
        )

    plan_call = next(
        (tc for tc in tool_calls if tc["tool"] == "present_plan"),
        None,
    )
    if plan_call and plan_call["args"]:
        args = plan_call["args"]
        await websocket.send_json(
            {
                "type": "plan",
                "summary": args.get("summary", ""),
                "steps": args.get("steps", "[]"),
                "options": args.get("options", "[]"),
                "question": args.get("question", ""),
            }
        )

    if full_text:
        await websocket.send_json({"type": "token", "content": full_text})

    await websocket.send_json(
        {
            "type": "response_complete",
            "full_text": full_text,
        }
    )

    used_canvas_tools = any(tc["tool"] in _CANVAS_TOOL_NAMES for tc in tool_calls)
    if used_canvas_tools:
        logger.info(
            "Canvas tools used, sending sync (%d nodes, %d edges)",
            len(canvas.nodes),
            len(canvas.edges),
        )
        await _send_canvas_sync(websocket, canvas)

    return tool_calls


_REFLEXION_MAX_ROUNDS = 3


async def _run_reflexion_validation(
    websocket: WebSocket,
    agent: Any,
    message_history: list[Any],
    canvas: Any,
) -> None:
    """Run framework-native reflexion validation after a pipeline build.

    Uses the built-in validate_pipeline logic to check the canvas, then
    sends any errors back through the Architect agent for correction.
    Repeats up to ``_REFLEXION_MAX_ROUNDS`` times until validation passes.
    """
    if not canvas.nodes:
        return

    for round_num in range(1, _REFLEXION_MAX_ROUNDS + 1):
        # Run validation directly against the canvas state
        validation = _validate_canvas(canvas)

        if validation["valid"]:
            logger.info("Reflexion validation passed (round %d)", round_num)
            return

        errors = validation.get("errors", [])
        warnings = validation.get("warnings", [])

        logger.info(
            "Reflexion round %d: %d errors, %d warnings",
            round_num,
            len(errors),
            len(warnings),
        )

        # Notify the user that auto-correction is running
        await websocket.send_json(
            {
                "type": "tool_call",
                "tool": "reflexion_validation",
                "args": {"round": round_num, "errors": len(errors)},
                "result": f"Found {len(errors)} errors. Auto-correcting...",
            }
        )

        # Ask the Architect to fix the issues via its canvas tools
        fix_prompt = (
            f"[REFLEXION VALIDATION - Round {round_num}]\n"
            f"The pipeline has {len(errors)} validation errors that must be fixed:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
        if warnings:
            fix_prompt += "\n\nWarnings (non-blocking):\n" + "\n".join(f"  - {w}" for w in warnings)
        fix_prompt += (
            "\n\nFix ALL errors using configure_node, connect_nodes, or add_node as needed. "
            "Do NOT explain. Just fix the issues with tool calls."
        )

        try:
            result = await agent.run(
                fix_prompt,
                message_history=message_history,
                usage_limits=UsageLimits(request_limit=50),
            )

            fix_tool_calls = _extract_tool_calls(result)
            if hasattr(result, "new_messages"):
                message_history.extend(result.new_messages())

            # Send tool calls to frontend
            for tc in fix_tool_calls:
                await websocket.send_json(
                    {
                        "type": "tool_call",
                        "tool": tc["tool"],
                        "args": tc["args"],
                        "result": tc["result"],
                    }
                )

            # Sync canvas if tools were used
            used_canvas = any(tc["tool"] in _CANVAS_TOOL_NAMES for tc in fix_tool_calls)
            if used_canvas:
                await _send_canvas_sync(websocket, canvas)

            fix_text = ""
            if hasattr(result, "output"):
                fix_text = str(result.output) if result.output else ""

            if fix_text:
                await websocket.send_json({"type": "token", "content": fix_text})

        except Exception as exc:
            logger.warning("Reflexion fix round %d failed: %s", round_num, exc)
            break

    # Final check
    final = _validate_canvas(canvas)
    if not final["valid"]:
        remaining = final.get("errors", [])
        await websocket.send_json(
            {
                "type": "token",
                "content": (
                    f"\n\n[Reflexion completed with {len(remaining)} remaining issue(s). "
                    "Please review and address manually.]"
                ),
            }
        )


def _validate_canvas(canvas: Any) -> dict[str, Any]:
    """Run validation logic against the current canvas state (synchronous)."""
    errors: list[str] = []
    warnings: list[str] = []

    if not canvas.nodes:
        return {"valid": False, "errors": ["Pipeline is empty."], "warnings": []}

    connected_ids: set[str] = set()
    for e in canvas.edges:
        connected_ids.add(e.source)
        connected_ids.add(e.target)

    for node in canvas.nodes:
        cfg = node.config
        ntype = node.type

        if ntype == "agent":
            if not cfg.get("model"):
                errors.append(f"Agent '{node.id}' is missing 'model'.")
            if not cfg.get("instructions"):
                errors.append(f"Agent '{node.id}' is missing 'instructions'.")
            if not cfg.get("description"):
                warnings.append(f"Agent '{node.id}' has no 'description'.")
        elif ntype == "tool":
            if not cfg.get("tool_name"):
                errors.append(f"Tool '{node.id}' is missing 'tool_name'.")
        elif ntype == "reasoning":
            if not cfg.get("pattern"):
                errors.append(f"Reasoning '{node.id}' is missing 'pattern'.")
        elif ntype == "condition":
            if not cfg.get("condition"):
                errors.append(f"Condition '{node.id}' is missing 'condition'.")
            if not cfg.get("branches"):
                errors.append(f"Condition '{node.id}' is missing 'branches'.")
        elif ntype == "input":
            if not cfg.get("trigger_type"):
                errors.append(f"Input '{node.id}' is missing 'trigger_type'.")
        elif ntype == "output":
            if not cfg.get("destination_type"):
                errors.append(f"Output '{node.id}' is missing 'destination_type'.")
        elif ntype == "custom_code":
            if not cfg.get("code"):
                errors.append(f"CustomCode '{node.id}' is missing 'code'.")
        elif ntype == "memory":
            if not cfg.get("memory_action"):
                errors.append(f"Memory '{node.id}' is missing 'memory_action'.")
        elif ntype == "validator":
            if not cfg.get("validation_rule"):
                errors.append(f"Validator '{node.id}' is missing 'validation_rule'.")

        if node.id not in connected_ids and len(canvas.nodes) > 1:
            errors.append(f"Node '{node.id}' ({node.label or ntype}) is orphaned.")

    input_nodes = [n for n in canvas.nodes if n.type == "input"]
    output_nodes = [n for n in canvas.nodes if n.type == "output"]
    if len(input_nodes) > 1:
        errors.append(f"Pipeline has {len(input_nodes)} input nodes but only 1 is allowed.")
    if input_nodes and not output_nodes:
        errors.append("Pipeline has an input node but no output node.")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


async def _handle_chat(
    websocket: WebSocket,
    agent: Any,
    user_message: str,
    message_history: list[Any],
    canvas: Any,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """Handle a chat message with hybrid streaming and reflexion validation.

    Attempts real-time token streaming via ``run_stream()`` first.  If
    streaming is not available or fails, falls back to blocking
    ``run()`` which sends the full text as a single token.

    Reflexion validation only triggers when the Architect completed a
    substantial build (called ``validate_pipeline`` or used 3+ canvas
    tools), not after every incremental addition.
    """
    try:
        # Prepend file attachment context if present
        effective_message = user_message
        if attachments:
            attachment_context = _process_attachments(attachments)
            if attachment_context:
                effective_message = f"{attachment_context}\n\nUser message: {user_message}"

        logger.info(
            "Running assistant (canvas: %d nodes, %d edges, attachments: %d)",
            len(canvas.nodes),
            len(canvas.edges),
            len(attachments or []),
        )

        # Use blocking run() for reliable multi-turn tool execution.
        # The Architect's exhaustive end strategy requires the full agent
        # loop (tool calls → re-prompt → more tool calls → final text),
        # which run_stream() does not handle correctly.
        tool_calls = await _handle_chat_blocking(
            websocket,
            agent,
            effective_message,
            message_history,
            canvas,
        )

        # Reflexion triggers only on substantial builds:
        # - The Architect called validate_pipeline (it believes the build is done)
        # - OR 3+ canvas tool calls in a single response (full build sequence)
        called_validate = any(tc["tool"] == "validate_pipeline" for tc in tool_calls)
        canvas_tool_count = sum(1 for tc in tool_calls if tc["tool"] in _CANVAS_TOOL_NAMES)

        if (called_validate or canvas_tool_count >= 3) and canvas.nodes:
            logger.info(
                "Reflexion triggered (validate_called=%s, canvas_tools=%d)",
                called_validate,
                canvas_tool_count,
            )
            try:
                await _run_reflexion_validation(
                    websocket,
                    agent,
                    message_history,
                    canvas,
                )
            except Exception as val_exc:
                logger.warning("Reflexion validation failed: %s", val_exc)

    except Exception as exc:
        logger.error("Assistant run failed: %s", exc, exc_info=True)

        err_str = str(exc)
        if "request_limit" in err_str:
            user_msg = (
                "This request required too many operations and hit the safety limit. "
                "Try breaking your request into smaller steps, or simplify the "
                "pipeline you are asking me to build."
            )
        elif "rate" in err_str.lower() and ("limit" in err_str.lower() or "429" in err_str):
            user_msg = "The LLM provider is rate-limiting requests. Please wait a moment and try again."
        else:
            user_msg = f"Assistant error: {exc}"

        await websocket.send_json(
            {
                "type": "error",
                "message": user_msg,
            }
        )


def _build_project_context(canvas: Any = None, project_name: str = "") -> str:
    """Gather live project, integration, and tool state for the Architect.

    This context is prepended (invisibly) to the first user message so the
    assistant knows what the user is working on without them having to explain.
    Includes cross-agent conversation summaries from Smith and Oracle.
    """
    parts: list[str] = []

    # Current canvas state
    if canvas and canvas.nodes:
        node_summaries = []
        for n in canvas.nodes:
            cfg_keys = ", ".join(f"{k}={v!r}" for k, v in list(n.config.items())[:4]) if n.config else "unconfigured"
            node_summaries.append(f"  - {n.id} ({n.type}): {n.label or 'unlabeled'} [{cfg_keys}]")
        edge_summaries = [f"  - {e.source} -> {e.target}" for e in canvas.edges]
        parts.append(
            f"[CONTEXT] Current canvas has {len(canvas.nodes)} nodes and {len(canvas.edges)} edges:\n"
            + "\n".join(node_summaries)
            + ("\nConnections:\n" + "\n".join(edge_summaries) if edge_summaries else "")
        )

    # Current project
    try:
        from fireflyframework_genai.studio.config import StudioConfig
        from fireflyframework_genai.studio.projects import ProjectManager

        pm = ProjectManager(StudioConfig().projects_dir)
        projects = pm.list_all()
        if projects:
            names = [p.name for p in projects]
            parts.append(f"[CONTEXT] Active projects: {', '.join(names)}.")
    except Exception:
        pass

    # Custom tools / integrations
    try:
        from fireflyframework_genai.studio.custom_tools import CustomToolManager

        manager = CustomToolManager()
        tools = manager.list_all()
        if tools:
            summaries = []
            for t in tools:
                status = "registered"
                summaries.append(f"  - {t.name} (type={t.tool_type}, {status})")
            parts.append("[CONTEXT] Custom tools / integrations installed:\n" + "\n".join(summaries))
        else:
            parts.append("[CONTEXT] No custom tools or integrations installed yet.")
    except Exception:
        pass

    # Registered framework tools
    try:
        from fireflyframework_genai.tools.registry import tool_registry

        registered = tool_registry.list_tools()
        if registered:
            names = [t.name for t in registered]
            parts.append(f"[CONTEXT] Framework tools available: {', '.join(names)}.")
    except Exception:
        pass

    # Settings snapshot (provider configured, default model)
    try:
        from fireflyframework_genai.studio.settings import load_settings

        settings = load_settings()
        if settings.model_defaults.default_model:
            parts.append(f"[CONTEXT] Default model: {settings.model_defaults.default_model}.")
    except Exception:
        pass

    # Cross-agent context: what Smith and Oracle have discussed with the user
    if project_name:
        try:
            from fireflyframework_genai.studio.assistant.shared_context import (
                build_shared_context,
            )

            # Canvas here is the typed object, convert to dict for shared context
            canvas_dict = None
            if canvas and canvas.nodes:
                canvas_dict = {
                    "nodes": [
                        {"id": n.id, "type": n.type, "data": {"label": n.label or "", "config": n.config or {}}}
                        for n in canvas.nodes
                    ],
                    "edges": [{"source": e.source, "target": e.target} for e in canvas.edges],
                }
            shared = build_shared_context(project_name, canvas_dict, exclude_agent="architect")
            if shared:
                parts.append(shared)
        except Exception:
            pass

    return "\n".join(parts)


class InferProjectNameRequest(BaseModel):
    message: str


class SaveHistoryRequest(BaseModel):
    messages: list[dict]


def create_assistant_router() -> APIRouter:
    """Create an :class:`APIRouter` with the assistant WebSocket endpoint.

    Endpoints
    ---------
    ``WS /ws/assistant``
        Accept a WebSocket connection for the AI assistant chat.  Supports
        ``"action": "chat"`` to send a user message and receive a streamed
        response, and ``"action": "clear_history"`` to reset the
        conversation.
    """
    router = APIRouter(tags=["assistant"])

    @router.get("/api/assistant/{project}/history")
    async def get_chat_history(project: str):
        from fireflyframework_genai.studio.assistant.history import load_chat_history

        return load_chat_history(project)

    @router.post("/api/assistant/{project}/history")
    async def save_chat_history_endpoint(project: str, body: SaveHistoryRequest):
        from fireflyframework_genai.studio.assistant.history import save_chat_history

        save_chat_history(project, body.messages)
        return {"status": "saved"}

    @router.delete("/api/assistant/{project}/history")
    async def delete_chat_history(project: str):
        from fireflyframework_genai.studio.assistant.history import clear_chat_history

        clear_chat_history(project)
        return {"status": "cleared"}

    @router.post("/api/assistant/infer-project-name")
    async def infer_project_name(body: InferProjectNameRequest):
        import time

        try:
            from pydantic_ai import Agent

            agent = Agent(
                "openai:gpt-4.1-mini",
                system_prompt=(
                    "Given this user request, generate a short project name "
                    "(2-4 words, kebab-case, no spaces). Just return the name, nothing else."
                ),
            )
            result = await agent.run(body.message)
            name = str(result.output).strip().lower().replace(" ", "-")
            # Sanitize: only allow alphanumeric and hyphens
            name = "".join(c for c in name if c.isalnum() or c == "-").strip("-")
            if not name:
                name = f"project-{int(time.time())}"
            return {"name": name}
        except Exception:
            return {"name": f"project-{int(time.time())}"}

    @router.websocket("/ws/assistant")
    async def assistant_ws(websocket: WebSocket, project: str = Query(default="")) -> None:
        await websocket.accept()
        logger.info("Assistant WebSocket connected")

        # Per-connection state
        from fireflyframework_genai.studio.assistant.agent import (
            CanvasEdge,
            CanvasNode,
            CanvasState,
            create_studio_assistant,
        )

        canvas = CanvasState()
        message_history: list[Any] = []

        # Create the agent.  We catch errors to avoid crashing the
        # WebSocket on startup (e.g. missing API key).
        try:
            agent = create_studio_assistant(canvas=canvas)
        except Exception as exc:
            logger.error("Failed to create studio assistant: %s", exc)
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Assistant unavailable: {exc}",
                }
            )
            await websocket.close()
            return

        # Load project-scoped chat history if project is specified
        if project:
            try:
                from fireflyframework_genai.studio.assistant.history import load_chat_history

                saved_history = load_chat_history(project)
                if saved_history:
                    logger.info("Loaded %d saved messages for project '%s'", len(saved_history), project)
            except Exception as exc:
                logger.warning("Could not load chat history for project '%s': %s", project, exc)

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Invalid JSON",
                        }
                    )
                    continue

                action = message.get("action")

                if action == "chat":
                    user_message = message.get("message", "").strip()
                    chat_attachments = message.get("attachments", [])
                    if not user_message and not chat_attachments:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "Empty message",
                            }
                        )
                        continue
                    if not user_message:
                        user_message = "Please analyze the attached files."

                    # Inject live project context so The Architect knows what
                    # the user is currently working on.
                    project_context = _build_project_context(canvas=canvas, project_name=project)
                    if project_context:
                        user_message = f"{project_context}\n\n{user_message}"

                    await _handle_chat(
                        websocket,
                        agent,
                        user_message,
                        message_history,
                        canvas,
                        attachments=chat_attachments or None,
                    )

                    # Auto-save chat history for project
                    if project:
                        try:
                            from fireflyframework_genai.studio.assistant.history import save_chat_history

                            save_chat_history(
                                project,
                                [
                                    {
                                        "role": "user",
                                        "content": user_message,
                                        "timestamp": __import__("datetime")
                                        .datetime.now(__import__("datetime").UTC)
                                        .isoformat(),
                                    },
                                ],
                            )
                        except Exception:
                            pass

                elif action == "clear_history":
                    message_history.clear()
                    await websocket.send_json({"type": "history_cleared"})

                elif action == "sync_canvas":
                    # Restore canvas state from frontend (e.g. after refresh)
                    sync_nodes = message.get("nodes", [])
                    sync_edges = message.get("edges", [])
                    canvas.nodes.clear()
                    canvas.edges.clear()
                    max_id = 0
                    for n in sync_nodes:
                        data = n.get("data", {})
                        config = {k: v for k, v in data.items() if k not in ("label", "_executionState")}
                        canvas.nodes.append(
                            CanvasNode(
                                id=n.get("id", ""),
                                type=n.get("type", "pipeline_step"),
                                label=data.get("label", n.get("id", "")),
                                position=n.get("position", {"x": 0, "y": 0}),
                                config=config,
                            )
                        )
                        # Track highest numeric suffix for counter
                        m = re.search(r"(\d+)$", n.get("id", ""))
                        if m:
                            max_id = max(max_id, int(m.group(1)))
                    for e in sync_edges:
                        canvas.edges.append(
                            CanvasEdge(
                                id=e.get("id", ""),
                                source=e.get("source", ""),
                                target=e.get("target", ""),
                                source_handle=e.get("sourceHandle"),
                                target_handle=e.get("targetHandle"),
                            )
                        )
                    canvas._counter = max_id
                    logger.info(
                        "Canvas synced from frontend: %d nodes, %d edges (counter=%d)",
                        len(canvas.nodes),
                        len(canvas.edges),
                        max_id,
                    )

                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": f"Unknown action: {action}",
                        }
                    )

        except WebSocketDisconnect:
            logger.info("Assistant WebSocket disconnected")

    return router
