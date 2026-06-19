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

"""SP-4: ToolKit -> pydantic-ai FunctionToolset adapter and FireflyAgent(toolsets=)."""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec
from fireflyframework_agentic.tools.toolkit import ToolKit


class _AddTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            "add",
            description="Add two integers",
            parameters=[
                ParameterSpec(name="x", type_annotation="int"),
                ParameterSpec(name="y", type_annotation="int"),
            ],
        )
        self.called = False

    async def _execute(self, x: int, y: int) -> int:
        self.called = True
        return x + y


def test_as_toolset_returns_function_toolset_with_tools():
    kit = ToolKit(name="math", tools=[_AddTool()])
    toolset = kit.as_toolset()
    assert isinstance(toolset, FunctionToolset)
    assert "add" in toolset.tools


@pytest.mark.asyncio
async def test_firefly_agent_invokes_tool_from_toolset():
    tool = _AddTool()
    kit = ToolKit(name="math", tools=[tool])
    # TestModel calls every available tool, so a reachable toolset tool runs.
    agent = FireflyAgent("math-agent", model=TestModel(), toolsets=[kit.as_toolset()], auto_register=False)
    await agent.run("please add the numbers")
    assert tool.called


@pytest.mark.asyncio
async def test_empty_toolsets_is_a_no_op():
    agent = FireflyAgent("plain", model=TestModel(), auto_register=False)
    result = await agent.run("hi")
    assert result is not None
