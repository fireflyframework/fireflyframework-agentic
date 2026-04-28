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

"""Global tool registry for discovering and managing tools.

:class:`ToolRegistry` follows the same singleton pattern used by
:class:`~fireflyframework_agentic.agents.registry.AgentRegistry`.  Tools are
registered either explicitly via :meth:`ToolRegistry.register` or implicitly
through the :func:`~fireflyframework_agentic.tools.decorators.firefly_tool`
decorator.
"""

from __future__ import annotations

import logging
import threading

from fireflyframework_agentic.exceptions import ToolNotFoundError
from fireflyframework_agentic.tools.base import ToolInfo, ToolProtocol

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Central registry that holds references to all registered tools.

    Provides name-based and tag-based discovery.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolProtocol] = {}
        self._lock = threading.Lock()

    def register(self, tool: ToolProtocol) -> None:
        """Register *tool* under its :attr:`name`.

        An existing tool with the same name is silently replaced.
        """
        with self._lock:
            self._tools[tool.name] = tool
        logger.debug("Registered tool '%s'", tool.name)

    def get(self, name: str) -> ToolProtocol:
        """Return the tool registered under *name*.

        Raises:
            ToolNotFoundError: If no tool with *name* is registered.
        """
        with self._lock:
            try:
                return self._tools[name]
            except KeyError:
                raise ToolNotFoundError(f"No tool registered with name '{name}'") from None

    def get_by_tag(self, tag: str) -> list[ToolProtocol]:
        """Return all tools that carry *tag*."""
        with self._lock:
            return [t for t in self._tools.values() if hasattr(t, "tags") and tag in getattr(t, "tags", [])]

    def has(self, name: str) -> bool:
        """Return *True* if a tool with *name* is registered."""
        with self._lock:
            return name in self._tools

    def unregister(self, name: str) -> None:
        """Remove the tool registered under *name*.

        Raises:
            ToolNotFoundError: If no tool with *name* is registered.
        """
        with self._lock:
            if name not in self._tools:
                raise ToolNotFoundError(f"No tool registered with name '{name}'")
            del self._tools[name]
        logger.debug("Unregistered tool '%s'", name)

    def list_tools(self) -> list[ToolInfo]:
        """Return a :class:`ToolInfo` summary for every registered tool."""
        with self._lock:
            tools = list(self._tools.values())
        results: list[ToolInfo] = []
        for t in tools:
            if hasattr(t, "info"):
                results.append(t.info())  # type: ignore[union-attr]
            else:
                results.append(ToolInfo(name=t.name, description=t.description))
        return results

    def clear(self) -> None:
        """Remove all registered tools.  Primarily useful in tests."""
        with self._lock:
            self._tools.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._tools)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._tools


# Module-level singleton
tool_registry = ToolRegistry()
