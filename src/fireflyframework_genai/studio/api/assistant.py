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
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


async def _handle_chat(
    websocket: WebSocket,
    agent: Any,
    user_message: str,
    message_history: list[Any],
) -> None:
    """Handle a chat message by streaming the assistant's response."""
    try:
        # Try incremental streaming first
        stream_ctx = await agent.run_stream(
            user_message,
            streaming_mode="incremental",
            message_history=message_history,
        )
        full_text = ""
        async with stream_ctx as stream:
            async for token in stream.stream_tokens():
                full_text += token
                await websocket.send_json(
                    {
                        "type": "token",
                        "content": token,
                    }
                )

            # Update message history with new messages
            message_history.extend(stream.new_messages())

        await websocket.send_json(
            {
                "type": "response_complete",
                "full_text": full_text,
            }
        )

    except Exception as exc:
        # Fallback: try non-streaming run
        logger.warning("Streaming failed (%s), trying non-streaming fallback", exc)
        try:
            result = await agent.run(
                user_message,
                message_history=message_history,
            )
            response_text = str(result.output) if hasattr(result, "output") else str(result)

            # Update message history from fallback result
            if hasattr(result, "new_messages"):
                message_history.extend(result.new_messages())

            await websocket.send_json(
                {
                    "type": "token",
                    "content": response_text,
                }
            )
            await websocket.send_json(
                {
                    "type": "response_complete",
                    "full_text": response_text,
                }
            )

        except Exception as fallback_exc:
            logger.error("Assistant chat failed: %s", fallback_exc)
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Assistant error: {fallback_exc}",
                }
            )


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

    @router.websocket("/ws/assistant")
    async def assistant_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        logger.info("Assistant WebSocket connected")

        # Per-connection state
        from fireflyframework_genai.studio.assistant.agent import (
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
                    if not user_message:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "Empty message",
                            }
                        )
                        continue

                    await _handle_chat(websocket, agent, user_message, message_history)

                elif action == "clear_history":
                    message_history.clear()
                    await websocket.send_json({"type": "history_cleared"})

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
