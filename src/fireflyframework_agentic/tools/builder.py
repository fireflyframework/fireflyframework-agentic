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

"""Fluent builder API for constructing tools programmatically.

The :class:`ToolBuilder` provides a step-by-step, chainable interface for
creating :class:`~fireflyframework_agentic.tools.base.BaseTool` instances
without subclassing::

    tool = (
        ToolBuilder("search")
        .description("Search the web for information")
        .parameter("query", "str", description="Search query", required=True)
        .guard(RateLimitGuard(max_calls=10, period_seconds=60))
        .handler(my_search_function)
        .build()
    )
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from fireflyframework_agentic.tools.base import BaseTool, GuardProtocol, ParameterSpec

# Type alias for an async handler function
AsyncHandler = Callable[..., Coroutine[Any, Any, Any]]


class _BuiltTool(BaseTool):
    """Concrete tool created by :class:`ToolBuilder`."""

    def __init__(
        self,
        name: str,
        handler: AsyncHandler,
        *,
        description: str = "",
        tags: Sequence[str] = (),
        guards: Sequence[GuardProtocol] = (),
        parameters: Sequence[ParameterSpec] = (),
    ) -> None:
        super().__init__(
            name,
            description=description,
            tags=tags,
            guards=guards,
            parameters=parameters,
        )
        self._handler = handler

    async def _execute(self, **kwargs: Any) -> Any:
        return await self._handler(**kwargs)


class ToolBuilder:
    """Fluent builder for constructing tools without subclassing.

    Every setter method returns *self* so calls can be chained.

    Parameters:
        name: The unique name for the tool being built.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._description = ""
        self._tags: list[str] = []
        self._guards: list[GuardProtocol] = []
        self._parameters: list[ParameterSpec] = []
        self._handler: AsyncHandler | None = None

    def description(self, desc: str) -> ToolBuilder:
        """Set the tool description."""
        self._description = desc
        return self

    def tag(self, tag: str) -> ToolBuilder:
        """Add a single tag."""
        self._tags.append(tag)
        return self

    def tags(self, tags: Sequence[str]) -> ToolBuilder:
        """Add multiple tags at once."""
        self._tags.extend(tags)
        return self

    def parameter(
        self,
        name: str,
        type_annotation: str,
        *,
        description: str = "",
        required: bool = True,
        default: Any = None,
    ) -> ToolBuilder:
        """Declare a parameter the tool accepts."""
        self._parameters.append(
            ParameterSpec(
                name=name,
                type_annotation=type_annotation,
                description=description,
                required=required,
                default=default,
            )
        )
        return self

    def guard(self, guard: GuardProtocol) -> ToolBuilder:
        """Append a guard to the tool's guard chain."""
        self._guards.append(guard)
        return self

    def handler(self, func: AsyncHandler) -> ToolBuilder:
        """Set the async handler function that implements the tool logic."""
        self._handler = func
        return self

    def build(self) -> BaseTool:
        """Build and return the tool.

        Raises:
            ValueError: If no handler has been set.
        """
        if self._handler is None:
            raise ValueError(f"ToolBuilder('{self._name}'): handler must be set before build()")
        return _BuiltTool(
            self._name,
            self._handler,
            description=self._description,
            tags=self._tags,
            guards=self._guards,
            parameters=self._parameters,
        )
