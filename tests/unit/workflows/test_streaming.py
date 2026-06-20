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

"""Tests for the streaming primitive (no LLM)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from fireflyframework_agentic.exceptions import WorkflowError
from fireflyframework_agentic.workflows import (
    AgentCall,
    Journal,
    StreamHandle,
    agent,
    stream,
    workflow,
    workflow_registry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    workflow_registry.clear()
    yield
    workflow_registry.clear()


class _FakeHandle:
    def __init__(self, chunks: tuple[str, ...]) -> None:
        self._chunks = chunks
        self.call: AgentCall | None = None

    async def text(self) -> AsyncIterator[str]:
        for c in self._chunks:
            yield c

    @property
    def output(self) -> Any:
        return self.call.output if self.call is not None else None


class FakeStreamRunner:
    def __init__(self, chunks: tuple[str, ...] = ("hel", "lo"), *, tokens: int = 2, cost: float = 0.001) -> None:
        self._chunks = chunks
        self._tokens = tokens
        self._cost = cost

    async def run(
        self, prompt, *, model=None, output_type=None, instructions=None, deps=None, tools=None, toolsets=None
    ):
        return AgentCall(output="".join(self._chunks), tokens=self._tokens, cost_usd=self._cost)

    @asynccontextmanager
    async def run_stream(
        self, prompt, *, model=None, output_type=None, instructions=None, deps=None, tools=None, toolsets=None
    ):
        handle = _FakeHandle(self._chunks)
        yield handle
        handle.call = AgentCall(output="".join(self._chunks), tokens=self._tokens, cost_usd=self._cost)


class NonStreamRunner:
    async def run(
        self, prompt, *, model=None, output_type=None, instructions=None, deps=None, tools=None, toolsets=None
    ):
        return AgentCall(output="x")


@pytest.mark.asyncio
async def test_stream_collects_deltas_output_and_cost():
    captured = {}

    @workflow(register=False)
    async def wf(args, ctx):
        deltas = []
        async with stream("say hi") as s:
            async for d in s.text():
                deltas.append(d)
        captured["output"] = s.output
        captured["cost"] = ctx.cost_spent_usd
        captured["agents"] = ctx.agents_started
        return deltas

    deltas = await wf.run(None, runner=FakeStreamRunner(("hel", "lo"), tokens=2, cost=0.001))
    assert deltas == ["hel", "lo"]
    assert captured["output"] == "hello"
    assert abs(captured["cost"] - 0.001) < 1e-9
    assert captured["agents"] == 1


@pytest.mark.asyncio
async def test_stream_resume_yields_cached_output_once():
    journal = Journal()

    @workflow(register=False)
    async def wf(args, ctx):
        out = []
        async with stream("x") as s:
            async for d in s.text():
                out.append(d)
        return out

    assert await wf.run(None, runner=FakeStreamRunner(("a", "b")), journal=journal) == ["a", "b"]
    # Resume: the call is cached, so the full output is yielded once (runner unused).
    assert await wf.run(None, runner=FakeStreamRunner(("SHOULD", "NOT", "RUN")), journal=journal) == ["ab"]


@pytest.mark.asyncio
async def test_stream_requires_a_streaming_runner():
    @workflow(register=False)
    async def wf(args, ctx):
        async with stream("x") as s:
            async for _ in s.text():
                pass

    with pytest.raises(WorkflowError):
        await wf.run(None, runner=NonStreamRunner())


@pytest.mark.asyncio
async def test_default_runner_streamhandle_is_exported():
    # StreamHandle is part of the public surface (typing/extension point).
    assert StreamHandle is not None
    # A plain agent() still works alongside streaming runners.

    @workflow(register=False)
    async def wf(args, ctx):
        return await agent("hi")

    assert await wf.run(None, runner=FakeStreamRunner(("z",))) == "z"
