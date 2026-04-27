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

"""Tool composition strategies: sequential piping, fallback, and conditional routing.

Composers let users build higher-order tools from existing tools.  Each
composer implements the :class:`ToolProtocol` so it can itself be registered
in a :class:`ToolRegistry` or nested inside other composers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from fireflyframework_agentic.exceptions import ToolError
from fireflyframework_agentic.tools.base import ToolProtocol

logger = logging.getLogger(__name__)


class SequentialComposer:
    """Execute tools in sequence, piping each output as the next tool's ``input`` kwarg.

    The first tool receives the original kwargs.  Subsequent tools receive a
    single keyword argument ``input`` set to the previous tool's return value.

    Parameters:
        name: Name for this composed tool.
        tools: Ordered sequence of tools to execute.
        description: Human-readable description.
    """

    def __init__(
        self,
        name: str,
        tools: Sequence[ToolProtocol],
        *,
        description: str = "",
    ) -> None:
        self._name = name
        self._tools = list(tools)
        self._description = description or f"Sequential composition of {len(tools)} tools"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, **kwargs: Any) -> Any:
        result: Any = None
        for i, tool in enumerate(self._tools):
            if i == 0:
                result = await tool.execute(**kwargs)
            else:
                result = await tool.execute(input=result)
        return result


class FallbackComposer:
    """Try each tool in order until one succeeds; raise if all fail.

    Parameters:
        name: Name for this composed tool.
        tools: Tools to try in priority order.
        description: Human-readable description.
    """

    def __init__(
        self,
        name: str,
        tools: Sequence[ToolProtocol],
        *,
        description: str = "",
    ) -> None:
        self._name = name
        self._tools = list(tools)
        self._description = description or f"Fallback composition of {len(tools)} tools"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for tool in self._tools:
            try:
                return await tool.execute(**kwargs)
            except Exception as exc:
                logger.debug("Fallback: tool '%s' failed (%s), trying next", tool.name, exc)
                last_error = exc
        raise ToolError(f"All {len(self._tools)} fallback tools failed; last error: {last_error}")


class ConditionalComposer:
    """Route to a specific tool based on a router function.

    The *router_fn* receives the kwargs and returns the name of the tool to
    invoke from *tool_map*.

    Parameters:
        name: Name for this composed tool.
        router_fn: A callable that selects which tool to use.
        tool_map: Mapping of names to tools.
        description: Human-readable description.
    """

    def __init__(
        self,
        name: str,
        router_fn: Callable[..., str],
        tool_map: dict[str, ToolProtocol],
        *,
        description: str = "",
    ) -> None:
        self._name = name
        self._router_fn = router_fn
        self._tool_map = dict(tool_map)
        self._description = description or f"Conditional router over {len(tool_map)} tools"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, **kwargs: Any) -> Any:
        selected = self._router_fn(**kwargs)
        if selected not in self._tool_map:
            raise ToolError(f"Router selected unknown tool '{selected}'")
        return await self._tool_map[selected].execute(**kwargs)
