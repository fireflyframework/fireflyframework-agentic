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

"""Oracle API endpoints: WebSocket for real-time analysis, REST for insights.

The Oracle observes pipeline state and produces structured insights
(suggestions, warnings, critical issues).  Users can approve or skip
each insight.  Approved insights are forwarded to The Architect.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect  # type: ignore[import-not-found]
from pydantic import BaseModel  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


class _SaveChatHistoryBody(BaseModel):
    messages: list[dict]


def create_oracle_router() -> APIRouter:
    """Create an :class:`APIRouter` with Oracle endpoints.

    Endpoints
    ---------
    ``WS /ws/oracle``
        Real-time Oracle analysis via WebSocket.
    ``GET /api/oracle/{project}/insights``
        List all insights for a project.
    ``POST /api/oracle/{project}/insights/{insight_id}/approve``
        Mark an insight as approved and return its action_instruction.
    ``POST /api/oracle/{project}/insights/{insight_id}/skip``
        Mark an insight as skipped.
    """
    router = APIRouter(tags=["oracle"])

    # ------------------------------------------------------------------
    # REST endpoints
    # ------------------------------------------------------------------

    @router.get("/api/oracle/{project}/insights")
    async def get_insights(project: str):
        from fireflyframework_genai.studio.assistant.oracle_notifications import (
            list_insights,
        )

        insights = list_insights(project)
        return [asdict(i) for i in insights]

    @router.post("/api/oracle/{project}/insights/{insight_id}/approve")
    async def approve_insight(project: str, insight_id: str):
        from fireflyframework_genai.studio.assistant.oracle_notifications import (
            update_insight_status,
        )

        updated = update_insight_status(project, insight_id, "approved")
        if updated is None:
            raise HTTPException(status_code=404, detail="Insight not found")
        return {
            "status": "approved",
            "action_instruction": updated.action_instruction,
        }

    @router.post("/api/oracle/{project}/insights/{insight_id}/skip")
    async def skip_insight(project: str, insight_id: str):
        from fireflyframework_genai.studio.assistant.oracle_notifications import (
            update_insight_status,
        )

        updated = update_insight_status(project, insight_id, "skipped")
        if updated is None:
            raise HTTPException(status_code=404, detail="Insight not found")
        return {"status": "skipped"}

    # ------------------------------------------------------------------
    # REST endpoints — Oracle chat history
    # ------------------------------------------------------------------

    @router.get("/api/oracle/{project}/chat-history")
    async def get_oracle_chat_history(project: str):
        from fireflyframework_genai.studio.assistant.history import load_oracle_history
        return load_oracle_history(project)

    @router.post("/api/oracle/{project}/chat-history")
    async def save_oracle_chat_history(project: str, body: _SaveChatHistoryBody):
        from fireflyframework_genai.studio.assistant.history import save_oracle_history
        save_oracle_history(project, body.messages)
        return {"status": "saved"}

    @router.delete("/api/oracle/{project}/chat-history")
    async def delete_oracle_chat_history(project: str):
        from fireflyframework_genai.studio.assistant.history import clear_oracle_history
        clear_oracle_history(project)
        return {"status": "cleared"}

    # ------------------------------------------------------------------
    # WebSocket endpoint
    # ------------------------------------------------------------------

    @router.websocket("/ws/oracle")
    async def oracle_ws(
        websocket: WebSocket, project: str = Query(default="")
    ) -> None:
        await websocket.accept()
        logger.info("Oracle WebSocket connected (project=%s)", project)

        # Per-connection canvas state (populated from frontend sync)
        canvas_state: dict[str, Any] = {"nodes": [], "edges": []}

        def _get_canvas() -> dict[str, Any]:
            return canvas_state

        # Create the Oracle agent
        try:
            from fireflyframework_genai.studio.assistant.oracle import (
                create_oracle_agent,
            )
            from fireflyframework_genai.studio.settings import load_settings

            settings = load_settings()
            user_name = settings.user_profile.name or ""
            oracle = create_oracle_agent(_get_canvas, user_name=user_name)
        except Exception as exc:
            logger.error("Failed to create Oracle agent: %s", exc)
            await websocket.send_json(
                {"type": "error", "message": f"Oracle unavailable: {exc}"}
            )
            await websocket.close()
            return

        message_history: list[Any] = []

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"type": "error", "message": "Invalid JSON"}
                    )
                    continue

                action = message.get("action")

                if action == "sync_canvas":
                    # Frontend sends current canvas state for Oracle to analyze
                    canvas_state["nodes"] = message.get("nodes", [])
                    canvas_state["edges"] = message.get("edges", [])
                    await websocket.send_json({"type": "canvas_synced"})

                elif action == "analyze":
                    # Full pipeline review
                    try:
                        context_block = _build_shared_context_for_oracle(project, canvas_state)
                        result = await oracle.run(
                            context_block
                            + "Analyze the current pipeline thoroughly. "
                            "Use analyze_pipeline, check_connectivity, and review_agent_setup "
                            "to gather data. Then use suggest_improvement for each issue or "
                            "recommendation you find. Consider the project purpose and "
                            "what the user discussed with The Architect when formulating "
                            "your insights.",
                            message_history=message_history,
                        )

                        if hasattr(result, "new_messages"):
                            message_history.extend(result.new_messages())

                        # Extract suggestions from tool calls
                        insights = _extract_oracle_insights(result)
                        for insight_data in insights:
                            from fireflyframework_genai.studio.assistant.oracle_notifications import (
                                add_insight,
                                create_insight,
                            )

                            insight = create_insight(
                                title=insight_data.get("title", "Insight"),
                                description=insight_data.get("description", ""),
                                severity=insight_data.get("severity", "suggestion"),
                                action_instruction=insight_data.get(
                                    "action_instruction"
                                ),
                            )
                            if project:
                                add_insight(project, insight)

                            await websocket.send_json(
                                {"type": "insight", **asdict(insight)}
                            )

                        # Also send any text output
                        text_output = ""
                        if hasattr(result, "output"):
                            text_output = str(result.output) if result.output else ""

                        await websocket.send_json(
                            {
                                "type": "analysis_complete",
                                "message": text_output,
                                "insight_count": len(insights),
                            }
                        )

                    except Exception as exc:
                        logger.error("Oracle analysis failed: %s", exc, exc_info=True)
                        await websocket.send_json(
                            {"type": "error", "message": f"Analysis failed: {exc}"}
                        )

                elif action == "analyze_node":
                    # Single node analysis
                    node_id = message.get("node_id", "")
                    if not node_id:
                        await websocket.send_json(
                            {"type": "error", "message": "Missing node_id"}
                        )
                        continue

                    try:
                        context_block = _build_shared_context_for_oracle(project, canvas_state)
                        result = await oracle.run(
                            context_block
                            + f"Analyze node '{node_id}' specifically. "
                            f"Use analyze_node_config to check its configuration, "
                            f"then suggest improvements if needed.",
                            message_history=message_history,
                        )

                        if hasattr(result, "new_messages"):
                            message_history.extend(result.new_messages())

                        insights = _extract_oracle_insights(result)
                        for insight_data in insights:
                            from fireflyframework_genai.studio.assistant.oracle_notifications import (
                                add_insight,
                                create_insight,
                            )

                            insight = create_insight(
                                title=insight_data.get("title", "Insight"),
                                description=insight_data.get("description", ""),
                                severity=insight_data.get("severity", "suggestion"),
                                action_instruction=insight_data.get(
                                    "action_instruction"
                                ),
                            )
                            if project:
                                add_insight(project, insight)

                            await websocket.send_json(
                                {"type": "insight", **asdict(insight)}
                            )

                        text_output = ""
                        if hasattr(result, "output"):
                            text_output = str(result.output) if result.output else ""

                        await websocket.send_json(
                            {
                                "type": "analysis_complete",
                                "message": text_output,
                                "insight_count": len(insights),
                            }
                        )

                    except Exception as exc:
                        logger.error(
                            "Oracle node analysis failed: %s", exc, exc_info=True
                        )
                        await websocket.send_json(
                            {"type": "error", "message": f"Analysis failed: {exc}"}
                        )

                elif action == "chat":
                    # Free-form conversational chat with The Oracle
                    user_msg = message.get("message", "").strip()
                    if not user_msg:
                        await websocket.send_json(
                            {"type": "error", "message": "Empty message"}
                        )
                        continue

                    try:
                        context_block = _build_shared_context_for_oracle(project, canvas_state)
                        result = await oracle.run(
                            context_block + user_msg,
                            message_history=message_history,
                        )

                        full_text = ""
                        if hasattr(result, "output"):
                            full_text = str(result.output) if result.output else ""
                        else:
                            full_text = str(result)

                        if hasattr(result, "new_messages"):
                            message_history.extend(result.new_messages())

                        # Send response in chunks for frontend streaming effect
                        import asyncio

                        _CHUNK_SIZE = 12
                        for i in range(0, len(full_text), _CHUNK_SIZE):
                            chunk = full_text[i : i + _CHUNK_SIZE]
                            await websocket.send_json(
                                {"type": "oracle_token", "content": chunk}
                            )
                            await asyncio.sleep(0.01)

                        # Extract any insights produced during chat
                        chat_insights = _extract_oracle_insights(result)
                        for insight_data in chat_insights:
                            from fireflyframework_genai.studio.assistant.oracle_notifications import (
                                add_insight,
                                create_insight,
                            )

                            insight = create_insight(
                                title=insight_data.get("title", "Insight"),
                                description=insight_data.get("description", ""),
                                severity=insight_data.get("severity", "suggestion"),
                                action_instruction=insight_data.get(
                                    "action_instruction"
                                ),
                            )
                            if project:
                                add_insight(project, insight)
                            await websocket.send_json(
                                {"type": "insight", **asdict(insight)}
                            )

                        await websocket.send_json(
                            {
                                "type": "oracle_response_complete",
                                "full_text": full_text,
                            }
                        )

                    except Exception as exc:
                        logger.error(
                            "Oracle chat failed: %s", exc, exc_info=True
                        )
                        await websocket.send_json(
                            {"type": "error", "message": f"Oracle chat error: {exc}"}
                        )

                else:
                    await websocket.send_json(
                        {"type": "error", "message": f"Unknown action: {action}"}
                    )

        except WebSocketDisconnect:
            logger.info("Oracle WebSocket disconnected")

    return router


def _extract_oracle_insights(result: Any) -> list[dict[str, Any]]:
    """Extract suggestion data from Oracle tool call results."""
    insights: list[dict[str, Any]] = []
    try:
        if not hasattr(result, "new_messages"):
            return insights
        for msg in result.new_messages():
            parts = getattr(msg, "parts", [])
            for part in parts:
                part_kind = getattr(part, "part_kind", "")
                if part_kind == "tool-return":
                    tool_name = getattr(part, "tool_name", "")
                    if tool_name == "suggest_improvement":
                        content = getattr(part, "content", "")
                        try:
                            data = json.loads(content)
                            if data.get("type") == "suggestion":
                                insights.append(data)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    elif tool_name == "analyze_pipeline":
                        content = getattr(part, "content", "")
                        try:
                            data = json.loads(content)
                            for issue in data.get("issues", []):
                                insights.append(issue)
                        except (json.JSONDecodeError, TypeError):
                            pass
    except Exception as exc:
        logger.warning("Could not extract Oracle insights: %s", exc)
    return insights


def _build_shared_context_for_oracle(
    project: str, canvas_state: dict[str, Any]
) -> str:
    """Build cross-agent context for the Oracle using the shared builder.

    Replaces the old frontend-supplied context approach — context is now
    assembled server-side from persisted conversation histories.
    """
    try:
        from fireflyframework_genai.studio.assistant.shared_context import (
            build_shared_context,
        )

        return build_shared_context(project, canvas_state, exclude_agent="oracle")
    except Exception:
        return ""
