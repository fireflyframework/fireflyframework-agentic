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

"""One Firefly application across providers, with only the HTTP boundary replaced."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.agents.builtin_middleware import CacheMiddleware
from fireflyframework_agentic.agents.cache import ResultCache
from fireflyframework_agentic.config import FireflyAgenticConfig, get_config, set_config
from fireflyframework_agentic.evaluation.judge import JudgeClient
from fireflyframework_agentic.memory import MemoryManager
from fireflyframework_agentic.models import ModelOptions, ModelOptionsError
from fireflyframework_agentic.tools import firefly_tool
from tests.integration.test_openai_api_compatibility import _chat_response, _HTTPBoundary, _responses_response

_MODELS = [
    pytest.param("openai-chat:gpt-6-sol", "none", id="chat"),
    pytest.param("openai-responses:gpt-6-luna", "low", id="responses"),
    pytest.param("anthropic:claude-sonnet-5", "low", id="anthropic"),
]


@pytest.fixture
def sampling_config():
    original = get_config()
    set_config(FireflyAgenticConfig(default_temperature=0.8))
    try:
        yield
    finally:
        set_config(original)


@pytest.mark.parametrize(
    "model,options,temperature",
    [
        ("openai-chat:gpt-4o", None, 0.0),
        ("openai-chat:gpt-6-sol", ModelOptions(reasoning="none"), 0.0),
        ("openai-responses:gpt-6-luna", None, None),
        ("anthropic:claude-sonnet-5", None, None),
    ],
)
@pytest.mark.filterwarnings("error:Sampling parameters.*:UserWarning")
async def test_judge_options_match_provider_capabilities(wire, model, options, temperature, sampling_config):
    class Verdict(BaseModel):
        verdict: str

    reply = _response(model, tool="final_result")
    payload = json.loads(reply.content)
    if model.startswith("openai-chat:"):
        payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"verdict":"supported"}'
    elif model.startswith("openai-responses:"):
        payload["output"][0]["arguments"] = '{"verdict":"supported"}'
    else:
        payload["content"][0]["input"] = {"verdict": "supported"}
    wire.replies = [httpx2.Response(200, json=payload)]
    kwargs = {"model_options": options} if options is not None else {}
    client = JudgeClient(model, **kwargs)
    verdict = await client.judge("Check the evidence.", "An observed fact.", Verdict, max_tokens=512)
    assert verdict.verdict == "supported"
    assert wire.body(0).get("temperature") == temperature
    if options is not None:
        assert wire.body(0)["reasoning_effort"] == "none"


def _application(
    model: str, reasoning: str, *, output_type: Any = str
) -> tuple[FireflyAgent, MemoryManager, list[tuple[int, int]]]:
    """Application code uses the same Firefly APIs for every configured model."""
    memory = MemoryManager()
    calls: list[tuple[int, int]] = []

    @firefly_tool("add", description="Add two integers.", auto_register=False)
    async def add(a: int, b: int) -> int:
        calls.append((a, b))
        return a + b

    agent = FireflyAgent(
        "portable-application",
        model=model,
        model_options=ModelOptions(max_tokens=512, reasoning=reasoning),
        tools=[add],
        memory=memory,
        output_type=output_type,
        auto_register=False,
    )
    return agent, memory, calls


@pytest.fixture
async def wire(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_HTTPBoundary]:
    boundary = _HTTPBoundary()
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")
    monkeypatch.setattr("pydantic_ai.providers._openai_compatible.create_async_httpx2_client", lambda: boundary.client)
    monkeypatch.setattr("pydantic_ai.providers.anthropic.create_async_httpx2_client", lambda: boundary.client)
    async with boundary.client:
        yield boundary


def _response(model: str, text: str | None = None, *, tool: str | None = None) -> httpx2.Response:
    provider, model_name = model.split(":", 1)
    if provider == "openai-chat":
        payload = _chat_response(model_name, text, tool=tool)
    elif provider == "openai-responses":
        payload = _responses_response(model_name, text, tool=tool)
    else:
        payload = {
            "id": "msg_portable",
            "type": "message",
            "role": "assistant",
            "model": model_name,
            "content": (
                [{"type": "tool_use", "id": "call_add", "name": tool, "input": {"a": 17, "b": 25}}]
                if tool
                else [{"type": "text", "text": text}]
            ),
            "stop_reason": "tool_use" if tool else "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 20, "output_tokens": 8},
        }
    return httpx2.Response(200, json=payload)


def _assert_wire_options(request: httpx2.Request, model: str, reasoning: str, max_tokens: int) -> None:
    body = json.loads(request.content)
    assert body["model"] == model.split(":", 1)[1]
    assert "temperature" not in body
    if model.startswith("openai-chat:"):
        assert request.url.path == "/v1/chat/completions"
        assert body["reasoning_effort"] == reasoning
        assert body["max_completion_tokens"] == max_tokens
        assert "thinking" not in body and "output_config" not in body and "reasoning" not in body
    elif model.startswith("openai-responses:"):
        assert request.url.path == "/v1/responses"
        assert body["reasoning"]["effort"] == reasoning
        assert body["max_output_tokens"] == max_tokens
        assert "thinking" not in body and "output_config" not in body and "reasoning_effort" not in body
    else:
        assert request.url.path == "/v1/messages"
        assert body["thinking"] == {"type": "adaptive"}
        assert body["output_config"]["effort"] == reasoning
        assert body["max_tokens"] == max_tokens
        assert "reasoning_effort" not in body and "reasoning" not in body


@pytest.mark.parametrize("model,reasoning", _MODELS)
async def test_same_application_runs_tools_and_remembers_history(
    wire: _HTTPBoundary, model: str, reasoning: str
) -> None:
    wire.replies = [_response(model, tool="add"), _response(model, "The sum is 42."), _response(model, "42")]
    agent, memory, calls = _application(model, reasoning)

    first = await agent.run("Add 17 and 25.", conversation_id="calculation")
    second = await agent.run("What was the sum?", conversation_id="calculation")

    assert first.output == "The sum is 42."
    assert second.output == "42"
    assert calls == [(17, 25)]
    assert len(memory.conversation.get_turns("calculation")) == 2
    assert len(wire.requests) == 3
    for request in wire.requests:
        _assert_wire_options(request, model, reasoning, 512)
    follow_up = wire.body(2)
    history = follow_up.get("messages", follow_up.get("input"))
    assert "Add 17 and 25." in json.dumps(history)
    assert "The sum is 42." in json.dumps(history)
    tool_result = wire.body(1)
    if model.startswith("openai-chat:"):
        returned = [item for item in tool_result["messages"] if item.get("role") == "tool"]
        assert returned[0]["tool_call_id"] == "call_add"
        assert returned[0]["content"] == "42"
    elif model.startswith("openai-responses:"):
        returned = [item for item in tool_result["input"] if item.get("type") == "function_call_output"]
        assert returned[0]["call_id"] == "call_add"
        assert returned[0]["output"] == "42"
    else:
        returned = [
            part
            for item in tool_result["messages"]
            if isinstance(item["content"], list)
            for part in item["content"]
            if part.get("type") == "tool_result"
        ]
        assert returned[0]["tool_use_id"] == "call_add"
        assert returned[0]["content"] == [{"type": "text", "text": "42"}]


@pytest.mark.parametrize("model,reasoning", _MODELS)
async def test_plain_pydantic_output_type_is_portable(wire: _HTTPBoundary, model: str, reasoning: str) -> None:
    class Person(BaseModel):
        name: str
        age: int

    reply = _response(model, tool="final_result")
    payload = json.loads(reply.content)
    if model.startswith("openai-chat:"):
        payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"name":"Zara","age":30}'
    elif model.startswith("openai-responses:"):
        payload["output"][0]["arguments"] = '{"name":"Zara","age":30}'
    else:
        payload["content"][0]["input"] = {"name": "Zara", "age": 30}
    wire.replies = [httpx2.Response(200, json=payload)]
    agent, _, calls = _application(model, reasoning, output_type=Person)

    result = await agent.run("Extract Zara, age 30.")

    assert result.output == Person(name="Zara", age=30)
    assert calls == []
    _assert_wire_options(wire.requests[0], model, reasoning, 512)


@pytest.mark.parametrize("at_construction", [True, False])
async def test_native_and_portable_options_validate_the_effective_wire_request(wire: _HTTPBoundary, at_construction):
    model = "openai-responses:gpt-6-sol"
    wire.replies = [_response(model, "Answer")]
    configuration = {
        "model_options": ModelOptions(temperature=0.2),
        "model_settings": {"openai_reasoning_effort": "none"},
    }
    agent = FireflyAgent("mixed", model=model, auto_register=False, **(configuration if at_construction else {}))
    await agent.run("Answer", **({} if at_construction else configuration))
    assert wire.body(0)["temperature"] == 0.2
    assert wire.body(0)["reasoning"]["effort"] == "none"


@pytest.mark.parametrize("with_seed", [True, False])
async def test_shared_cache_keeps_api_identity_and_option_validation(wire: _HTTPBoundary, with_seed):
    cache = ResultCache()
    options = ModelOptions(max_tokens=100, reasoning="none")
    agents = [
        FireflyAgent(
            "shared",
            model=f"{api}:gpt-6-sol",
            model_options=options,
            middleware=[CacheMiddleware(cache=cache)],
            auto_register=False,
        )
        for api in ["openai-chat", "openai-responses"]
    ]
    wire.replies = [_response("openai-chat:gpt-6-sol", "chat"), _response("openai-responses:gpt-6-sol", "responses")]
    override = ModelOptions(seed=7) if with_seed else ModelOptions()
    assert (await agents[0].run("same", model_options=override)).output == "chat"
    if with_seed:
        with pytest.raises(ModelOptionsError, match="seed"):
            await agents[1].run("same", model_options=override)
        assert len(wire.requests) == 1
    else:
        assert (await agents[1].run("same", model_options=override)).output == "responses"
        assert len(wire.requests) == 2


@pytest.mark.parametrize(
    "initial,initial_reasoning,alternate,alternate_reasoning",
    [
        pytest.param(
            "anthropic:claude-sonnet-5", "low", "openai-responses:gpt-6-luna", "medium", id="anthropic-to-responses"
        ),
        pytest.param(
            "openai-responses:gpt-6-luna", "low", "anthropic:claude-sonnet-5", "medium", id="responses-to-anthropic"
        ),
        pytest.param("anthropic:claude-sonnet-5", "low", "openai-chat:gpt-6-sol", "none", id="anthropic-to-chat"),
    ],
)
async def test_per_call_model_change_retranslates_portable_options(
    wire: _HTTPBoundary, initial: str, initial_reasoning: str, alternate: str, alternate_reasoning: str
) -> None:
    wire.replies = [_response(initial, "First"), _response(alternate, "Second"), _response(initial, "Third")]
    agent, _, _ = _application(initial, initial_reasoning)

    first = await agent.run("First request.")
    second = await agent.run(
        "Second request.", model=alternate, model_options=ModelOptions(max_tokens=768, reasoning=alternate_reasoning)
    )
    third = await agent.run("Third request.")

    assert [first.output, second.output, third.output] == ["First", "Second", "Third"]
    _assert_wire_options(wire.requests[0], initial, initial_reasoning, 512)
    _assert_wire_options(wire.requests[1], alternate, alternate_reasoning, 768)
    _assert_wire_options(wire.requests[2], initial, initial_reasoning, 512)
