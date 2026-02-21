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

"""Agent Smith WebSocket endpoint for Firefly Agentic Studio.

Provides a WebSocket interface at /ws/smith for code generation,
execution, and chat with Agent Smith.

Actions
-------
``generate``
    Convert the current canvas graph into production Python code using
    the Smith agent.  Sends ``smith_token`` messages during generation,
    followed by ``code_generated`` with the final code.

``chat``
    Free-form conversation with Agent Smith (code questions, refactoring,
    explanations).  Streams tokens as ``smith_token`` messages.

``sync_canvas``
    Update the per-connection canvas state that Smith uses as context.

``execute``
    Run generated code in a subprocess and return stdout/stderr.

``approve_command``
    Approve or deny a pending command that Smith requested to execute.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


def create_smith_router() -> APIRouter:
    """Create an :class:`APIRouter` with the Smith WebSocket endpoint.

    Endpoints
    ---------
    ``WS /ws/smith``
        Accept a WebSocket connection for Agent Smith code generation
        and chat.  Supports actions: ``generate``, ``chat``,
        ``sync_canvas``, ``execute``, ``approve_command``.
    """
    router = APIRouter(tags=["smith"])

    @router.websocket("/ws/smith")
    async def smith_ws(
        websocket: WebSocket, project: str = Query(default="")
    ) -> None:
        await websocket.accept()
        logger.info("Smith WebSocket connected (project=%s)", project)

        # Per-connection canvas state (populated from frontend sync)
        canvas_state: dict[str, Any] = {"nodes": [], "edges": []}

        # Per-connection pending commands awaiting user approval
        pending_commands: dict[str, dict[str, Any]] = {}

        # Per-connection message history for multi-turn chat
        message_history: list[Any] = []

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"type": "error", "message": "Invalid JSON"}
                    )
                    continue

                action = data.get("action", "")

                if action == "generate":
                    await _handle_generate(
                        websocket, data, canvas_state, message_history
                    )
                elif action == "chat":
                    await _handle_chat(
                        websocket, data, canvas_state, message_history,
                        pending_commands,
                    )
                elif action == "sync_canvas":
                    await _handle_sync_canvas(websocket, data, canvas_state)
                elif action == "execute":
                    await _handle_execute(websocket, data)
                elif action == "approve_command":
                    await _handle_approve_command(
                        websocket, data, pending_commands
                    )
                else:
                    await websocket.send_json(
                        {"type": "error", "message": f"Unknown action: {action}"}
                    )

        except WebSocketDisconnect:
            logger.info("Smith WebSocket disconnected")
        except Exception as exc:
            logger.exception("Smith WebSocket error")
            try:
                await websocket.send_json(
                    {"type": "error", "message": str(exc)}
                )
            except Exception:
                pass

    return router


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


async def _handle_generate(
    websocket: WebSocket,
    data: dict[str, Any],
    canvas_state: dict[str, Any],
    message_history: list[Any],
) -> None:
    """Handle the ``generate`` action: convert canvas graph to Python code.

    Uses ``generate_code_with_smith()`` from the Smith agent module.
    Sends ``smith_token`` messages for progress, ``code_generated`` with
    the final code, and ``smith_response_complete`` when done.
    """
    try:
        from fireflyframework_genai.studio.assistant.smith import (
            generate_code_with_smith,
        )
        from fireflyframework_genai.studio.settings import load_settings

        settings = load_settings()
        settings_dict = {
            "model_defaults": {
                "default_model": settings.model_defaults.default_model,
            },
        }

        # Build graph from the provided data or fall back to canvas state
        graph = data.get("graph", canvas_state)

        # Notify the frontend that generation has started
        await websocket.send_json(
            {"type": "smith_token", "content": "Generating code from pipeline...\n"}
        )

        # Pass user name so Smith can personalise responses
        user_name = ""
        try:
            user_name = settings.user_profile.name or ""
        except Exception:
            pass

        result = await generate_code_with_smith(graph, settings_dict, user_name=user_name)

        code = result.get("code", "")
        files = result.get("files", [])
        notes = result.get("notes", [])

        # Send structured multi-file result
        await websocket.send_json(
            {
                "type": "files_generated",
                "files": files,
                "notes": notes,
            }
        )

        # Backward-compatible single code message
        await websocket.send_json(
            {
                "type": "code_generated",
                "code": code,
                "notes": notes,
            }
        )

        # Send completion
        await websocket.send_json(
            {
                "type": "smith_response_complete",
                "full_text": code,
                "notes": notes,
            }
        )

    except Exception as exc:
        logger.error("Smith generation failed: %s", exc, exc_info=True)
        await websocket.send_json(
            {"type": "error", "message": f"Code generation failed: {exc}"}
        )


async def _handle_chat(
    websocket: WebSocket,
    data: dict[str, Any],
    canvas_state: dict[str, Any],
    message_history: list[Any],
    pending_commands: dict[str, dict[str, Any]],
) -> None:
    """Handle the ``chat`` action: free-form conversation with Smith.

    Creates a Smith agent, includes the current canvas state as context,
    and runs the agent with the user message.  Streams tokens as
    ``smith_token`` messages and sends ``smith_response_complete`` at end.
    """
    user_msg = data.get("message", "").strip()
    if not user_msg:
        await websocket.send_json(
            {"type": "error", "message": "Empty message"}
        )
        return

    try:
        from fireflyframework_genai.studio.assistant.smith import (
            create_smith_agent,
        )

        from fireflyframework_genai.studio.settings import load_settings as _load_settings

        _user_name = ""
        try:
            _settings = _load_settings()
            _user_name = _settings.user_profile.name or ""
        except Exception:
            pass

        smith = create_smith_agent(user_name=_user_name)

        # Enrich the prompt with canvas context so Smith knows what the
        # user is working on
        context_parts: list[str] = []
        if canvas_state.get("nodes"):
            context_parts.append(
                "[CURRENT PIPELINE STATE]\n"
                + json.dumps(canvas_state, indent=2)
            )
        context_parts.append(user_msg)
        effective_message = "\n\n".join(context_parts)

        # Use run() for reliable exhaustive tool execution (not run_stream,
        # which cannot guarantee all tool calls complete with end_strategy
        # 'exhaustive').
        result = await smith.run(
            effective_message,
            message_history=message_history,
        )

        if hasattr(result, "output"):
            full_text = str(result.output) if result.output else ""
        else:
            full_text = str(result)

        if hasattr(result, "new_messages"):
            message_history.extend(result.new_messages())

        # Check if the response contains code blocks that should go to
        # the Code tab instead of being displayed inline in chat.
        extracted_files = _extract_code_blocks(full_text)

        if extracted_files:
            # Route code to the Code tab via files_generated
            await websocket.send_json(
                {
                    "type": "files_generated",
                    "files": extracted_files,
                    "notes": [],
                }
            )

            # Strip code blocks from the chat text, keep only narrative
            narrative = _strip_code_blocks(full_text).strip()

            # Send narrative as chat tokens (or a brief note if empty)
            chat_text = narrative or "Code generated — see the Code tab."
            _CHUNK_SIZE = 80
            for i in range(0, len(chat_text), _CHUNK_SIZE):
                chunk = chat_text[i : i + _CHUNK_SIZE]
                await websocket.send_json(
                    {"type": "smith_token", "content": chunk}
                )

            combined_code = "\n\n".join(
                f"# --- {f['path']} ---\n{f['content']}" for f in extracted_files
            )

            await websocket.send_json(
                {
                    "type": "smith_response_complete",
                    "full_text": chat_text,
                    "code": combined_code,
                }
            )
        else:
            # No code blocks — send as regular chat
            _CHUNK_SIZE = 80
            for i in range(0, len(full_text), _CHUNK_SIZE):
                chunk = full_text[i : i + _CHUNK_SIZE]
                await websocket.send_json(
                    {"type": "smith_token", "content": chunk}
                )

            await websocket.send_json(
                {
                    "type": "smith_response_complete",
                    "full_text": full_text,
                }
            )

        # Extract any tool calls for visibility
        tool_calls = _extract_tool_calls(result)
        for tc in tool_calls:
            await websocket.send_json(
                {
                    "type": "tool_call",
                    "tool": tc["tool"],
                    "args": tc["args"],
                    "result": tc["result"],
                }
            )

        # Check for pending approvals in tool return parts
        await _check_pending_approvals(
            websocket, result, pending_commands
        )

    except Exception as exc:
        logger.error("Smith chat failed: %s", exc, exc_info=True)
        await websocket.send_json(
            {"type": "error", "message": f"Smith chat error: {exc}"}
        )


async def _handle_sync_canvas(
    websocket: WebSocket,
    data: dict[str, Any],
    canvas_state: dict[str, Any],
) -> None:
    """Handle the ``sync_canvas`` action: update per-connection canvas state."""
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    canvas_state["nodes"] = nodes
    canvas_state["edges"] = edges

    # Keep the module-level singleton in smith.py in sync so that the
    # get_canvas_state tool returns current data.
    from fireflyframework_genai.studio.assistant.smith import update_canvas_state

    update_canvas_state(nodes, edges)
    await websocket.send_json({"type": "canvas_synced"})


async def _handle_execute(
    websocket: WebSocket,
    data: dict[str, Any],
) -> None:
    """Handle the ``execute`` action: run code in a subprocess.

    Writes the code to a temporary file and runs it with the Python
    interpreter.  Sends ``execution_result`` with stdout, stderr, and
    return code.
    """
    code = data.get("code", "").strip()
    if not code:
        await websocket.send_json(
            {"type": "error", "message": "No code to execute"}
        )
        return

    tmp_file: Path | None = None
    try:
        # Write code to a temp file
        tmp_dir = Path(tempfile.gettempdir()) / "firefly-smith"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = tmp_dir / f"smith_{uuid.uuid4().hex[:8]}.py"
        tmp_file.write_text(code, encoding="utf-8")

        timeout = data.get("timeout", 30)

        import sys

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(tmp_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(tmp_dir),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            await websocket.send_json(
                {
                    "type": "execution_result",
                    "stdout": "",
                    "stderr": f"Execution timed out after {timeout}s",
                    "return_code": -1,
                }
            )
            return

        await websocket.send_json(
            {
                "type": "execution_result",
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "return_code": proc.returncode,
            }
        )

    except Exception as exc:
        logger.error("Smith execution failed: %s", exc, exc_info=True)
        await websocket.send_json(
            {"type": "error", "message": f"Execution failed: {exc}"}
        )
    finally:
        # Clean up temp file
        if tmp_file is not None:
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception:
                pass


async def _handle_approve_command(
    websocket: WebSocket,
    data: dict[str, Any],
    pending_commands: dict[str, dict[str, Any]],
) -> None:
    """Handle the ``approve_command`` action: approve or deny a pending command.

    Smith may request to execute commands that need user approval.  The
    frontend sends ``approve_command`` with a ``command_id`` and an
    ``approved`` boolean.
    """
    command_id = data.get("command_id", "")
    approved = data.get("approved", False)

    if not command_id:
        await websocket.send_json(
            {"type": "error", "message": "Missing command_id"}
        )
        return

    command = pending_commands.pop(command_id, None)
    if command is None:
        await websocket.send_json(
            {
                "type": "error",
                "message": f"Unknown or expired command: {command_id}",
            }
        )
        return

    if not approved:
        await websocket.send_json(
            {
                "type": "smith_response_complete",
                "full_text": "Command denied by user.",
                "command_id": command_id,
            }
        )
        return

    # Execute the approved shell command
    shell_command = command.get("command", "")
    if not shell_command:
        await websocket.send_json(
            {
                "type": "smith_response_complete",
                "full_text": "Approved command was empty.",
                "command_id": command_id,
            }
        )
        return

    # Run the approved shell command asynchronously
    try:
        proc = await asyncio.create_subprocess_shell(
            shell_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout = command.get("timeout", 30)
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            await websocket.send_json(
                {
                    "type": "execution_result",
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout}s",
                    "return_code": -1,
                    "command_id": command_id,
                }
            )
            return

        await websocket.send_json(
            {
                "type": "execution_result",
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "return_code": proc.returncode,
                "command_id": command_id,
            }
        )
    except Exception as exc:
        logger.error("Approved command execution failed: %s", exc, exc_info=True)
        await websocket.send_json(
            {"type": "error", "message": f"Command execution failed: {exc}"}
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Regex for fenced code blocks: ```lang\n...code...\n```
_CODE_BLOCK_RE = re.compile(
    r"```(\w*)\n(.*?)```",
    re.DOTALL,
)

# Map language tags to file extensions
_LANG_TO_EXT: dict[str, str] = {
    "python": ".py", "py": ".py",
    "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts",
    "json": ".json", "yaml": ".yaml", "yml": ".yaml",
    "bash": ".sh", "sh": ".sh", "shell": ".sh",
    "sql": ".sql", "html": ".html", "css": ".css",
    "xml": ".xml", "toml": ".toml", "ini": ".ini",
}

# Minimum total code length to be considered "substantial" (skip tiny snippets)
_MIN_CODE_LENGTH = 120


def _extract_code_blocks(text: str) -> list[dict[str, Any]]:
    """Extract fenced code blocks from markdown text as file entries.

    Returns a list of ``{"path": ..., "content": ..., "language": ...}``
    dicts suitable for a ``files_generated`` WebSocket message.
    Only returns results when the total code is substantial enough to
    warrant display in the Code tab (>= ``_MIN_CODE_LENGTH`` chars).
    """
    matches = _CODE_BLOCK_RE.findall(text)
    if not matches:
        return []

    total_code = sum(len(content.strip()) for _, content in matches)
    if total_code < _MIN_CODE_LENGTH:
        return []

    files: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    for lang_tag, content in matches:
        lang = lang_tag.lower() or "python"
        ext = _LANG_TO_EXT.get(lang, ".py")
        # Generate a short filename per block
        count = counters.get(lang, 0) + 1
        counters[lang] = count
        name = f"smith_code_{count}{ext}" if count > 1 else f"smith_code{ext}"
        files.append({
            "path": name,
            "content": content.strip(),
            "language": lang,
        })
    return files


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks from markdown, keeping surrounding narrative."""
    return _CODE_BLOCK_RE.sub("", text)


