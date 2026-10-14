# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0

"""Native MCP toolsets use real local transports without a provider or Docker."""

from __future__ import annotations

import asyncio
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from mcp.server import MCPServer
from pydantic_ai import ModelRetry
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from fireflyframework_agentic.agents.base import FireflyAgent


def _server(lifecycle: Path) -> MCPServer:
    @asynccontextmanager
    async def lifespan(server):
        with lifecycle.open("a") as stream:
            stream.write("started\n")
        try:
            yield
        finally:
            with lifecycle.open("a") as stream:
                stream.write("stopped\n")

    server = MCPServer("agentic-compatibility", lifespan=lifespan)

    @server.tool()
    def add(left: int, right: int) -> dict[str, int]:
        """Add two integers."""
        return {"sum": left + right}

    @server.tool()
    def fail() -> str:
        """Return a recoverable tool error."""
        raise ValueError("intentional local tool failure")

    return server


@pytest.fixture(params=["stdio", "http-modern", "http-legacy"])
async def mcp_toolset(request, tmp_path):
    lifecycle = tmp_path / "lifecycle.txt"
    if request.param == "stdio":
        client = Client(
            StdioTransport(
                command=sys.executable,
                args=[str(Path(__file__).resolve()), str(lifecycle)],
                keep_alive=False,
            ),
            timeout=5,
        )
        toolset = MCPToolset(client)
        try:
            yield toolset
        finally:
            await client.close()
            events = lifecycle.read_text().splitlines()
            assert events.count("started") == events.count("stopped") >= 1
        return

    server = _server(lifecycle)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    http = uvicorn.Server(uvicorn.Config(server.streamable_http_app(), log_level="error", ws="none"))
    client = Client(
        StreamableHttpTransport(f"http://127.0.0.1:{port}/mcp"),
        mode="2026-07-28" if request.param == "http-modern" else "legacy",
        timeout=5,
    )
    task = asyncio.create_task(http.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not http.started:
                if task.done():
                    await task
                    pytest.fail("Local MCP HTTP server stopped during startup")
                await asyncio.sleep(0.01)
        yield MCPToolset(client)
    finally:
        await client.close()
        http.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=10)
        finally:
            sock.close()
        assert lifecycle.read_text().splitlines() == ["started", "stopped"]


async def test_mcp_transport_discovers_calls_closes_and_reconnects(mcp_toolset):
    async with asyncio.timeout(20):
        for _ in range(2):
            async with mcp_toolset:
                assert mcp_toolset.is_running
                tools = {tool.name: tool for tool in await mcp_toolset.list_tools()}
                assert set(tools) == {"add", "fail"}
                assert tools["add"].input_schema["required"] == ["left", "right"]
                assert await mcp_toolset.direct_call_tool("add", {"left": 19, "right": 23}) == {"sum": 42}
            assert not mcp_toolset.is_running
            assert not mcp_toolset.client.is_connected()


async def test_mcp_tool_error_preserves_session_and_closes(mcp_toolset):
    async with asyncio.timeout(20):
        async with mcp_toolset:
            with pytest.raises(ModelRetry, match="Error executing tool fail"):
                await mcp_toolset.direct_call_tool("fail", {})
            assert await mcp_toolset.direct_call_tool("add", {"left": 1, "right": 2}) == {"sum": 3}
        assert not mcp_toolset.is_running
        assert not mcp_toolset.client.is_connected()


async def test_firefly_agent_runs_native_mcp_tool_and_owns_client_lifecycle(mcp_toolset):
    observed = []

    def model(messages, info):
        assert {tool.name for tool in info.function_tools} == {"add", "fail"}
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("add", {"left": 8, "right": 13}, tool_call_id="local-call")])
        observed.append(returns[-1].content)
        return ModelResponse(parts=[TextPart("sum=21")])

    agent = FireflyAgent(
        name="native-mcp-compatibility",
        model=FunctionModel(model),
        toolsets=[mcp_toolset],
        default_middleware=False,
        auto_register=False,
    )
    async with asyncio.timeout(20):
        result = await agent.run("Add eight and thirteen using the local MCP tool.")
    assert result.output == "sum=21"
    assert observed == [{"sum": 21}]
    assert not mcp_toolset.is_running
    assert not mcp_toolset.client.is_connected()


if __name__ == "__main__":
    _server(Path(sys.argv[1])).run(transport="stdio")
