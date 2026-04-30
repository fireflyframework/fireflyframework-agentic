# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""``firefly-mcp`` CLI — run the MCP server over stdio.

Spawned as a subprocess by clients like Claude Code, Claude Desktop, or
Cursor. The server enumerates the framework's tool registry and exposes
each tool over MCP.
"""

from __future__ import annotations

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
from fireflyframework_agentic.exposure.mcp.transports import run_stdio


def main() -> None:
    """Entry point registered as ``firefly-mcp`` in ``[project.scripts]``."""
    mcp = create_mcp_app()
    run_stdio(mcp)


if __name__ == "__main__":
    main()
