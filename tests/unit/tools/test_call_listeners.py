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

"""``BaseTool`` call hooks: a public seam around every tool call.

Until this suite existed ``_guarded_execute`` — guards, timeout, error wrapping — was the one
path every call took and it was private, so a host that needed to see each call begin and end
(a per-turn ledger, an audit trail, a metering row) subclassed the private method, and a host that
needed to raise ``requires_approval`` after construction ``setattr``'d the private flag. Both
broke on every refactor. The contract pinned here:

* :class:`ToolCallListener` receives ``before_call`` / ``after_call`` / ``on_error`` /
  ``on_pause`` around ``_execute``, in that order, with the same ``kwargs`` and ``ctx`` the
  tool sees;
* the guard chain itself is a listener — :class:`GuardChainListener`, first in the chain —
  so there is one seam, not a private path with a public window bolted on;
* ``BaseTool.require_approval(flag)`` is the supported way to change the flag after
  construction; ``defers=True`` declares that a tool can raise ``CallDeferred`` so an agent
  widens its output type without guessing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred

from fireflyframework_agentic.exceptions import ToolError, ToolGuardError, ToolTimeoutError
from fireflyframework_agentic.tools.base import (
    BaseTool,
    GuardChainListener,
    GuardResult,
    ParameterSpec,
    ToolCallListener,
)


class Recorder:
    """A listener that writes down every hook it receives."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any], Any]] = []

    async def before_call(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any) -> None:
        self.events.append(("before", tool.name, dict(kwargs), ctx))

    async def after_call(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any, result: Any) -> None:
        self.events.append(("after", tool.name, dict(kwargs), result))

    async def on_error(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any, exc: BaseException) -> None:
        self.events.append(("error", tool.name, dict(kwargs), exc))

    async def on_pause(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any, signal: BaseException) -> None:
        self.events.append(("pause", tool.name, dict(kwargs), signal))


class _Behaviour(BaseTool):
    def __init__(self, behaviour: str, **kw: Any) -> None:
        super().__init__(
            "probe",
            description="does what its behaviour says",
            parameters=[ParameterSpec(name="q", python_type=str)],
            **kw,
        )
        self._behaviour = behaviour

    async def _execute(self, **kwargs: Any) -> Any:
        if self._behaviour == "ok":
            return f"ran {kwargs['q']}"
        if self._behaviour == "retry":
            raise ModelRetry("say it again")
        if self._behaviour == "boom":
            raise ValueError("broke")
        if self._behaviour == "approval":
            raise ApprovalRequired()
        if self._behaviour == "defer":
            raise CallDeferred()
        if self._behaviour == "slow":
            await asyncio.sleep(1)
        return None


class _Deny:
    async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
        return GuardResult(passed=False, reason="not today")


class TestListenerProtocol:
    def test_the_protocol_is_structural(self) -> None:
        assert isinstance(Recorder(), ToolCallListener)
        assert not isinstance(object(), ToolCallListener)

    def test_the_guard_chain_is_the_first_listener(self) -> None:
        recorder = Recorder()
        tool = _Behaviour("ok", guards=[_Deny()], listeners=[recorder])
        assert isinstance(tool.listeners[0], GuardChainListener)
        assert tool.listeners[1] is recorder
        # The guards property still answers, for everything that reads it today.
        assert len(tool.guards) == 1

    def test_add_listener_appends_and_is_idempotent(self) -> None:
        recorder = Recorder()
        tool = _Behaviour("ok")
        tool.add_listener(recorder)
        tool.add_listener(recorder)
        assert [x for x in tool.listeners if x is recorder] == [recorder]


