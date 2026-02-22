"""Shared cross-agent context builder for Firefly Agentic Studio.

All three agents (Architect, Smith, Oracle) share context about the
project, canvas state, and each other's recent conversations.  This
ensures coherent collaboration: Smith knows WHY the pipeline was built,
Oracle knows what Smith discussed, and the Architect sees feedback
from both.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_shared_context(
    project_name: str,
    canvas_state: dict[str, Any] | None = None,
    exclude_agent: str = "",
) -> str:
    """Build a context block with project info and cross-agent conversation summaries.

    Parameters
    ----------
    project_name:
        The active project name.
    canvas_state:
        Optional canvas dict with ``nodes`` and ``edges`` lists.
    exclude_agent:
        Which agent's own history to skip (``"architect"``, ``"smith"``,
        or ``"oracle"``).  An agent should not see its own history as
        context since it already has it in message_history.

    Returns
    -------
    str
        A formatted context block to prepend to the agent prompt.
    """
    parts: list[str] = []

    # 1. Project metadata
    try:
        from fireflyframework_genai.studio.config import StudioConfig
        from fireflyframework_genai.studio.projects import ProjectManager

        pm = ProjectManager(StudioConfig().projects_dir)
        project = next((p for p in pm.list_all() if p.name == project_name), None)
        if project:
            desc = project.description or "No description"
            parts.append(f"[PROJECT] {project.name}: {desc}")
        elif project_name:
            parts.append(f"[PROJECT] {project_name}")
    except Exception:
        if project_name:
            parts.append(f"[PROJECT] {project_name}")

    # 2. Canvas state summary
    if canvas_state and canvas_state.get("nodes"):
        parts.append(_summarize_canvas(canvas_state))

    # 3. Recent Architect conversation
    if exclude_agent != "architect":
        try:
            from fireflyframework_genai.studio.assistant.history import (
                load_chat_history,
            )

            architect_msgs = load_chat_history(project_name)
            if architect_msgs:
                parts.append(_summarize_history("Architect", architect_msgs[-10:]))
        except Exception:
            pass

    # 4. Recent Smith conversation
    if exclude_agent != "smith":
        try:
            from fireflyframework_genai.studio.assistant.history import (
                load_smith_history,
            )

            smith_msgs = load_smith_history(project_name)
            if smith_msgs:
                parts.append(_summarize_history("Smith", smith_msgs[-10:]))
        except Exception:
            pass

    # 5. Recent Oracle conversation
    if exclude_agent != "oracle":
        try:
            from fireflyframework_genai.studio.assistant.history import (
                load_oracle_history,
            )

            oracle_msgs = load_oracle_history(project_name)
            if oracle_msgs:
                parts.append(_summarize_history("Oracle", oracle_msgs[-10:]))
        except Exception:
            pass

    if not parts:
        return ""

    return "\n\n".join(parts) + "\n\n"


def _summarize_history(agent_name: str, messages: list[dict]) -> str:
    """Summarize recent messages, showing intent rather than full content."""
    lines: list[str] = []
    for msg in messages:
        role = "User" if msg.get("role") == "user" else agent_name
        content = msg.get("content", "")[:200]
        if content:
            lines.append(f"  {role}: {content}")
    if not lines:
        return ""
    return f"[RECENT {agent_name.upper()} CONVERSATION]\n" + "\n".join(lines)


def _summarize_canvas(canvas: dict[str, Any]) -> str:
    """Brief canvas summary: node types and connections."""
    nodes = canvas.get("nodes", [])
    edges = canvas.get("edges", [])
    type_counts: dict[str, int] = {}
    for n in nodes:
        t = n.get("type", n.get("data", {}).get("type", "unknown"))
        type_counts[t] = type_counts.get(t, 0) + 1
    types = ", ".join(f"{c}x {t}" for t, c in type_counts.items())
    return f"[CANVAS] {len(nodes)} nodes ({types}), {len(edges)} connections"
