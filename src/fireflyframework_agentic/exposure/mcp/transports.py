# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""MCP transports: stdio (local subprocess) and Streamable HTTP (mounted on FastAPI)."""

from __future__ import annotations

from fastapi import FastAPI
from fastmcp import FastMCP


def run_stdio(mcp: FastMCP) -> None:
    """Run ``mcp`` over stdio.

    Stdio is the transport Claude Code, Claude Desktop, and similar clients
    use to spawn an MCP server as a subprocess on the user's machine. No
    network, no auth — credentials come from the user's local environment
    (e.g. ``az login`` for Azure-backed tools).
    """
    mcp.run(transport="stdio")


def mount_http(fastapi_app: FastAPI, mcp: FastMCP, *, path: str = "/mcp") -> None:
    """Mount ``mcp`` onto ``fastapi_app`` at ``path`` over Streamable HTTP.

    The MCP server then shares the FastAPI app's lifecycle, middleware,
    and OpenTelemetry instrumentation — one container can serve REST and
    MCP from the same image.
    """
    sub = mcp.http_app(path="/")
    fastapi_app.mount(path, sub)
