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

"""ToolKit -- group related tools and manage them as a single unit.

A :class:`ToolKit` bundles several tools together so they can be registered
into (or removed from) a :class:`ToolRegistry` in one call.  It also
converts its tools into Pydantic AI ``Tool`` objects for direct injection
into a :class:`pydantic_ai.Agent`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai import Tool as PydanticTool

from fireflyframework_genai.tools.base import ToolProtocol
from fireflyframework_genai.tools.registry import ToolRegistry


class ToolKit:
    """A named group of tools that operates as a single unit.

    Parameters:
        name: A unique human-readable name for the toolkit.
        tools: The tools that belong to this toolkit.
        description: Free-form description for documentation.
        tags: Tags applied to the toolkit (tools retain their own tags too).
    """

    def __init__(
        self,
        name: str,
        tools: Sequence[ToolProtocol],
        *,
        description: str = "",
        tags: Sequence[str] = (),
    ) -> None:
        self._name = name
        self._tools = list(tools)
        self._description = description
        self._tags = list(tags)

    @property
    def name(self) -> str:
        """Toolkit name."""
        return self._name

    @property
    def description(self) -> str:
        """Free-form description."""
        return self._description

    @property
    def tags(self) -> list[str]:
        """Tags applied to the toolkit."""
        return self._tags

    @property
    def tools(self) -> list[ToolProtocol]:
        """The tools contained in this toolkit."""
        return list(self._tools)

    def register_all(self, registry: ToolRegistry) -> None:
        """Register every tool in this toolkit into *registry*."""
        for tool in self._tools:
            registry.register(tool)

    def unregister_all(self, registry: ToolRegistry) -> None:
        """Remove every tool in this toolkit from *registry*."""
        for tool in self._tools:
            if registry.has(tool.name):
                registry.unregister(tool.name)

    def as_pydantic_tools(self) -> list[PydanticTool[Any]]:
        """Convert each tool into a :class:`pydantic_ai.Tool`.

        This creates plain Pydantic AI tools whose handler delegates to the
        Firefly tool's :meth:`execute` method.  Useful for injecting a
        toolkit's tools directly into a :class:`pydantic_ai.Agent`.
        """
        pydantic_tools: list[PydanticTool[Any]] = []
        for tool in self._tools:
            pydantic_handler_fn = getattr(tool, "pydantic_handler", None)
            handler = pydantic_handler_fn() if pydantic_handler_fn is not None else tool.execute
            pydantic_tools.append(
                PydanticTool(
                    handler,
                    name=tool.name,
                    description=tool.description,
                )
            )
        return pydantic_tools

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolKit(name={self._name!r}, tools={len(self._tools)})"
