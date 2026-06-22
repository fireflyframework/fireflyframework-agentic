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

"""SP-3 tool layer: ``requires_approval`` threading + guard-denial taxonomy.

A tool's ``requires_approval`` flag must reach the native ``pydantic_ai.Tool``
on every conversion path (direct ``tools=``, ``ToolKit.as_pydantic_tools``,
``ToolKit.as_toolset``). Guard denials now raise ``ToolGuardError``. The legacy
``ApprovalGuard`` (bespoke approval via ``ToolError``) is removed in favour of
native deferred-tools.
"""

from __future__ import annotations

from typing import Any

import pytest

from fireflyframework_agentic.exceptions import ToolError, ToolGuardError
from fireflyframework_agentic.tools.base import BaseTool, GuardResult, ParameterSpec
from fireflyframework_agentic.tools.decorators import firefly_tool
from fireflyframework_agentic.tools.toolkit import ToolKit


class _Tool(BaseTool):
    def __init__(self, *, requires_approval: bool = False, guards: Any = ()) -> None:
        super().__init__(
            "danger",
            description="a dangerous tool",
            parameters=[ParameterSpec(name="q", python_type=str)],
            guards=guards,
            requires_approval=requires_approval,
        )

    async def _execute(self, **kwargs: Any) -> Any:
        return "ran"


def test_base_tool_requires_approval_property():
    assert _Tool().requires_approval is False
    assert _Tool(requires_approval=True).requires_approval is True


def test_firefly_tool_requires_approval_flag():
    @firefly_tool("t", requires_approval=True, auto_register=False)
    async def t(x: str) -> str:
        return x

    assert t.requires_approval is True

    @firefly_tool("t2", auto_register=False)
    async def t2(x: str) -> str:
        return x

    assert t2.requires_approval is False


def test_toolkit_as_pydantic_tools_threads_requires_approval():
    # Distinguish the two tools by giving them different names.
    a = _Tool(requires_approval=True)
    a._name = "a"
    b = _Tool(requires_approval=False)
    b._name = "b"
    kit = ToolKit("k", [a, b])

    pyd = {t.name: t for t in kit.as_pydantic_tools()}
    assert pyd["a"].requires_approval is True
    assert pyd["b"].requires_approval is False


def test_toolkit_as_toolset_threads_requires_approval():
    a = _Tool(requires_approval=True)
    a._name = "a"
    b = _Tool(requires_approval=False)
    b._name = "b"
    toolset = ToolKit("k", [a, b]).as_toolset()

    assert toolset.tools["a"].requires_approval is True
    assert toolset.tools["b"].requires_approval is False


@pytest.mark.asyncio
async def test_guard_denial_raises_tool_guard_error():
    class _Deny:
        async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
            return GuardResult(passed=False, reason="nope")

    tool = _Tool(guards=[_Deny()])
    with pytest.raises(ToolGuardError) as exc:
        await tool.execute(q="x")
    # ToolGuardError remains a ToolError subclass — existing `except ToolError` still catches it.
    assert isinstance(exc.value, ToolError)


def test_legacy_approval_guard_is_removed():
    import fireflyframework_agentic.tools as tools_pkg

    assert not hasattr(tools_pkg, "ApprovalGuard")
    # Native replacements are exported instead.
    for name in ("ApprovalRequired", "ApprovalRequiredToolset", "DeferredToolRequests", "DeferredToolResults"):
        assert hasattr(tools_pkg, name)
