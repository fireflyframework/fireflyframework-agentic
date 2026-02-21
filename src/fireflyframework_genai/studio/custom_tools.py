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

"""Persistence and runtime loading for user-defined custom tools.

Custom tools are stored as JSON definitions under
``~/.firefly-studio/custom_tools/``.  Three tool types are supported:

* **python** – A Python file on disk loaded via :mod:`importlib`.
* **webhook** – An HTTP endpoint called at runtime.
* **api** – A structured API call with configurable auth.

The :class:`CustomToolManager` handles CRUD and converts definitions into
live :class:`~fireflyframework_genai.tools.base.BaseTool` instances that
can be registered with the global tool registry.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fireflyframework_genai.tools.decorators import _DecoratedTool
from fireflyframework_genai.tools.registry import tool_registry

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """A single parameter accepted by a custom tool."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None


@dataclass
class CustomToolDefinition:
    """Serializable definition of a user-created custom tool."""

    name: str
    description: str = ""
    tool_type: str = "python"  # python | webhook | api
    tags: list[str] = field(default_factory=list)
    parameters: list[ToolParameter] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    # -- Python tool fields --
    module_path: str = ""  # path to .py file with an async `run` function

    # -- Webhook tool fields --
    webhook_url: str = ""
    webhook_method: str = "POST"
    webhook_headers: dict[str, str] = field(default_factory=dict)

    # -- API tool fields --
    api_base_url: str = ""
    api_path: str = ""
    api_method: str = "GET"
    api_auth_type: str = ""  # bearer | api_key | none
    api_auth_value: str = ""
    api_headers: dict[str, str] = field(default_factory=dict)


class CustomToolManager:
    """Manage custom tool definitions stored as JSON on disk.

    Parameters
    ----------
    base_dir:
        Root directory for custom tool storage.  Defaults to
        ``~/.firefly-studio/custom_tools``.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = (
            base_dir or Path.home() / ".firefly-studio" / "custom_tools"
        ).resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, name: str) -> Path:
        resolved = (self._base_dir / f"{name}.json").resolve()
        if not str(resolved).startswith(str(self._base_dir)):
            raise ValueError(f"Invalid tool name: {name}")
        return resolved

    # -- CRUD ---------------------------------------------------------------

    def save(self, definition: CustomToolDefinition) -> None:
        """Persist a tool definition to disk."""
        now = datetime.now(UTC).isoformat()
        if not definition.created_at:
            definition.created_at = now
        definition.updated_at = now

        path = self._safe_path(definition.name)
        data = asdict(definition)
        path.write_text(json.dumps(data, indent=2))
        logger.info("Saved custom tool '%s' to %s", definition.name, path)

    def load(self, name: str) -> CustomToolDefinition:
        """Load a tool definition by name."""
        path = self._safe_path(name)
        if not path.is_file():
            raise FileNotFoundError(f"Custom tool '{name}' not found")
        data = json.loads(path.read_text())
        params = [ToolParameter(**p) for p in data.pop("parameters", [])]
        return CustomToolDefinition(**data, parameters=params)

    def list_all(self) -> list[CustomToolDefinition]:
        """Return all saved tool definitions."""
        tools: list[CustomToolDefinition] = []
        for path in sorted(self._base_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                params = [ToolParameter(**p) for p in data.pop("parameters", [])]
                tools.append(CustomToolDefinition(**data, parameters=params))
            except Exception as exc:
                logger.warning("Skipping invalid tool file %s: %s", path, exc)
        return tools

    def delete(self, name: str) -> None:
        """Remove a tool definition from disk."""
        path = self._safe_path(name)
        if not path.is_file():
            raise FileNotFoundError(f"Custom tool '{name}' not found")
        path.unlink()
        # Also unregister from the global registry if loaded
        if tool_registry.has(f"custom:{name}"):
            tool_registry.unregister(f"custom:{name}")
        logger.info("Deleted custom tool '%s'", name)

    # -- Runtime tool creation ----------------------------------------------

    def create_runtime_tool(
        self, definition: CustomToolDefinition
    ) -> _DecoratedTool:
        """Convert a definition into a live BaseTool instance."""
        tool_name = f"custom:{definition.name}"

        if definition.tool_type == "python":
            handler = self._make_python_handler(definition)
        elif definition.tool_type == "webhook":
            handler = self._make_webhook_handler(definition)
        elif definition.tool_type == "api":
            handler = self._make_api_handler(definition)
        else:
            raise ValueError(f"Unknown tool type: {definition.tool_type}")

        return _DecoratedTool(
            tool_name,
            handler,
            description=definition.description,
            tags=["custom", *definition.tags],
        )

    def _make_python_handler(self, definition: CustomToolDefinition):
        """Load an async ``run`` function from a Python file on disk."""
        module_path = Path(definition.module_path).resolve()
        if not module_path.is_file():
            raise FileNotFoundError(
                f"Python module not found: {definition.module_path}"
            )

        spec = importlib.util.spec_from_file_location(
            f"custom_tool_{definition.name}", module_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {module_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        run_fn = getattr(module, "run", None)
        if run_fn is None:
            raise AttributeError(
                f"Module {module_path} must define an async 'run' function"
            )
        return run_fn

    def _make_webhook_handler(self, definition: CustomToolDefinition):
        """Create a handler that calls an HTTP webhook."""

        async def webhook_handler(**kwargs: Any) -> str:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(
                    method=definition.webhook_method,
                    url=definition.webhook_url,
                    headers=definition.webhook_headers,
                    json=kwargs,
                )
                response.raise_for_status()
                return response.text

        webhook_handler.__doc__ = definition.description
        return webhook_handler

    def _make_api_handler(self, definition: CustomToolDefinition):
        """Create a handler that calls a structured API endpoint."""

        async def api_handler(**kwargs: Any) -> str:
            import httpx

            headers = dict(definition.api_headers)
            if definition.api_auth_type == "bearer":
                headers["Authorization"] = f"Bearer {definition.api_auth_value}"
            elif definition.api_auth_type == "api_key":
                headers["X-API-Key"] = definition.api_auth_value

            url = f"{definition.api_base_url.rstrip('/')}/{definition.api_path.lstrip('/')}"
            async with httpx.AsyncClient(timeout=30) as client:
                if definition.api_method.upper() in ("POST", "PUT", "PATCH"):
                    response = await client.request(
                        method=definition.api_method,
                        url=url,
                        headers=headers,
                        json=kwargs,
                    )
                else:
                    response = await client.request(
                        method=definition.api_method,
                        url=url,
                        headers=headers,
                        params=kwargs,
                    )
                response.raise_for_status()
                return response.text

        api_handler.__doc__ = definition.description
        return api_handler

    # -- Bulk registration --------------------------------------------------

    def register_all(self) -> int:
        """Load all saved tools and register them in the global registry.

        Returns the number of tools successfully registered.
        """
        count = 0
        for definition in self.list_all():
            try:
                tool = self.create_runtime_tool(definition)
                tool_registry.register(tool)
                count += 1
                logger.info("Registered custom tool '%s'", tool.name)
            except Exception as exc:
                logger.warning(
                    "Failed to register custom tool '%s': %s",
                    definition.name,
                    exc,
                )
        return count
