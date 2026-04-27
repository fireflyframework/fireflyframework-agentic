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

"""Shared type aliases, protocols, and generic type variables used across the framework.

This module re-exports Pydantic AI's multimodal content types so that the rest
of the framework (and downstream applications) can import them from a single,
stable location.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, TypeAlias, TypeVar, runtime_checkable

from pydantic_ai.messages import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    VideoUrl,
)
from pydantic_ai.messages import MultiModalContent as PydanticMultiModalContent
from pydantic_ai.messages import UserContent as PydanticUserContent

__all__ = [
    "AgentDepsT",
    "AgentLike",
    "OutputT",
    "ToolInputT",
    "ToolOutputT",
    "UserContent",
    "MultiModalContent",
    "UserPrompt",
    "ImageUrl",
    "AudioUrl",
    "DocumentUrl",
    "VideoUrl",
    "BinaryContent",
    "JSON",
    "Metadata",
    "Headers",
]

# ---------------------------------------------------------------------------
# Generic type variables
# ---------------------------------------------------------------------------

AgentDepsT = TypeVar("AgentDepsT")
"""Type variable for agent dependency types, matching Pydantic AI's AgentDepsT."""

OutputT = TypeVar("OutputT")
"""Type variable for agent or reasoning pattern output types."""

ToolInputT = TypeVar("ToolInputT")
"""Type variable for tool input parameter types."""

ToolOutputT = TypeVar("ToolOutputT")
"""Type variable for tool return types."""

# ---------------------------------------------------------------------------
# Multimodal content types (re-exported from Pydantic AI)
# ---------------------------------------------------------------------------

UserContent: TypeAlias = PydanticUserContent
"""A single content element: text string or any multimodal part.

This is the union: ``str | ImageUrl | AudioUrl | DocumentUrl | VideoUrl | BinaryContent | CachePoint``.
"""

MultiModalContent: TypeAlias = PydanticMultiModalContent
"""Non-text multimodal content: ``ImageUrl | AudioUrl | DocumentUrl | VideoUrl | BinaryContent``."""

UserPrompt: TypeAlias = str | Sequence[UserContent]
"""The full prompt type accepted by :class:`FireflyAgent`: a plain string or
a sequence of multimodal content parts (text interspersed with images,
documents, audio, video, or binary data)."""

# ---------------------------------------------------------------------------
# Agent protocol — used to type-hint parameters that accept "any agent-like
# object" (FireflyAgent, a pydantic_ai Agent, or any duck-typed equivalent).
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentLike(Protocol):
    """Structural protocol satisfied by any object with an async ``run`` method.

    :class:`FireflyAgent`, :class:`pydantic_ai.Agent`, and user-defined
    wrappers all satisfy this protocol, allowing framework utilities
    (reasoning patterns, pipeline steps, validators, compression, lab)
    to accept agents without importing concrete types.
    """

    async def run(self, prompt: Any, **kwargs: Any) -> Any:
        """Run the agent with the given prompt."""
        ...


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

JSON: TypeAlias = dict[str, Any] | list[Any] | str | int | float | bool | None
"""Type alias representing any JSON-compatible value."""

Metadata: TypeAlias = dict[str, Any]
"""Type alias for metadata dictionaries attached to agents, tools, traces, etc."""

Headers: TypeAlias = dict[str, str]
"""Type alias for HTTP or message header dictionaries."""
