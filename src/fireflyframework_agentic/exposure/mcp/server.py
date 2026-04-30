# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""FastMCP server factory for exposing the framework's tools over MCP."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from fireflyframework_agentic.tools.base import ToolProtocol
from fireflyframework_agentic.tools.registry import ToolRegistry, tool_registry

logger = logging.getLogger(__name__)


def create_mcp_app(
    *,
    name: str = "firefly",
    version: str = "0.1.0",
    registry: ToolRegistry | None = None,
) -> FastMCP:
    """Build a :class:`fastmcp.FastMCP` server exposing every registered tool.

    The registry is read once at construction time. To pick up tools
    registered later, build a fresh app.

    Parameters:
        name: MCP server name advertised to clients.
        version: Server version string.
        registry: Tool registry to enumerate. Defaults to the module-level
            singleton :data:`fireflyframework_agentic.tools.registry.tool_registry`.
    """
    del version  # FastMCP 3.x reads version from the server name; kept for API stability.
    mcp: FastMCP = FastMCP(name)
    reg = registry if registry is not None else tool_registry
    for info in reg.list_tools():
        tool = reg.get(info.name)
        _register_tool(mcp, tool)
    return mcp


def _register_tool(mcp: FastMCP, tool: ToolProtocol) -> None:
    handler_factory = getattr(tool, "pydantic_handler", None)
    if handler_factory is None:
        logger.warning(
            "Tool %r has no pydantic_handler(); skipping MCP registration "
            "(only BaseTool-derived tools are auto-exposed)",
            tool.name,
        )
        return
    handler = handler_factory()
    mcp.tool(name=tool.name, description=tool.description)(handler)
