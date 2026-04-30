# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for the MCP exposure layer."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastmcp", reason="MCP tests require fastmcp")
pytest.importorskip("fastapi", reason="MCP HTTP transport requires fastapi")

from fastapi import FastAPI
from fastmcp import FastMCP

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
from fireflyframework_agentic.exposure.mcp.transports import mount_http, run_stdio
from fireflyframework_agentic.tools.builtins import DateTimeTool
from fireflyframework_agentic.tools.registry import ToolRegistry, tool_registry


@pytest.fixture
def fresh_registry() -> Iterator[ToolRegistry]:
    """Snapshot and restore the singleton tool_registry to isolate tests."""
    snapshot = dict(tool_registry._tools)
    tool_registry._tools.clear()
    yield tool_registry
    tool_registry._tools.clear()
    tool_registry._tools.update(snapshot)


def test_create_mcp_app_returns_fastmcp(fresh_registry: ToolRegistry) -> None:
    app = create_mcp_app()
    assert isinstance(app, FastMCP)


async def test_mcp_app_exposes_registered_tools(fresh_registry: ToolRegistry) -> None:
    fresh_registry.register(DateTimeTool())
    app = create_mcp_app()
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert "datetime" in names


async def test_mcp_app_propagates_tool_description(fresh_registry: ToolRegistry) -> None:
    tool = DateTimeTool()
    fresh_registry.register(tool)
    app = create_mcp_app()
    tools = await app.list_tools()
    by_name = {t.name: t for t in tools}
    assert by_name["datetime"].description == tool.description


async def test_mcp_app_invokes_registered_tool(fresh_registry: ToolRegistry) -> None:
    fresh_registry.register(DateTimeTool())
    app = create_mcp_app()
    result = await app.call_tool("datetime", {"action": "now", "timezone": "UTC"})
    assert result.content, "expected at least one content block"
    text = result.content[0].text  # type: ignore[union-attr]
    assert text and "2026" in text  # current year, smoke check on real call


def test_create_mcp_app_accepts_custom_registry() -> None:
    """An empty injected registry yields an MCP app with no tools."""
    custom = ToolRegistry()
    app = create_mcp_app(registry=custom)
    assert isinstance(app, FastMCP)


# --- transports -------------------------------------------------------------


def test_run_stdio_invokes_fastmcp_run(monkeypatch: pytest.MonkeyPatch) -> None:
    mcp = FastMCP("test")
    fake_run = MagicMock()
    monkeypatch.setattr(mcp, "run", fake_run)
    run_stdio(mcp)
    fake_run.assert_called_once_with(transport="stdio")


def test_mount_http_attaches_at_default_path() -> None:
    fastapi_app = FastAPI()
    mcp = FastMCP("test")
    mount_http(fastapi_app, mcp)
    paths = [r.path for r in fastapi_app.routes]
    assert "/mcp" in paths


def test_mount_http_attaches_at_custom_path() -> None:
    fastapi_app = FastAPI()
    mcp = FastMCP("test")
    mount_http(fastapi_app, mcp, path="/firefly-mcp")
    paths = [r.path for r in fastapi_app.routes]
    assert "/firefly-mcp" in paths


# --- CLI entry point --------------------------------------------------------


def test_cli_main_creates_app_and_runs_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = MagicMock()
    fake_create = MagicMock(return_value=fake_app)
    fake_run_stdio = MagicMock()
    monkeypatch.setattr(
        "fireflyframework_agentic.cli.mcp_server.create_mcp_app",
        fake_create,
    )
    monkeypatch.setattr(
        "fireflyframework_agentic.cli.mcp_server.run_stdio",
        fake_run_stdio,
    )

    from fireflyframework_agentic.cli.mcp_server import main

    main()
    fake_create.assert_called_once_with()
    fake_run_stdio.assert_called_once_with(fake_app)
