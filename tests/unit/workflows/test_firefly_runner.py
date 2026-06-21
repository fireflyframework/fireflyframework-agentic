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

"""FireflyAgentRunner — workflows running through the full FireflyAgent stack.

These tests use pydantic-ai's ``TestModel`` so they exercise the real
FireflyAgent path (middleware, usage recording) with no network.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.registry import agent_registry
from fireflyframework_agentic.observability.usage import UsageTracker
from fireflyframework_agentic.workflows import (
    AgentCall,
    DefaultAgentRunner,
    FireflyAgentRunner,
    SmartRoutingRunner,
    agent,
    stream,
    workflow,
    workflow_registry,
)


@pytest.fixture(autouse=True)
def _clean_registries():
    workflow_registry.clear()
    agent_registry.clear()
    yield
    workflow_registry.clear()
    agent_registry.clear()


def _fa(name: str, text: str) -> FireflyAgent:
    return FireflyAgent(name, model=TestModel(custom_output_text=text), auto_register=False)


@pytest.mark.asyncio
async def test_reuse_configured_agent_runs_through_full_path():
    fa = _fa("cfg", "REUSED")
    captured: dict = {}

    @workflow(register=False)
    async def wf(args, ctx):
        out = await agent("hi")
        captured["tokens"] = ctx.tokens_spent
        captured["agents"] = ctx.agents_started
        return out

    out = await wf.run(None, runner=FireflyAgentRunner(fa))
    assert out == "REUSED"
    assert captured["tokens"] > 0  # tokens flow into the per-run WorkflowBudget ledger
    assert captured["agents"] == 1


@pytest.mark.asyncio
async def test_ephemeral_path_does_not_touch_registry():
    before = len(agent_registry)

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("x")

    out = await wf.run(None, runner=FireflyAgentRunner(default_model=TestModel(custom_output_text="EPH")))
    assert out == "EPH"
    assert len(agent_registry) == before  # ephemeral agent is built auto_register=False


@pytest.mark.asyncio
async def test_firefly_agent_runner_is_the_default():
    """With no runner= injected, sub-agents run through FireflyAgent — the default."""
    fresh = UsageTracker()

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("x", model=TestModel(custom_output_text="DEFAULT"))

    with patch("fireflyframework_agentic.agents.base.default_usage_tracker", fresh):
        out = await wf.run(None)  # NO runner= -> the framework default

    assert out == "DEFAULT"
    # Reaching the global usage tracker only happens via FireflyAgent (a bare
    # pydantic_ai.Agent never touches it) -> proves the default is FireflyAgentRunner.
    assert fresh.get_summary().record_count == 1


@pytest.mark.asyncio
async def test_ephemeral_without_a_model_raises():
    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("x")

    with pytest.raises(ValueError, match="requires a model"):
        await wf.run(None, runner=FireflyAgentRunner())


@pytest.mark.asyncio
async def test_using_resolves_a_registry_name():
    agent_registry.register(_fa("named", "NAMED"))

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("x", using="named")

    out = await wf.run(None, runner=FireflyAgentRunner(default_model=TestModel(custom_output_text="DEFAULT")))
    assert out == "NAMED"  # the per-call target wins over the runner's default source


@pytest.mark.asyncio
async def test_using_instance_targets_that_agent():
    target = _fa("target", "TARGET")

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("x", using=target)

    out = await wf.run(None, runner=FireflyAgentRunner(default_model=TestModel(custom_output_text="DEFAULT")))
    assert out == "TARGET"


@pytest.mark.asyncio
async def test_default_runner_rejects_using():
    target = _fa("t", "X")

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("x", using=target)

    with pytest.raises(ValueError, match="FireflyAgentRunner"):
        await wf.run(None, runner=DefaultAgentRunner(default_model=TestModel()))


@pytest.mark.asyncio
async def test_per_call_tools_on_a_reused_agent_raises():
    fa = _fa("cfg", "X")

    def my_tool(x: int) -> int:
        return x

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("x", tools=[my_tool])

    # pydantic-ai has no per-call tools= param, so tools on a reused agent is rejected.
    with pytest.raises(ValueError, match="tools="):
        await wf.run(None, runner=FireflyAgentRunner(fa))


@pytest.mark.asyncio
async def test_streaming_through_a_firefly_agent():
    @workflow(register=False)
    async def wf(args, ctx):
        deltas = []
        async with stream("go") as s:
            async for d in s.text():
                deltas.append(d)
        return s.output, "".join(deltas), ctx.tokens_spent

    out, joined, tokens = await wf.run(
        None, runner=FireflyAgentRunner(default_model=TestModel(custom_output_text="STREAM ME"))
    )
    assert out == "STREAM ME"
    assert joined == "STREAM ME"  # deltas reassemble to the full output
    assert tokens > 0


@pytest.mark.asyncio
async def test_global_usage_tracker_written_exactly_once_per_call():
    fresh = UsageTracker()

    @workflow(register=False)
    async def wf(args, ctx):
        await agent("a")
        await agent("b")
        return ctx.tokens_spent

    with patch("fireflyframework_agentic.agents.base.default_usage_tracker", fresh):
        tokens = await wf.run(None, runner=FireflyAgentRunner(default_model=TestModel(custom_output_text="Y")))

    # Two agent() calls => exactly two global-ledger writes (no double counting),
    assert fresh.get_summary().record_count == 2
    # and the per-run WorkflowBudget ledger is populated independently.
    assert tokens > 0


@pytest.mark.asyncio
async def test_smart_routing_forwards_using_to_base_runner():
    captured: dict = {}

    class CapturingRunner:
        async def run(
            self,
            prompt,
            *,
            model=None,
            output_type=None,
            instructions=None,
            deps=None,
            tools=None,
            toolsets=None,
            using=None,
        ):
            captured["using"] = using
            captured["model"] = model
            return AgentCall(output="ok", tokens=1)

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("x", using="target", model="m1")

    router = SmartRoutingRunner(["m1", "m2"], base_runner=CapturingRunner())
    out = await wf.run(None, runner=router)
    assert out == "ok"
    assert captured["using"] == "target"  # routing composes with using=
    assert captured["model"] == "m1"
