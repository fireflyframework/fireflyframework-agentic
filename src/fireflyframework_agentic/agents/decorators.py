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

"""Decorator-driven API for defining Firefly agents.

The :func:`firefly_agent` decorator lets users define an agent and its
instructions in a single, concise declaration::

    @firefly_agent("summariser", model="openai:gpt-4o", tags=["nlp"])
    def summariser_instructions(ctx):
        return "You are a summarisation assistant."

The decorated function becomes the agent's dynamic instructions callback and
the decorator returns the fully-configured :class:`FireflyAgent` instance.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.types import Metadata

if TYPE_CHECKING:
    from fireflyframework_agentic.agents.middleware import AgentMiddleware
    from fireflyframework_agentic.memory.manager import MemoryManager


def firefly_agent(
    name: str,
    *,
    model: str | Model | None = None,
    output_type: type = str,
    deps_type: type = type(None),
    tools: Sequence[Any] = (),
    description: str = "",
    version: str = "0.1.0",
    tags: Sequence[str] = (),
    metadata: Metadata | None = None,
    retries: int | None = None,
    model_settings: dict[str, Any] | None = None,
    memory: MemoryManager | None = None,
    middleware: list[AgentMiddleware] | None = None,
    default_middleware: bool = True,
    auto_register: bool = True,
) -> Callable[[Callable[..., str]], FireflyAgent[Any, Any]]:
    """Create a :class:`FireflyAgent` using the decorated function as its instructions.

    The decorated function may accept a single ``ctx`` argument (the
    :class:`pydantic_ai.RunContext`) and must return a string.  It is
    registered as the agent's dynamic instructions callback.

    Parameters:
        name: Unique human-readable agent name.
        model: LLM model string or :class:`pydantic_ai.models.Model` instance;
            falls back to the framework default.
        output_type: Pydantic model or scalar type for structured output.
        deps_type: Dependency type expected at runtime.
        tools: Sequence of tool functions or ``pydantic_ai.Tool`` objects.
        description: Free-form description for documentation.
        version: Semantic version of this agent definition.
        tags: Tags for capability-based discovery.
        metadata: Arbitrary key-value metadata.
        retries: Override the default retry count.
        model_settings: Pydantic AI model settings.
        memory: Optional :class:`MemoryManager` for conversation history.
        middleware: List of :class:`AgentMiddleware` instances.
        default_middleware: Auto-wire ``LoggingMiddleware``.
        auto_register: Automatically register in the global registry.

    Returns:
        The constructed :class:`FireflyAgent` instance.

    Example::

        @firefly_agent("qa-bot", tags=["qa"])
        def qa_instructions(ctx):
            return "Answer questions accurately and cite sources."

        # qa_instructions is now a FireflyAgent instance
        result = await qa_instructions.run("What is the capital of France?")
    """

    def decorator(func: Callable[..., str]) -> FireflyAgent[Any, Any]:
        agent = FireflyAgent(
            name,
            model=model,
            output_type=output_type,
            deps_type=deps_type,
            tools=tools,
            description=description or func.__doc__ or "",
            version=version,
            tags=tags,
            metadata=metadata,
            retries=retries,
            model_settings=model_settings,
            memory=memory,
            middleware=middleware,
            default_middleware=default_middleware,
            auto_register=auto_register,
        )
        # Register the decorated function as a dynamic instructions provider
        agent.instructions(func)
        return agent  # type: ignore[return-value]

    return decorator
