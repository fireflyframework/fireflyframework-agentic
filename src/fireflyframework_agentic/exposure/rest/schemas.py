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

"""Request and response Pydantic models for the REST exposure layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MultiModalPart(BaseModel):
    """A single multimodal content part in a REST request.

    Attributes:
        type: Content type: ``"text"``, ``"image_url"``, ``"document_url"``,
            ``"audio_url"``, ``"video_url"``, or ``"binary"``.
        content: The content value (text string, URL, or base64 data).
        media_type: MIME type for binary content.
    """

    type: str = "text"
    content: str = ""
    media_type: str | None = None


class AgentRequest(BaseModel):
    """Request body for agent invocation.

    *prompt* can be a plain string or a list of multimodal parts for VLM
    use cases (images, documents, etc.).

    When *conversation_id* is provided, the server maintains
    conversation history across requests.
    """

    prompt: str | list[MultiModalPart] = ""
    deps: Any = None
    model_settings: dict[str, Any] | None = None
    conversation_id: str | None = None


class AgentResponse(BaseModel):
    """Response body from an agent invocation."""

    agent_name: str
    output: Any
    success: bool = True
    error: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    agents: int = 0
    details: dict[str, str] = {}
