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

"""Alignment of Firefly tools with pydantic-ai native tooling.

Covers full-fidelity schema generation via ParameterSpec.python_type, RunContext
opt-in (takes_ctx) wired end-to-end through a real Agent run, description
forwarding through as_toolset, and the re-exported native combinators.
"""

from __future__ import annotations

from typing import Any, Literal

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.models.test import TestModel

from fireflyframework_agentic.exceptions import ToolError
from fireflyframework_agentic.tools import (
    FilteredToolset,
    PrefixedToolset,
    RunContext,
    WrapperToolset,
    to_pydantic_handler,
)
from fireflyframework_agentic.tools.base import BaseTool, GuardResult, ParameterSpec
from fireflyframework_agentic.tools.builder import ToolBuilder
from fireflyframework_agentic.tools.toolkit import ToolKit


def _schema(tool: BaseTool) -> dict[str, Any]:
    return Tool(tool.pydantic_handler(), name=tool.name, description=tool.description).function_schema.json_schema


class _Tool(BaseTool):
    def __init__(self, **kw: Any) -> None:
        super().__init__("t", description="d", **kw)

    async def _execute(self, **kwargs: Any) -> Any:
        return kwargs


# --------------------------------------------------------------------------- #
# Schema fidelity via python_type
# --------------------------------------------------------------------------- #


def test_python_type_list_preserves_element_type():
    schema = _schema(_Tool(parameters=[ParameterSpec(name="tags", python_type=list[str])]))
    prop = schema["properties"]["tags"]
    assert prop["type"] == "array"
    assert prop["items"] == {"type": "string"}  # element type preserved (the lossy map dropped it)


def test_python_type_literal_becomes_enum():
    schema = _schema(_Tool(parameters=[ParameterSpec(name="mode", python_type=Literal["fast", "slow"])]))
    prop = schema["properties"]["mode"]
    assert prop["type"] == "string"
    assert prop["enum"] == ["fast", "slow"]


def test_python_type_nested_model_emits_ref():
    class Address(BaseModel):
        city: str
        zip_code: str

    schema = _schema(_Tool(parameters=[ParameterSpec(name="addr", python_type=Address)]))
    assert "$defs" in schema and "Address" in schema["$defs"]
    # the property references the nested model rather than collapsing to Any
    assert "$ref" in schema["properties"]["addr"] or "allOf" in schema["properties"]["addr"]


def test_builder_python_type_gives_full_fidelity():
    tool = (
        ToolBuilder("b")
        .description("d")
        .parameter("ids", python_type=list[int], description="ids")
        .handler(lambda **kw: kw)
        .build()
    )
    assert _schema(tool)["properties"]["ids"] == {
        "type": "array",
        "items": {"type": "integer"},
        "description": "ids",
    }


# --------------------------------------------------------------------------- #
# RunContext opt-in (takes_ctx) — wired end-to-end
# --------------------------------------------------------------------------- #


def test_takes_ctx_is_detected_and_ctx_excluded_from_schema():
    fs = Tool(
        _Tool(takes_ctx=True, parameters=[ParameterSpec(name="q", python_type=str)]).pydantic_handler()
    ).function_schema
    assert fs.takes_ctx is True
    assert "ctx" not in fs.json_schema.get("properties", {})
    assert "q" in fs.json_schema["properties"]


def test_non_ctx_tool_stays_ctx_free():
    fs = Tool(_Tool(parameters=[ParameterSpec(name="q", python_type=str)]).pydantic_handler()).function_schema
    assert fs.takes_ctx is False


@pytest.mark.asyncio
async def test_runcontext_is_injected_through_a_real_agent_run():
    seen: dict[str, Any] = {}

    class CtxTool(BaseTool):
        def __init__(self) -> None:
            super().__init__(
                "ctx_tool",
                description="needs ctx",
                takes_ctx=True,
                parameters=[ParameterSpec(name="q", python_type=str)],
            )

        async def _execute(self, *, _ctx: Any = None, **kwargs: Any) -> Any:
            seen["ctx_type"] = type(_ctx).__name__
            seen["deps"] = getattr(_ctx, "deps", None)
            seen["q"] = kwargs.get("q")
            return "done"

    kit = ToolKit("k", [CtxTool()])
    agent = Agent(TestModel(), deps_type=str, toolsets=[kit.as_toolset()])
    await agent.run("go", deps="MY_DEPS")

    assert isinstance(seen.get("ctx_type"), str) and "RunContext" in seen["ctx_type"]
    assert seen["deps"] == "MY_DEPS"  # the tool reached the agent's deps via ctx
    assert isinstance(seen["q"], str)  # the declared tool arg was still passed


@pytest.mark.asyncio
async def test_guards_and_cache_key_never_see_ctx():
    captured: dict[str, Any] = {}

    class _RecordingGuard:
        async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
            captured["kwargs"] = dict(kwargs)
            return GuardResult(passed=True)

    class CtxTool(BaseTool):
        def __init__(self) -> None:
            super().__init__(
                "g",
                takes_ctx=True,
                guards=[_RecordingGuard()],
                parameters=[ParameterSpec(name="q", python_type=str)],
            )

        async def _execute(self, *, _ctx: Any = None, **kwargs: Any) -> Any:
            return "ok"

    tool = CtxTool()
    sentinel = object()
    await tool.execute_with_ctx(sentinel, q="hi")
    # The guard saw only the tool args — never ctx / _ctx.
    assert captured["kwargs"] == {"q": "hi"}


# --------------------------------------------------------------------------- #
# Conversion: description forwarding + value-add survival
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_as_toolset_forwards_description_to_the_model():
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    captured: dict[str, Any] = {}

    def capture(_messages: Any, info: AgentInfo) -> ModelResponse:
        captured["tools"] = {t.name: t.description for t in info.function_tools}
        return ModelResponse(parts=[TextPart("ok")])

    tool = _Tool(parameters=[ParameterSpec(name="q", python_type=str)])
    tool._description = "a helpful tool"
    agent = Agent(FunctionModel(capture), toolsets=[ToolKit("k", [tool]).as_toolset()])
    await agent.run("go")
    # The description reaches the model's tool definition (add_function dropped it before the fix).
    assert captured["tools"]["t"] == "a helpful tool"


@pytest.mark.asyncio
async def test_guarded_tool_still_rejects_through_converted_handler():
    class _Deny:
        async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
            return GuardResult(passed=False, reason="nope")

    tool = _Tool(guards=[_Deny()], parameters=[ParameterSpec(name="q", python_type=str)])
    handler = to_pydantic_handler(tool)
    with pytest.raises(ToolError):
        await handler(q="x")  # the guard fires via the converted handler


def test_native_combinators_are_re_exported():
    # Importable from the tools package without reaching into pydantic_ai.
    assert all(c is not None for c in (FilteredToolset, PrefixedToolset, WrapperToolset, RunContext))
