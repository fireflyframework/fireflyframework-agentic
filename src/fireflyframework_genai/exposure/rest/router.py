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

"""Auto-generated agent routes.

:func:`create_agent_router` generates REST endpoints for every registered
agent: ``POST /agents/{name}/run`` and ``GET /agents``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import APIRouter  # type: ignore[import-not-found]

from fireflyframework_genai.agents.registry import agent_registry
from fireflyframework_genai.exposure.rest.schemas import AgentRequest, AgentResponse
from fireflyframework_genai.exposure.rest.streaming import sse_stream, sse_stream_incremental
from fireflyframework_genai.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

# Server-side memory manager for REST conversations
_rest_memory = MemoryManager(working_scope_id="rest")


def _resolve_prompt(request: AgentRequest) -> Any:
    """Convert an AgentRequest prompt into a pydantic-ai compatible format."""
    if isinstance(request.prompt, str):
        return request.prompt

    from pydantic_ai.messages import BinaryContent, DocumentUrl, ImageUrl

    parts: list[Any] = []
    for part in request.prompt:
        if part.type == "text":
            parts.append(part.content)
        elif part.type == "image_url":
            parts.append(ImageUrl(url=part.content))
        elif part.type == "document_url":
            parts.append(DocumentUrl(url=part.content))
        elif part.type == "binary" and part.media_type:
            import base64

            data = base64.b64decode(part.content)
            parts.append(BinaryContent(data=data, media_type=part.media_type))
        else:
            parts.append(part.content)
    return parts


def create_agent_router() -> APIRouter:
    """Create a FastAPI router with agent invocation endpoints."""
    from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]

    router = APIRouter(prefix="/agents", tags=["agents"])

    @router.get("/")
    async def list_agents() -> list[dict[str, Any]]:
        return [info.model_dump() for info in agent_registry.list_agents()]

    @router.post("/{name}/run", response_model=AgentResponse)
    async def run_agent(name: str, request: AgentRequest) -> AgentResponse:
        if not agent_registry.has(name):
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        agent = agent_registry.get(name)
        try:
            prompt = _resolve_prompt(request)
            conv_id = request.conversation_id
            result = await agent.run(prompt, deps=request.deps, conversation_id=conv_id)
            output = result.output if hasattr(result, "output") else str(result)
            return AgentResponse(agent_name=name, output=output)
        except Exception:
            logger.exception("Agent '%s' run failed", name)
            return AgentResponse(agent_name=name, output=None, success=False, error="Internal server error")

    @router.post("/{name}/stream")
    async def stream_agent(name: str, request: AgentRequest) -> Any:
        """Stream agent responses in buffered mode (chunks/messages).

        This endpoint uses buffered streaming where the model's output is
        streamed in chunks or complete messages. Good for most use cases.
        """
        from starlette.responses import StreamingResponse

        if not agent_registry.has(name):
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        agent = agent_registry.get(name)
        prompt = _resolve_prompt(request)
        conv_id = request.conversation_id
        return StreamingResponse(
            sse_stream(agent, prompt, deps=request.deps, conversation_id=conv_id),
            media_type="text/event-stream",
        )

    @router.post("/{name}/stream/incremental")
    async def stream_agent_incremental(
        name: str,
        request: AgentRequest,
        debounce_ms: float = 0.0,
    ) -> Any:
        """Stream agent responses in incremental mode (token-by-token).

        This endpoint provides true token-by-token streaming with minimal
        latency. Tokens are sent as soon as they arrive from the model,
        without buffering. Ideal for interactive applications where users
        want to see responses immediately.

        Args:
            debounce_ms: Optional debounce delay in milliseconds to batch
                rapid tokens. Default 0 = no debouncing.
        """
        from starlette.responses import StreamingResponse

        if not agent_registry.has(name):
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        agent = agent_registry.get(name)
        prompt = _resolve_prompt(request)
        conv_id = request.conversation_id
        return StreamingResponse(
            sse_stream_incremental(
                agent,
                prompt,
                debounce_ms=debounce_ms,
                deps=request.deps,
                conversation_id=conv_id,
            ),
            media_type="text/event-stream",
        )

    # -- Conversation management ---------------------------------------------

    @router.post("/conversations", tags=["conversations"])
    async def create_conversation() -> dict[str, str]:
        """Create a new conversation and return its ID."""
        conv_id = _rest_memory.new_conversation()
        return {"conversation_id": conv_id}

    @router.get("/conversations/{conversation_id}", tags=["conversations"])
    async def get_conversation(conversation_id: str) -> dict[str, Any]:
        """Return the message history for a conversation."""
        messages = _rest_memory.get_message_history(conversation_id)
        serialized = []
        for msg in messages:
            dumper = getattr(msg, "model_dump", None)
            if dumper is not None:
                serialized.append(dumper(mode="json"))
            else:
                serialized.append({"content": str(msg)})
        return {
            "conversation_id": conversation_id,
            "message_count": len(messages),
            "messages": serialized,
        }

    @router.delete("/conversations/{conversation_id}", tags=["conversations"])
    async def delete_conversation(conversation_id: str) -> dict[str, str]:
        """Clear a conversation's history."""
        _rest_memory.clear_conversation(conversation_id)
        return {"status": "cleared", "conversation_id": conversation_id}

    return router
