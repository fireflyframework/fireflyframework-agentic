# Copyright 2026 Firefly Software Foundation
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

"""Firefly + Pydantic AI + OpenAI SDK contracts, with only HTTP replaced.

The transport returns API-shaped messages and server-sent events. No
provider methods, agent methods, framework tools, or memory methods are mocked.
All clients have a dummy credential and a transport that cannot access a network.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel
from pydantic_ai import NativeOutput
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.messages import NativeToolReturnPart
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.native_tools import WebSearchTool
from pydantic_ai.providers.openai import OpenAIProvider

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.fallback import FallbackModelWrapper, run_with_fallback
from fireflyframework_agentic.memory.manager import MemoryManager
from fireflyframework_agentic.models.factory import ModelFactory
from fireflyframework_agentic.models.spec import Credential, ModelSpec
from fireflyframework_agentic.observability.usage import UsageTracker
from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec
from fireflyframework_agentic.tools.toolkit import ToolKit

API_CASES = [
    pytest.param("chat", "gpt-6-sol", id="chat-sol"),
    pytest.param("chat", "gpt-6-luna", id="chat-luna"),
    pytest.param("responses", "gpt-6-astra", id="responses-astra"),
    pytest.param("responses", "gpt-6-sol", id="responses-sol"),
    pytest.param("responses", "gpt-6-luna", id="responses-luna"),
]


class _HTTPBoundary:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.replies: list[httpx2.Response] = []
        self.client = httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        assert self.replies, "Agent made an unexpected additional provider request"
        self.requests.append(request)
        return self.replies.pop(0)

    def body(self, index: int) -> dict[str, Any]:
        return json.loads(self.requests[index].content)

    def model(self, api: str, model_name: str) -> OpenAIChatModel | OpenAIResponsesModel:
        provider = OpenAIProvider(api_key="offline-test-key", http_client=self.client)
        model_class = OpenAIChatModel if api == "chat" else OpenAIResponsesModel
        return model_class(model_name, provider=provider)


@pytest.fixture
async def boundary() -> AsyncIterator[_HTTPBoundary]:
    boundary = _HTTPBoundary()
    async with boundary.client:
        yield boundary


def _chat_response(model: str, text: str | None = None, *, tool: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text, "refusal": None}
    if tool:
        message["tool_calls"] = [
            {"id": "call_add", "type": "function", "function": {"name": tool, "arguments": '{"a":17,"b":25}'}}
        ]
    return {
        "id": "chatcmpl_offline",
        "object": "chat.completion",
        "created": 1_790_000_000,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool else "stop"}],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 8,
            "total_tokens": 28,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }


def _responses_response(
    model: str, text: str | None = None, *, tool: str | None = None, reasoning: bool = False
) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    if reasoning:
        output.append(
            {
                "id": "rs_offline",
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "Retain the user's name."}],
                "encrypted_content": "offline-encrypted-reasoning",
                "status": "completed",
            }
        )
    if tool:
        output.append(
            {
                "id": "fc_add",
                "type": "function_call",
                "call_id": "call_add",
                "name": tool,
                "arguments": '{"a":17,"b":25}',
                "status": "completed",
            }
        )
    if text is not None:
        output.append(
            {
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
                "status": "completed",
            }
        )
    return {
        "id": "resp_offline",
        "object": "response",
        "created_at": 1_790_000_000,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 8,
            "total_tokens": 28,
            "input_tokens_details": {"cached_tokens": 4},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
    }


def _reply(api: str, model: str, text: str | None = None, *, tool: str | None = None) -> httpx2.Response:
    payload = _chat_response(model, text, tool=tool) if api == "chat" else _responses_response(model, text, tool=tool)
    return httpx2.Response(200, json=payload)


def _stream_reply(api: str, model: str) -> httpx2.Response:
    events: list[dict[str, Any]] = []
    if api == "chat":
        for delta in [{"role": "assistant", "content": ""}, {"content": "Hello"}, {"content": " Zara"}]:
            events.append(
                {
                    "id": "chatcmpl_stream",
                    "object": "chat.completion.chunk",
                    "created": 1_790_000_000,
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
            )
        events.append({**events[-1], "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        events.append({**events[-1], "choices": [], "usage": _chat_response(model)["usage"]})
    else:
        response = _responses_response(model, "Hello Zara")
        item = response["output"][0]
        events = [
            {
                "type": "response.created",
                "response": {**response, "status": "in_progress", "output": [], "usage": None},
            },
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**item, "content": [], "status": "in_progress"},
            },
            *[
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_offline",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": delta,
                    "logprobs": [],
                }
                for delta in ["Hello", " Zara"]
            ],
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": response},
        ]
        events = [{**event, "sequence_number": index} for index, event in enumerate(events)]
    wire = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    if api == "chat":
        wire += "data: [DONE]\n\n"
    return httpx2.Response(200, content=wire, headers={"content-type": "text/event-stream"})


@pytest.mark.parametrize(("api", "model_name"), API_CASES)
async def test_framework_tool_round_trip_and_usage(boundary: _HTTPBoundary, api: str, model_name: str) -> None:
    calls: list[tuple[int, int]] = []

    class AddTool(BaseTool):
        def __init__(self) -> None:
            super().__init__(
                "add",
                description="Add two integers.",
                parameters=[ParameterSpec(name="a", python_type=int), ParameterSpec(name="b", python_type=int)],
            )

        async def _execute(self, **kwargs: Any) -> int:
            calls.append((kwargs["a"], kwargs["b"]))
            return kwargs["a"] + kwargs["b"]

    boundary.replies = [_reply(api, model_name, tool="add"), _reply(api, model_name, "42")]
    tracker = UsageTracker()
    agent = FireflyAgent(
        "openai-tools",
        model=boundary.model(api, model_name),
        toolsets=[ToolKit("calculator", [AddTool()]).as_toolset()],
        model_settings={"openai_reasoning_effort": "none" if api == "chat" else "medium", "max_tokens": 256},
        usage_tracker=tracker,
        auto_register=False,
    )
    result = await agent.run("Add 17 and 25.")
    assert result.output == "42"
    assert calls == [(17, 25)]
    assert len(boundary.requests) == 2
    assert {request.url.path for request in boundary.requests} == {
        "/v1/chat/completions" if api == "chat" else "/v1/responses"
    }
    first, second = boundary.body(0), boundary.body(1)
    assert first["model"] == model_name
    if api == "chat":
        assert first["reasoning_effort"] == "none"
        assert first["max_completion_tokens"] == 256
        assert first["tools"][0]["function"]["name"] == "add"
        assert any(
            item.get("role") == "tool" and item["content"] == "42" and item["tool_call_id"] == "call_add"
            for item in second["messages"]
        )
    else:
        assert first["reasoning"]["effort"] == "medium"
        assert first["max_output_tokens"] == 256
        assert first["tools"][0]["name"] == "add"
        assert any(
            item.get("type") == "function_call_output" and item["output"] == "42" and item["call_id"] == "call_add"
            for item in second["input"]
        )
    (record,) = tracker.records
    assert record.model == f"openai:{model_name}"
    assert (record.input_tokens, record.output_tokens, record.request_count, record.cache_read_tokens) == (40, 16, 2, 8)
    assert record.total_tokens == 56


@pytest.mark.parametrize(("api", "model_name"), API_CASES)
async def test_native_structured_output(boundary: _HTTPBoundary, api: str, model_name: str) -> None:
    class Person(BaseModel):
        name: str
        age: int

    boundary.replies = [_reply(api, model_name, '{"name":"Zara","age":30}')]
    agent = FireflyAgent(
        "openai-structured",
        model=boundary.model(api, model_name),
        output_type=NativeOutput(Person),
        auto_register=False,
    )
    result = await agent.run("Extract Zara, age 30.")
    assert result.output == Person(name="Zara", age=30)
    body = boundary.body(0)
    output_format = body["response_format"] if api == "chat" else body["text"]["format"]
    assert output_format["type"] == "json_schema"
    schema = output_format["json_schema"]["schema"] if api == "chat" else output_format["schema"]
    assert set(schema["required"]) == {"name", "age"}
    assert schema["properties"]["age"]["type"] == "integer"


@pytest.mark.parametrize(("api", "model_name"), API_CASES)
@pytest.mark.parametrize("streaming_mode", ["buffered", "incremental"])
async def test_streaming_persists_memory_and_usage(
    boundary: _HTTPBoundary, api: str, model_name: str, streaming_mode: str
) -> None:
    boundary.replies = [_stream_reply(api, model_name)]
    tracker, memory = UsageTracker(), MemoryManager()
    agent = FireflyAgent(
        "openai-stream",
        model=boundary.model(api, model_name),
        memory=memory,
        usage_tracker=tracker,
        auto_register=False,
    )
    async with await agent.run_stream(
        "My name is Zara.", conversation_id="stream", streaming_mode=streaming_mode
    ) as stream:
        chunks = [
            part
            async for part in (
                stream.stream_tokens() if streaming_mode == "incremental" else stream.stream_text(delta=True)
            )
        ]
    assert "".join(chunks) == "Hello Zara"
    assert boundary.body(0)["stream"] is True
    (record,) = tracker.records
    assert (record.input_tokens, record.output_tokens, record.request_count) == (20, 8, 1)
    turns = memory.conversation.get_turns("stream")
    assert len(turns) == 1
    turn = turns[0]
    assert turn.user_prompt == "My name is Zara."
    assert turn.assistant_response == "Hello Zara"
    assert len(memory.get_message_history("stream")) == 2
    boundary.replies = [_reply(api, model_name, "Zara")]
    follow_up = await agent.run("What is my name?", conversation_id="stream")
    assert follow_up.output == "Zara"
    history = boundary.body(1)["messages" if api == "chat" else "input"]
    assert "My name is Zara." in json.dumps(history)
    assert "Hello Zara" in json.dumps(history)
    assert len(memory.conversation.get_turns("stream")) == 2


@pytest.mark.parametrize(("api", "model_name"), [API_CASES[0], API_CASES[2]])
@pytest.mark.parametrize("streaming_mode", ["buffered", "incremental"])
async def test_failed_stream_does_not_persist_a_completed_turn(
    boundary: _HTTPBoundary, api: str, model_name: str, streaming_mode: str
) -> None:
    boundary.replies = [_stream_reply(api, model_name)]
    memory, tracker = MemoryManager(), UsageTracker()
    agent = FireflyAgent(
        "openai-interrupted-stream",
        model=boundary.model(api, model_name),
        memory=memory,
        usage_tracker=tracker,
        auto_register=False,
    )
    with pytest.raises(RuntimeError, match="consumer stopped"):
        async with await agent.run_stream(
            "Remember Zara.", conversation_id="failed", streaming_mode=streaming_mode
        ) as stream:
            async for _ in stream.stream_text(delta=True):
                raise RuntimeError("consumer stopped")
    assert memory.conversation.get_turns("failed") == []
    assert tracker.records == []


@pytest.mark.parametrize(("api", "model_name"), [API_CASES[0], API_CASES[2]])
@pytest.mark.parametrize("streaming_mode", ["buffered", "incremental"])
async def test_unconsumed_stream_does_not_persist_a_completed_turn(
    boundary: _HTTPBoundary, api: str, model_name: str, streaming_mode: str
) -> None:
    boundary.replies = [_stream_reply(api, model_name)]
    memory = MemoryManager()
    agent = FireflyAgent(
        "openai-abandoned-stream",
        model=boundary.model(api, model_name),
        memory=memory,
        auto_register=False,
    )
    async with await agent.run_stream(
        "Remember Zara.", conversation_id="partial", streaming_mode=streaming_mode
    ) as stream:
        async for _ in stream.stream_text(delta=True, debounce_by=None):
            break
    assert not stream.is_complete
    assert memory.conversation.get_turns("partial") == []


@pytest.mark.parametrize(("api", "model_name"), API_CASES)
async def test_exported_memory_replays_provider_state(boundary: _HTTPBoundary, api: str, model_name: str) -> None:
    payload = (
        _chat_response(model_name, "Hello Zara")
        if api == "chat"
        else _responses_response(model_name, "Hello Zara", reasoning=True)
    )
    boundary.replies = [httpx2.Response(200, json=payload), _reply(api, model_name, "Your name is Zara.")]
    memory = MemoryManager()
    settings = {"openai_store": False, "openai_send_reasoning_ids": True} if api == "responses" else {}
    agent = FireflyAgent(
        "openai-memory",
        model=boundary.model(api, model_name),
        memory=memory,
        model_settings=settings,
        auto_register=False,
    )
    await agent.run("My name is Zara.", conversation_id="original")
    exported = json.loads(json.dumps(memory.conversation.export_conversation("original")))
    restored = MemoryManager()
    restored.conversation.import_conversation(exported, conversation_id="restored")
    resumed = FireflyAgent(
        "openai-restored",
        model=boundary.model(api, model_name),
        memory=restored,
        model_settings=settings,
        auto_register=False,
    )
    result = await resumed.run("What is my name?", conversation_id="restored")
    assert result.output == "Your name is Zara."
    assert len(restored.conversation.get_turns("restored")) == 2
    body = boundary.body(1)
    if api == "chat":
        assert [(item["role"], item["content"]) for item in body["messages"]] == [
            ("user", "My name is Zara."),
            ("assistant", "Hello Zara"),
            ("user", "What is my name?"),
        ]
    else:
        assert body["store"] is False
        assert "reasoning.encrypted_content" in body["include"]
        (reasoning,) = [item for item in body["input"] if item.get("type") == "reasoning"]
        assert reasoning["id"] == "rs_offline"
        assert reasoning["encrypted_content"] == "offline-encrypted-reasoning"
        assert reasoning["summary"] == [{"type": "summary_text", "text": "Retain the user's name."}]
        assert any(item.get("id") == "msg_offline" for item in body["input"])
        assert "My name is Zara." in json.dumps(body["input"])
        assert "What is my name?" in json.dumps(body["input"])


async def test_responses_native_search_capability(boundary: _HTTPBoundary) -> None:
    payload = _responses_response("gpt-6-astra", "The current documentation is available.")
    payload["output"].insert(
        0,
        {
            "id": "ws_offline",
            "type": "web_search_call",
            "status": "completed",
            "action": {"type": "search", "query": "OpenAI documentation", "sources": []},
        },
    )
    boundary.replies = [httpx2.Response(200, json=payload)]
    agent = FireflyAgent(
        "openai-native-search",
        model=boundary.model("responses", "gpt-6-astra"),
        capabilities=[NativeTool(WebSearchTool(search_context_size="low", allowed_domains=["openai.com"]))],
        auto_register=False,
    )
    result = await agent.run("Find the current OpenAI documentation.")
    assert result.output == "The current documentation is available."
    (tool,) = boundary.body(0)["tools"]
    assert tool["type"] == "web_search"
    assert tool["search_context_size"] == "low"
    assert tool["filters"]["allowed_domains"] == ["openai.com"]
    assert any(isinstance(part, NativeToolReturnPart) for message in result.all_messages() for part in message.parts)


@pytest.mark.parametrize(
    "provider,api", [("openai", "chat"), ("openai-chat", "chat"), ("openai-responses", "responses")]
)
@pytest.mark.parametrize("construction", ["string", "factory"])
@pytest.mark.parametrize("model_name", ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna"])
async def test_explicit_api_selection_reaches_expected_endpoint(
    boundary: _HTTPBoundary,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    api: str,
    construction: str,
    model_name: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setattr("pydantic_ai.providers._openai_compatible.create_async_httpx2_client", lambda: boundary.client)
    boundary.replies = [_reply(api, model_name, "Ready")]
    if construction == "factory":
        model = await ModelFactory().build(
            ModelSpec(provider=provider, model=model_name, credential=Credential.api_key("offline-test-key"))
        )
    else:
        model = f"{provider}:{model_name}"
    agent = FireflyAgent("api-selection", model=model, auto_register=False)
    result = await agent.run("Confirm readiness.")
    assert result.output == "Ready"
    (request,) = boundary.requests
    assert request.url.path == ("/v1/chat/completions" if api == "chat" else "/v1/responses")
    assert boundary.body(0)["model"] == model_name


@pytest.mark.parametrize(("provider", "api"), [("openai", "chat"), ("openai-responses", "responses")])
async def test_fallback_preserves_api_and_restores_primary(boundary, monkeypatch, provider, api):
    from pydantic_ai.models.function import FunctionModel

    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setattr("pydantic_ai.providers._openai_compatible.create_async_httpx2_client", lambda: boundary.client)

    def unavailable(messages, info):
        raise RuntimeError("primary unavailable")

    primary = FunctionModel(unavailable)
    fallback = FallbackModelWrapper(models=[primary, f"{provider}:gpt-4o"])
    boundary.replies = [_reply(api, "gpt-4o", "Recovered")]
    agent = FireflyAgent("fallback-api", model=primary, auto_register=False)
    result = await run_with_fallback(agent, "Hello", fallback)
    assert result.output == "Recovered"
    assert boundary.requests[0].url.path == ("/v1/chat/completions" if api == "chat" else "/v1/responses")
    assert agent.agent.model is primary
    assert fallback.current is primary


@pytest.mark.parametrize(("first_api", "second_api"), [("chat", "responses"), ("responses", "chat")])
async def test_per_call_model_override_reuses_history_across_apis(boundary, first_api, second_api):
    boundary.replies = [
        _reply(first_api, "gpt-4o", "Hello Zara"),
        _reply(second_api, "gpt-4o", "Your name is Zara"),
    ]
    memory = MemoryManager()
    agent = FireflyAgent("switch-api", model=boundary.model(first_api, "gpt-4o"), memory=memory, auto_register=False)
    await agent.run("My name is Zara", conversation_id="switch")
    result = await agent.run("What is my name?", model=boundary.model(second_api, "gpt-4o"), conversation_id="switch")
    assert result.output == "Your name is Zara"
    assert boundary.requests[1].url.path == ("/v1/chat/completions" if second_api == "chat" else "/v1/responses")
    body = boundary.body(1)
    assert "My name is Zara" in json.dumps(body["messages" if second_api == "chat" else "input"])
    assert len(memory.conversation.get_turns("switch")) == 2


async def test_rubric_grader_preserves_responses_model_and_client(boundary, monkeypatch):
    from fireflyframework_agentic.validation.reviewer import RubricReviewer

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    boundary.replies = [
        _reply("responses", "gpt-6-sol", "Hello Zara"),
        _reply("responses", "gpt-6-sol", "SATISFIED"),
    ]
    agent = FireflyAgent("reviewed", model=boundary.model("responses", "gpt-6-sol"), auto_register=False)
    result = await RubricReviewer(["Greet Zara"]).review(agent, "Greet Zara")
    assert result.output == "Hello Zara"
    assert [request.url.path for request in boundary.requests] == ["/v1/responses", "/v1/responses"]
