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

"""Plugin discovery system for the Firefly Agentic framework.

Third-party packages can register agents, tools, and reasoning patterns by
declaring entry points in their ``pyproject.toml``::

    [project.entry-points."fireflyframework_agentic.agents"]
    my_agent = "my_package.agents:MyAgent"

    [project.entry-points."fireflyframework_agentic.tools"]
    my_tool = "my_package.tools:MyTool"

    [project.entry-points."fireflyframework_agentic.reasoning_patterns"]
    my_pattern = "my_package.reasoning:MyPattern"

On startup, :meth:`PluginDiscovery.discover_all` scans these groups and loads
the referenced objects so they can self-register with their respective
registries.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Well-known entry-point group names
ENTRY_POINT_AGENTS = "fireflyframework_agentic.agents"
ENTRY_POINT_TOOLS = "fireflyframework_agentic.tools"
ENTRY_POINT_REASONING = "fireflyframework_agentic.reasoning_patterns"

ALL_GROUPS = (ENTRY_POINT_AGENTS, ENTRY_POINT_TOOLS, ENTRY_POINT_REASONING)


@dataclass
class DiscoveredPlugin:
    """Metadata about a single discovered plugin entry point."""

    group: str
    name: str
    value: str
    loaded_object: Any | None = None
    error: str | None = None


@dataclass
class DiscoveryResult:
    """Aggregated result of a plugin discovery scan."""

    plugins: list[DiscoveredPlugin] = field(default_factory=list)

    @property
    def successful(self) -> list[DiscoveredPlugin]:
        """Return plugins that were loaded without errors."""
        return [p for p in self.plugins if p.error is None]

    @property
    def failed(self) -> list[DiscoveredPlugin]:
        """Return plugins that failed to load."""
        return [p for p in self.plugins if p.error is not None]


class PluginDiscovery:
    """Discovers and loads plugins from Python entry points.

    This class is intentionally stateless -- discovery results are returned
    and the caller decides what to do with them (typically: register with the
    appropriate registry).
    """

    @staticmethod
    def discover_group(group: str) -> list[DiscoveredPlugin]:
        """Discover and load all entry points in *group*.

        Each entry point is loaded via its ``load()`` method.  If loading
        raises an exception the error is captured in
        :attr:`DiscoveredPlugin.error` rather than propagated, so that one
        broken plugin does not prevent the rest from loading.
        """
        results: list[DiscoveredPlugin] = []
        for ep in importlib.metadata.entry_points(group=group):
            plugin = DiscoveredPlugin(group=group, name=ep.name, value=ep.value)
            try:
                plugin.loaded_object = ep.load()
                logger.debug("Loaded plugin %s:%s -> %s", group, ep.name, ep.value)
            except Exception as exc:  # noqa: BLE001
                plugin.error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Failed to load plugin %s:%s -> %s: %s",
                    group,
                    ep.name,
                    ep.value,
                    plugin.error,
                )
            results.append(plugin)
        return results

    @classmethod
    def discover_all(cls) -> DiscoveryResult:
        """Discover and load plugins from all well-known entry-point groups.

        Returns a :class:`DiscoveryResult` containing every discovered plugin
        along with any load errors.
        """
        result = DiscoveryResult()
        for group in ALL_GROUPS:
            result.plugins.extend(cls.discover_group(group))
        logger.info(
            "Plugin discovery complete: %d loaded, %d failed",
            len(result.successful),
            len(result.failed),
        )
        return result
