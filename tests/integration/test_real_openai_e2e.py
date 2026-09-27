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

"""Credential-gated live tests for OpenAI Chat Completions and Responses.

Run explicitly with a real OPENAI_API_KEY and ``-m nightly``. Model IDs are
overridable with FIREFLY_OPENAI_CHAT_MODEL and FIREFLY_OPENAI_RESPONSES_MODEL.
The Chat model must support function calling with reasoning effort ``none``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai import NativeOutput

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.memory.manager import MemoryManager
from fireflyframework_agentic.observability.usage import UsageTracker
from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec

_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
pytestmark = pytest.mark.skipif(
    not _KEY or _KEY.lower() in {"test", "dummy", "unused", "offline-test-key", "your-api-key"},
    reason="needs a real OPENAI_API_KEY",
)

LIVE_MODELS = [
    pytest.param(f"openai-chat:{os.environ.get('FIREFLY_OPENAI_CHAT_MODEL', 'gpt-6-luna')}", id="chat"),
    pytest.param(f"openai-responses:{os.environ.get('FIREFLY_OPENAI_RESPONSES_MODEL', 'gpt-6-luna')}", id="responses"),
]


@pytest.mark.nightly
@pytest.mark.asyncio
@pytest.mark.parametrize("model", LIVE_MODELS)
class TestRealOpenAIE2E:
    async def test_framework_tool_and_usage(self, model: str) -> None:
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

        tracker = UsageTracker()
        agent = FireflyAgent(
            "live-openai-tool",
            model=model,
            tools=[AddTool()],
            instructions="Always use the add tool for arithmetic, then state its result.",
            model_settings={"openai_reasoning_effort": "none", "max_tokens": 512},
            usage_tracker=tracker,
            auto_register=False,
        )
        result = await agent.run("Use the add tool to add 17 and 25.")
        assert calls and calls[0] == (17, 25)
        assert "42" in result.output
        (record,) = tracker.records
        assert record.input_tokens > 0 and record.output_tokens > 0
        assert record.request_count >= 2
        assert record.cost_usd > 0

    async def test_native_structured_output(self, model: str) -> None:
        class Person(BaseModel):
            name: str
            age: int

        agent = FireflyAgent(
            "live-openai-structured",
            model=model,
            output_type=NativeOutput(Person),
            model_settings={"openai_reasoning_effort": "none", "max_tokens": 512},
            auto_register=False,
        )
        result = await agent.run("Extract the person: Zara is 30 years old.")
        assert result.output == Person(name="Zara", age=30)

    async def test_streaming_memory_follow_up(self, model: str) -> None:
        memory = MemoryManager()
        agent = FireflyAgent(
            "live-openai-stream",
            model=model,
            memory=memory,
            model_settings={"openai_reasoning_effort": "none", "max_tokens": 512},
            auto_register=False,
        )
        async with await agent.run_stream(
            "My name is Zara. Greet me briefly.", conversation_id="live-stream"
        ) as stream:
            chunks = [chunk async for chunk in stream.stream_text(delta=True)]
        assert "zara" in "".join(chunks).lower()
        result = await agent.run("What is my name?", conversation_id="live-stream")
        assert "zara" in result.output.lower()
        assert len(memory.conversation.get_turns("live-stream")) == 2

    async def test_serialized_memory_follow_up(self, model: str) -> None:
        memory = MemoryManager()
        settings: dict[str, Any] = {"max_tokens": 1024, "openai_reasoning_effort": "none"}
        if model.startswith("openai-responses:"):
            settings.update(openai_store=False, openai_reasoning_effort="low")
        agent = FireflyAgent(
            "live-openai-memory",
            model=model,
            memory=memory,
            model_settings=settings,
            auto_register=False,
        )
        await agent.run("Remember: the project code is cobalt-42. Briefly acknowledge.", conversation_id="live")
        exported = json.loads(json.dumps(memory.conversation.export_conversation("live")))
        restored = MemoryManager()
        restored.conversation.import_conversation(exported)
        resumed = FireflyAgent(
            "live-openai-restored",
            model=model,
            memory=restored,
            model_settings=settings,
            auto_register=False,
        )
        result = await resumed.run("What is the project code?", conversation_id="live")
        assert "cobalt-42" in result.output.lower()
        assert len(restored.conversation.get_turns("live")) == 2
