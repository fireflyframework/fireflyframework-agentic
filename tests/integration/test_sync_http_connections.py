"""Actual HTTP/1.1 sockets expose loop-affinity bugs that MockTransport cannot."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.agents.base import _run_sync_coro
from fireflyframework_agentic.memory import MemoryManager
from tests.integration.test_openai_api_compatibility import _chat_response, _responses_response


@pytest.mark.parametrize("api", ["chat", "responses"])
@pytest.mark.parametrize("inside_event_loop", [False, True], ids=["script", "notebook"])
def test_repeated_sync_turns_reuse_a_real_keepalive_connection(api, inside_event_loop):
    requests = []
    connections = []
    accepted_sockets = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(2)
            accepted_sockets.append(self.connection)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            connections.append(self.client_address)
            response = _chat_response if api == "chat" else _responses_response
            payload = json.dumps(response("gpt-4o", f"turn {len(requests)}")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    http = httpx2.AsyncClient(trust_env=False)
    client = AsyncOpenAI(
        api_key="local-contract-test",
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        http_client=http,
        max_retries=0,
    )
    model_cls = OpenAIChatModel if api == "chat" else OpenAIResponsesModel
    agent = FireflyAgent(
        "socket-affinity",
        model=model_cls("gpt-4o", provider=OpenAIProvider(openai_client=client)),
        memory=MemoryManager(),
        auto_register=False,
        default_middleware=False,
    )

    def run():
        for turn in range(1, 4):
            assert agent.run_sync(f"request {turn}", conversation_id="same-chat").output == f"turn {turn}"

    try:
        if inside_event_loop:

            async def caller():
                run()

            asyncio.run(caller(), loop_factory=asyncio.new_event_loop)
        else:
            run()
        assert len(requests) == 3
        assert len(set(connections)) == 1
        assert {path for path, _ in requests} == {"/v1/chat/completions" if api == "chat" else "/v1/responses"}
        assert "request 1" in json.dumps(requests[2][1])
        assert len(agent.memory.conversation.get_turns("same-chat")) == 3
    finally:
        try:
            _run_sync_coro(client.close())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive()
            assert server.socket.fileno() == -1
            assert all(connection.fileno() == -1 for connection in accepted_sockets)
