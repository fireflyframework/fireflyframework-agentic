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

"""Decorator-driven API for defining tools with minimal boilerplate.

The :func:`firefly_tool` decorator transforms an async function into a
registered :class:`~fireflyframework_agentic.tools.base.BaseTool` instance::

    @firefly_tool("search", tags=["web"])
    async def search(query: str) -> str:
        '''Search the web for *query*.'''
        ...

:func:`guarded` and :func:`retryable` add cross-cutting concerns to any
:class:`~fireflyframework_agentic.tools.base.BaseTool`.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from fireflyframework_agentic.tools.base import BaseTool, GuardProtocol
from fireflyframework_agentic.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# Type alias
AsyncHandler = Callable[..., Coroutine[Any, Any, Any]]


class _DecoratedTool(BaseTool):
    """Concrete tool created by the :func:`firefly_tool` decorator."""

    def __init__(
        self,
        name: str,
        handler: AsyncHandler,
        *,
        description: str = "",
        tags: Sequence[str] = (),
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(name, description=description, tags=tags, guards=guards)
        self._handler = handler

    async def _execute(self, **kwargs: Any) -> Any:
        return await self._handler(**kwargs)

    def pydantic_handler(self) -> Any:
        """Return a wrapper preserving the original handler's signature.

        Pydantic AI inspects the function signature to generate JSON
        schemas for LLM tool calls.  :meth:`BaseTool.execute` uses
        ``**kwargs`` which hides the real parameter names.  This method
        returns a thin wrapper whose ``__wrapped__`` attribute points to
        the original handler so that :func:`inspect.signature` resolves
        the correct parameter list, while execution still routes through
        :meth:`execute` for guard evaluation.
        """

        @functools.wraps(self._handler)
        async def _wrapper(**kwargs: Any) -> Any:
            return await self.execute(**kwargs)

        return _wrapper


def firefly_tool(
    name: str,
    *,
    description: str = "",
    tags: Sequence[str] = (),
    guards: Sequence[GuardProtocol] = (),
    auto_register: bool = True,
) -> Callable[[AsyncHandler], BaseTool]:
    """Create a :class:`BaseTool` from an async function and optionally register it.

    Parameters:
        name: Unique tool name.
        description: Description (falls back to the function's docstring).
        tags: Tags for capability-based discovery.
        guards: Guards evaluated before execution.
        auto_register: When *True*, the tool is added to the global registry.

    Returns:
        The constructed :class:`BaseTool` instance (replaces the decorated
        function in the declaring module's namespace).
    """

    def decorator(func: AsyncHandler) -> BaseTool:
        tool = _DecoratedTool(
            name,
            func,
            description=description or func.__doc__ or "",
            tags=tags,
            guards=guards,
        )
        if auto_register:
            tool_registry.register(tool)
        return tool

    return decorator


def guarded(guard: GuardProtocol) -> Callable[[BaseTool], BaseTool]:
    """Append a guard to an existing :class:`BaseTool`.

    Usage::

        @guarded(RateLimitGuard(max_calls=10))
        @firefly_tool("search")
        async def search(query: str) -> str: ...
    """

    def decorator(tool: BaseTool) -> BaseTool:
        tool.guards.append(guard)
        return tool

    return decorator


def retryable(
    max_retries: int = 3,
    backoff: float = 1.0,
) -> Callable[[BaseTool], BaseTool]:
    """Wrap a :class:`BaseTool`'s execute method with retry logic.

    On failure, the tool is retried up to *max_retries* times with
    exponential backoff starting at *backoff* seconds.

    Parameters:
        max_retries: Maximum number of retry attempts.
        backoff: Initial delay in seconds (doubles on each retry).
    """

    def decorator(tool: BaseTool) -> BaseTool:
        original_execute = tool.execute

        @functools.wraps(original_execute)
        async def _retrying_execute(**kwargs: Any) -> Any:
            delay = backoff
            last_exc: Exception | None = None
            # Attempt the original execute up to (max_retries + 1) times
            # with exponential backoff (delay doubles after each failure).
            for attempt in range(max_retries + 1):
                try:
                    return await original_execute(**kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        logger.debug(
                            "Retry %d/%d for tool '%s' after %.1fs",
                            attempt + 1,
                            max_retries,
                            tool.name,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        delay *= 2  # exponential backoff
            raise last_exc  # type: ignore[misc]

        tool.execute = _retrying_execute  # type: ignore[assignment]
        return tool

    return decorator
