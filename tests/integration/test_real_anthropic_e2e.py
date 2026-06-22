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

"""Live end-to-end tests against a real Anthropic model.

These exercise the whole framework against a real provider — agent + tools,
structured output, streaming, multi-turn memory, a reasoning pattern, a
pipeline, a Dynamic Workflow (FireflyAgentRunner + ``using=``), and real cost
tracking — to give confidence the framework is rock-solid end to end, not just
against mocks.

They are ``@pytest.mark.nightly`` (excluded from the PR gate) and skip unless a
**real** ``ANTHROPIC_API_KEY`` is present (conftest sets the value to ``"test"``
for offline runs). Run with::

    ANTHROPIC_API_KEY=sk-ant-... uv run pytest tests/integration/test_real_anthropic_e2e.py -m nightly
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.memory.manager import MemoryManager
from fireflyframework_agentic.observability.usage import UsageTracker
from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.steps import AgentStep
from fireflyframework_agentic.reasoning.chain_of_thought import ChainOfThoughtPattern
from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec
from fireflyframework_agentic.tools.toolkit import ToolKit
from fireflyframework_agentic.workflows import FireflyAgentRunner, agent, workflow

_KEY = os.environ.get("ANTHROPIC_API_KEY", "test")
pytestmark = pytest.mark.skipif(
    _KEY in ("", "test"), reason="needs a real ANTHROPIC_API_KEY (conftest defaults it to 'test')"
)

HAIKU = "anthropic:claude-haiku-4-5"


@pytest.mark.nightly
@pytest.mark.asyncio
class TestRealAnthropicE2E:
    """The framework, end to end, against a live Anthropic model."""

    async def test_agent_tool_round_trip(self):
        """The model calls a Firefly tool with the right args and uses the result."""
        calls: list[tuple[int, int]] = []

        class AddTool(BaseTool):
            def __init__(self) -> None:
                super().__init__(
                    "add",
                    description="Add two integers and return the sum.",
                    parameters=[
                        ParameterSpec(name="a", python_type=int),
                        ParameterSpec(name="b", python_type=int),
                    ],
                )

            async def _execute(self, **kwargs: Any) -> int:
                calls.append((int(kwargs["a"]), int(kwargs["b"])))
                return int(kwargs["a"]) + int(kwargs["b"])

        ag = FireflyAgent(
            "e2e-tool",
            model=HAIKU,
            toolsets=[ToolKit("calc", [AddTool()]).as_toolset()],
            instructions="Use the add tool for any arithmetic, then state the numeric result.",
            auto_register=False,
        )
        res = await ag.run("What is 17 plus 25? Use the add tool.")
        assert calls and calls[0] == (17, 25)  # tool called with the correct, real args
        assert "42" in str(res.output)

    async def test_structured_output(self):
        """``output_type`` constrains a real model to a validated pydantic model."""

        class Person(BaseModel):
            name: str
            age: int

        ag = FireflyAgent("e2e-struct", model=HAIKU, output_type=Person, auto_register=False)
        res = await ag.run("Extract the person: Alice is 30 years old.")
        assert isinstance(res.output, Person)
        assert res.output.name == "Alice"
        assert res.output.age == 30

    async def test_streaming(self):
        """Token streaming yields deltas that reassemble into the full answer."""
        ag = FireflyAgent("e2e-stream", model=HAIKU, auto_register=False)
        chunks: list[str] = []
        async with await ag.run_stream("Count from one to five in words, space separated.") as stream:
            async for delta in stream.stream_text(delta=True):
                chunks.append(delta)
        assert chunks
        assert "five" in "".join(chunks).lower()

    async def test_memory_multi_turn(self):
        """Conversation memory carries context across turns on a real model."""
        memory = MemoryManager()
        ag = FireflyAgent("e2e-mem", model=HAIKU, memory=memory, auto_register=False)
        cid = "e2e-conv"
        await ag.run("My name is Zara. Please remember it.", conversation_id=cid)
        res = await ag.run("What is my name?", conversation_id=cid)
        assert "zara" in str(res.output).lower()
        assert len(memory.get_message_history(cid)) >= 2

    async def test_reasoning_chain_of_thought(self):
        """A reasoning pattern drives a real model to a correct multi-step answer."""
        ag = FireflyAgent("e2e-reason", model=HAIKU, auto_register=False)
        pattern = ChainOfThoughtPattern(max_steps=4)
        result = await pattern.execute(
            ag, "A train travels 60 km in 1.5 hours. What is its average speed in km/h? Answer with the number."
        )
        assert result.steps_taken >= 1
        assert "40" in str(result.output)

    async def test_reasoning_prompted_output_mode(self):
        """The 'prompted' output mode drives a real model through prompt-engineered
        JSON (not tool-calling) and still produces validated structured steps."""
        ag = FireflyAgent("e2e-reason-prompted", model=HAIKU, auto_register=False)
        pattern = ChainOfThoughtPattern(max_steps=4, output_mode="prompted")
        result = await pattern.execute(
            ag, "A train travels 90 km in 1.5 hours. What is its average speed in km/h? Answer with the number."
        )
        assert result.steps_taken >= 1
        assert "60" in str(result.output)

    async def test_pipeline_agent_step(self):
        """A DAG pipeline runs a real agent step end to end."""
        ag = FireflyAgent("e2e-pipe", model=HAIKU, instructions="Answer with a single word.", auto_register=False)
        builder = PipelineBuilder()

        async def question(context: Any, inputs: Any) -> str:
            return "What is the capital of France?"

        builder.add_node("q", question)
        builder.add_node("ask", AgentStep(ag))  # edge supplies the prompt under "input"
        builder.add_edge("q", "ask")
        pipeline = builder.build()
        result = await pipeline.run(PipelineContext(inputs={}))
        assert "paris" in str(result.outputs["ask"].output).lower()

    async def test_workflow_default_runner_and_using(self):
        """A workflow on the default FireflyAgentRunner, with per-call ``using=`` targeting."""
        FireflyAgent("e2e-cheap", model=HAIKU, instructions="Answer with a single word.", auto_register=True)

        @workflow(register=False)
        async def wf(args, ctx):
            a = await agent("Reply with exactly: PONG", model=HAIKU)
            b = await agent("What is the capital of Japan?", using="e2e-cheap")
            return a, b, ctx.cost_spent_usd, ctx.tokens_spent

        a, b, cost, tokens = await wf.run(None, runner=FireflyAgentRunner(default_model=HAIKU))
        assert "PONG" in str(a).upper()
        assert "tokyo" in str(b).lower()
        assert cost > 0 and tokens > 0  # per-run budget ledger populated from real usage

    async def test_cost_tracking_records_real_cost(self):
        """The global usage tracker books real, non-zero Anthropic cost for a call."""
        tracker = UsageTracker()
        with patch("fireflyframework_agentic.agents.base.default_usage_tracker", tracker):
            ag = FireflyAgent("e2e-cost", model=HAIKU, auto_register=False)
            await ag.run("Say hello in one word.")
        summary = tracker.get_summary()
        assert summary.record_count == 1
        assert summary.total_tokens > 0
        assert summary.total_cost_usd > 0  # genai-prices resolved a real Anthropic price
