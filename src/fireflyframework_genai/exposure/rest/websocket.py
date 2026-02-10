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

"""WebSocket endpoint for bidirectional multi-turn agent conversations.

Clients connect to ``/ws/agents/{name}`` and send JSON messages.
The server responds with streamed tokens and final results over the
same connection, enabling real-time conversational UIs.

Message protocol
----------------

**Client → Server** (JSON)::

    {
        "prompt": "Hello, agent!",
        "conversation_id": "optional-id",
        "deps": null
    }

**Server → Client** (JSON, one or more)::

    {"type": "token",   "data": "partial text..."}
    {"type": "result",  "data": "full output", "success": true}
    {"type": "error",   "data": "error message", "success": false}
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import APIRouter  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


def create_websocket_router() -> APIRouter:
    """Create a FastAPI router with the agent WebSocket endpoint."""
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect  # type: ignore[import-not-found]

    from fireflyframework_genai.agents.registry import agent_registry
    from fireflyframework_genai.memory.manager import MemoryManager

    router = APIRouter(tags=["websocket"])
    _ws_memory = MemoryManager(working_scope_id="ws")

    @router.websocket("/ws/agents/{name}")
    async def agent_ws(websocket: WebSocket, name: str) -> None:
        """Multi-turn WebSocket conversation with a registered agent."""
        if not agent_registry.has(name):
            await websocket.close(code=4004, reason=f"Agent '{name}' not found")
            return

        await websocket.accept()
        agent = agent_registry.get(name)
        conversation_id: str | None = None

        # Use a per-connection memory scope to avoid cross-talk between
        # concurrent WebSocket sessions sharing the same agent.
        conn_id = uuid.uuid4().hex[:8]
        conn_memory = _ws_memory.fork(working_scope_id=f"ws:{conn_id}")

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    await _send_error(websocket, "Invalid JSON")
                    continue

                prompt = msg.get("prompt", "")
                if not prompt:
                    await _send_error(websocket, "Missing 'prompt' field")
                    continue

                # Conversation management
                conversation_id = msg.get("conversation_id") or conversation_id
                if conversation_id is None:
                    conversation_id = uuid.uuid4().hex
                    await websocket.send_json(
                        {"type": "conversation_id", "data": conversation_id},
                    )

                # Set per-connection memory only if the agent doesn't already
                # have one configured by the user.
                if agent.memory is None:
                    agent.memory = conn_memory

                deps = msg.get("deps")

                # Attempt streaming; if it fails, report the error rather than
                # falling through to run() which would double-process.
                try:
                    final: str | None = None

                    if hasattr(agent, "run_stream"):
                        try:
                            async with await agent.run_stream(  # type: ignore[attr-defined]
                                prompt,
                                deps=deps,
                                conversation_id=conversation_id,
                            ) as stream:
                                full_output: list[str] = []
                                async for token in stream.stream_text(delta=True):
                                    full_output.append(token)
                                    await websocket.send_json(
                                        {"type": "token", "data": token},
                                    )
                                final = "".join(full_output)
                        except Exception:
                            # Streaming not supported or failed — fall back
                            final = None

                    if final is None:
                        result = await agent.run(
                            prompt,
                            deps=deps,
                            conversation_id=conversation_id,
                        )
                        final = result.output if hasattr(result, "output") else str(result)

                    await websocket.send_json(
                        {"type": "result", "data": final, "success": True},
                    )

                except Exception as exc:
                    logger.exception("WebSocket agent error for '%s'", name)
                    await _send_error(websocket, str(exc))

        except WebSocketDisconnect:
            logger.debug("WebSocket client disconnected from agent '%s'", name)

    return router


async def _send_error(websocket: Any, message: str) -> None:
    """Send an error frame to the client."""
    await websocket.send_json(
        {"type": "error", "data": message, "success": False},
    )