async def _check_pending_approvals(
    websocket: WebSocket,
    result: Any,
    pending_commands: dict[str, dict[str, Any]],
) -> None:
    """Scan agent result messages for tool returns that contain approval_required.

    When the ``run_shell`` tool classifies a command as risky, it returns a JSON
    payload with ``"approval_required": true``.  This function detects those
    payloads, stores the command in *pending_commands*, and sends an
    ``approval_required`` WebSocket message so the frontend can prompt the user.
    """
    if not hasattr(result, "new_messages"):
        return

    for msg in result.new_messages():
        parts = getattr(msg, "parts", [])
        for part in parts:
            part_kind = getattr(part, "part_kind", "")
            if part_kind != "tool-return":
                continue
            content = getattr(part, "content", "")
            if not content:
                continue
            try:
                payload = json.loads(str(content)) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or not payload.get("approval_required"):
                continue

            command_id = uuid.uuid4().hex[:12]
            command = payload.get("command", "")
            level = payload.get("level", "risky")

            pending_commands[command_id] = {
                "command": command,
                "level": level,
                "timeout": 30,
            }

            await websocket.send_json(
                {
                    "type": "approval_required",
                    "commandId": command_id,
                    "command": command,
                    "level": level,
                }
            )


def _normalize_args(args: Any) -> dict[str, Any]:
    """Ensure tool call args are always a dict.

    PydanticAI's ``ToolCallPart.args`` can be either a ``dict`` or a JSON
    ``str``.  The frontend expects a dict.
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
    (from ``run_stream()``).
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
                            tc["result"] = (
                                str(content)[:500] if content else ""
                            )
                            break
    except Exception as exc:
        logger.warning("Could not extract tool calls: %s", exc)
    return tool_calls
