# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Model Context Protocol (MCP) exposure layer.

Wraps the framework's tool registry with a FastMCP server so any MCP client
(Claude Code, Claude Desktop, Claude.ai, Cursor, custom Pydantic AI agents)
can call into Firefly natively.
"""

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app

__all__ = ["create_mcp_app"]