class TestHookOrder:
    async def test_ok_call_sees_before_then_after_with_the_result(self) -> None:
        recorder = Recorder()
        tool = _Behaviour("ok", listeners=[recorder])
        assert await tool.execute(q="x") == "ran x"
        assert recorder.events == [("before", "probe", {"q": "x"}, None), ("after", "probe", {"q": "x"}, "ran x")]

    async def test_ctx_reaches_the_listener_but_never_the_kwargs(self) -> None:
        recorder = Recorder()
        tool = _Behaviour("ok", listeners=[recorder], takes_ctx=False)
        ctx = object()
        await tool.execute_with_ctx(ctx, q="x")
        assert recorder.events[0] == ("before", "probe", {"q": "x"}, ctx)

    async def test_model_retry_is_reported_as_an_error_and_still_propagates(self) -> None:
        recorder = Recorder()
        tool = _Behaviour("retry", listeners=[recorder])
        with pytest.raises(ModelRetry):
            await tool.execute(q="x")
        kind, _, _, exc = recorder.events[-1]
        assert kind == "error"
        assert isinstance(exc, ModelRetry)

    async def test_a_plain_exception_is_reported_as_the_tool_error_the_caller_sees(self) -> None:
        recorder = Recorder()
        tool = _Behaviour("boom", listeners=[recorder])
        with pytest.raises(ToolError) as excinfo:
            await tool.execute(q="x")
        kind, _, _, exc = recorder.events[-1]
        assert kind == "error"
        assert exc is excinfo.value
        assert isinstance(exc.__cause__, ValueError)

    async def test_a_timeout_is_reported_as_the_timeout_error(self) -> None:
        recorder = Recorder()
        tool = _Behaviour("slow", listeners=[recorder], timeout=0.01)
        with pytest.raises(ToolTimeoutError):
            await tool.execute(q="x")
        assert isinstance(recorder.events[-1][3], ToolTimeoutError)

    @pytest.mark.parametrize("behaviour", ["approval", "defer"])
    async def test_a_hitl_signal_is_a_pause_not_an_error(self, behaviour: str) -> None:
        recorder = Recorder()
        tool = _Behaviour(behaviour, listeners=[recorder])
        with pytest.raises((ApprovalRequired, CallDeferred)):
            await tool.execute(q="x")
        kinds = [e[0] for e in recorder.events]
        assert kinds == ["before", "pause"]

    async def test_a_guard_refusal_reaches_on_error_and_never_runs_the_tool(self) -> None:
        recorder = Recorder()
        tool = _Behaviour("ok", guards=[_Deny()], listeners=[recorder])
        with pytest.raises(ToolGuardError, match="not today"):
            await tool.execute(q="x")
        # The guard chain runs before any later listener's before_call, so the recorder saw no
        # "before" — the call was refused before it began — and one "error".
        assert [e[0] for e in recorder.events] == ["error"]
        assert isinstance(recorder.events[0][3], ToolGuardError)

    async def test_a_listener_may_refuse_a_call_by_raising(self) -> None:
        class Refuser:
            async def before_call(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any) -> None:
                raise ModelRetry("not with that argument")

        recorder = Recorder()
        tool = _Behaviour("ok", listeners=[Refuser(), recorder])
        with pytest.raises(ModelRetry):
            await tool.execute(q="x")
        assert [e[0] for e in recorder.events] == ["error"]

    async def test_a_listener_that_raises_in_after_call_does_not_lose_the_result_silently(self) -> None:
        class Broken:
            async def after_call(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any, result: Any) -> None:
                raise RuntimeError("ledger is down")

        tool = _Behaviour("ok", listeners=[Broken()])
        with pytest.raises(ToolError, match="ledger is down"):
            await tool.execute(q="x")

    async def test_a_partial_listener_is_fine(self) -> None:
        """Only the hooks a listener defines are called — a metering row needs after_call alone."""

        class AfterOnly:
            def __init__(self) -> None:
                self.results: list[Any] = []

            async def after_call(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any, result: Any) -> None:
                self.results.append(result)

        after = AfterOnly()
        tool = _Behaviour("ok", listeners=[after])
        await tool.execute(q="x")
        assert after.results == ["ran x"]


class TestRequireApproval:
    def test_the_flag_can_be_raised_and_lowered_after_construction(self) -> None:
        tool = _Behaviour("ok")
        assert tool.requires_approval is False
        assert tool.require_approval(True) is True
        assert tool.requires_approval is True
        # Reports whether anything changed.
        assert tool.require_approval(True) is False
        assert tool.require_approval(False) is True
        assert tool.requires_approval is False

    def test_defers_is_declared_not_guessed(self) -> None:
        assert _Behaviour("defer", defers=True).defers is True
        assert _Behaviour("ok").defers is False


class TestListenerThroughAnAgent:
    async def test_a_ctx_tool_listener_receives_the_run_context_with_the_call_id(self) -> None:
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        from fireflyframework_agentic.agents.base import FireflyAgent

        state = {"n": 0}

        def fn(messages: Any, info: Any) -> ModelResponse:
            state["n"] += 1
            if state["n"] == 1:
                return ModelResponse(parts=[ToolCallPart(tool_name="probe", args={"q": "x"}, tool_call_id="call-7")])
            return ModelResponse(parts=[TextPart("done")])

        recorder = Recorder()
        tool = _Behaviour("ok", listeners=[recorder], takes_ctx=True)
        agent = FireflyAgent("l", model=FunctionModel(fn), tools=[tool], auto_register=False)
        result = await agent.run("go")
        assert result.output == "done"
        before = next(e for e in recorder.events if e[0] == "before")
        assert before[2] == {"q": "x"}
        assert before[3].tool_call_id == "call-7"
