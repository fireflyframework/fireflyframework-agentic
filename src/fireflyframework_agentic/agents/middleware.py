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

"""Agent middleware: pluggable before/after hooks for agent runs.

Middleware allows cross-cutting concerns -- logging, validation,
guardrails, cost tracking, retries, etc. -- to be composed
without modifying the agent itself.

Usage::

    class AuditMiddleware:
        async def before_run(self, context):
            context.metadata["audit_start"] = time.monotonic()

        async def after_run(self, context, result):
            elapsed = time.monotonic() - context.metadata["audit_start"]
            logger.info("Audit: agent=%s elapsed=%.1fms", context.agent_name, elapsed * 1000)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class MiddlewareContext:
    """Context passed to middleware hooks.

    Attributes:
        agent_name: Name of the agent being run.
        prompt: The user prompt.
        method: The execution path (``"run"``, ``"run_sync"``,
            ``"run_stream"``, or ``"run_with_reasoning"``).
        deps: The dependencies object.
        kwargs: Extra keyword arguments passed to ``run()``.
        metadata: Arbitrary dict for middleware to share state across hooks.
    """

    agent_name: str
    prompt: Any
    method: str = ""
    deps: Any = None
    kwargs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    context: Any = None


@runtime_checkable
class AgentMiddleware(Protocol):
    """Protocol for agent middleware.

    Middleware may implement either or both hooks.  Both are optional;
    a middleware that only defines ``before_run`` is perfectly valid.
    """

    async def before_run(self, context: MiddlewareContext) -> None:
        """Called before the agent runs.

        May mutate *context* (e.g. modify prompt, add metadata).
        Raising an exception here aborts the run.
        """
        ...

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        """Called after the agent runs successfully.

        May inspect or transform *result*.  The return value replaces
        the original result (return *result* unchanged to pass through).
        """
        ...


class MiddlewareChain:
    """Ordered chain of middleware that wraps an agent run."""

    def __init__(self, middlewares: list[AgentMiddleware] | None = None) -> None:
        self._middlewares: list[AgentMiddleware] = list(middlewares or [])

    def add(self, middleware: AgentMiddleware) -> None:
        """Append a middleware to the chain."""
        self._middlewares.append(middleware)

    def remove(self, middleware: AgentMiddleware) -> None:
        """Remove a middleware from the chain."""
        self._middlewares.remove(middleware)

    async def run_before(self, context: MiddlewareContext) -> None:
        """Execute all ``before_run`` hooks in order."""
        for mw in self._middlewares:
            if hasattr(mw, "before_run"):
                await mw.before_run(context)

    async def run_after(self, context: MiddlewareContext, result: Any) -> Any:
        """Execute all ``after_run`` hooks in reverse order."""
        for mw in reversed(self._middlewares):
            if hasattr(mw, "after_run"):
                result = await mw.after_run(context, result)
        return result

    def __len__(self) -> int:
        return len(self._middlewares)
