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

"""SP-3: human-in-the-loop tool approval via pydantic-ai native deferred-tools.

An approval-required tool pauses the run and surfaces a ``DeferredToolRequests``
(``is_deferred`` is True). The caller resumes by approving/denying via
``DeferredToolResults``. Post-run cross-cutting code (memory, OutputGuard,
Validation, Cache, Logging) must treat the paused result as a control object,
not a final answer.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults, Tool, ToolApproved, ToolDenied
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.toolsets import ApprovalRequiredToolset, FunctionToolset

from fireflyframework_agentic.agents.base import FireflyAgent, is_deferred
from fireflyframework_agentic.agents.builtin_middleware import (
    CacheMiddleware,
    ExplainabilityMiddleware,
    OutputGuardError,
    OutputGuardMiddleware,
    ValidationMiddleware,
)
from fireflyframework_agentic.agents.cache import ResultCache
from fireflyframework_agentic.exceptions import OutputReviewError
from fireflyframework_agentic.memory.manager import MemoryManager
from fireflyframework_agentic.tools import ApprovalRequired
from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec
from fireflyframework_agentic.tools.decorators import firefly_tool
from fireflyframework_agentic.tools.toolkit import ToolKit


def _model_calling(*calls: tuple[str, dict[str, Any], str]) -> FunctionModel:
    """A model that emits the given tool calls in its first response, then text.

    Each call is ``(tool_name, args, tool_call_id)``. Emitting several in one
    response exercises a single pause carrying multiple pending approvals.
    """
    state = {"n": 0}

    def fn(messages: Any, info: Any) -> ModelResponse:
        state["n"] += 1
        if state["n"] == 1:
            return ModelResponse(parts=[ToolCallPart(tool_name=t, args=a, tool_call_id=c) for (t, a, c) in calls])
        return ModelResponse(parts=[TextPart("done")])

    return FunctionModel(fn)


class _RecordingTool(BaseTool):
    """An approval-required tool that records the args it actually executed with."""

    def __init__(self, name: str = "rec_delete") -> None:
        super().__init__(
            name,
            description="delete by name",
            parameters=[ParameterSpec(name="name", python_type=str)],
            requires_approval=True,
        )
        self.ran_with: list[str] = []

    async def _execute(self, *, name: str) -> str:
        self.ran_with.append(name)
        return f"DELETED {name}"


class _DynamicTool(BaseTool):
    """A ctx-aware tool that defers *dynamically* by raising ApprovalRequired until approved."""

    def __init__(self) -> None:
        super().__init__(
            "dyn_delete",
            description="delete a record (needs approval)",
            parameters=[ParameterSpec(name="record_id", python_type=str)],
            takes_ctx=True,
        )
        self.seen: dict[str, Any] = {}

    async def _execute(self, *, record_id: str, _ctx: Any) -> str:
        if not getattr(_ctx, "tool_call_approved", False):
            raise ApprovalRequired(metadata={"reason": "destructive", "record_id": record_id})
        self.seen["approved"] = _ctx.tool_call_approved
        self.seen["metadata"] = dict(_ctx.tool_call_metadata or {})
        return f"deleted {record_id}"


def _approval_model() -> FunctionModel:
    """A model that calls ``delete_db`` first, then answers with text."""
    state = {"n": 0}

    def fn(messages: Any, info: Any) -> ModelResponse:
        state["n"] += 1
        if state["n"] == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="delete_db", args={"name": "prod"}, tool_call_id="call_1")]
            )
        return ModelResponse(parts=[TextPart("done")])

    return FunctionModel(fn)


@firefly_tool("delete_db", description="Delete a database", requires_approval=True, auto_register=False)
async def delete_db(name: str) -> str:
    return f"DELETED {name}"


@pytest.mark.asyncio
async def test_requires_approval_pauses_then_resumes_approve():
    agent = FireflyAgent("hitl", model=_approval_model(), tools=[delete_db], auto_register=False)

    paused = await agent.run("delete prod")
    assert is_deferred(paused)
    reqs = paused.output
    assert isinstance(reqs, DeferredToolRequests)
    assert [c.tool_name for c in reqs.approvals] == ["delete_db"]
    assert not reqs.calls
    call_id = reqs.approvals[0].tool_call_id

    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={call_id: True}),
    )
    assert not is_deferred(resumed)
    assert resumed.output == "done"


@pytest.mark.asyncio
async def test_resume_deny_surfaces_to_model_and_completes():
    agent = FireflyAgent("hitl-deny", model=_approval_model(), tools=[delete_db], auto_register=False)
    paused = await agent.run("delete prod")
    call_id = paused.output.approvals[0].tool_call_id

    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={call_id: ToolDenied(message="not allowed")}),
    )
    # A denial is not a crash: the model is told and the run completes.
    assert not is_deferred(resumed)
    assert resumed.output == "done"


@pytest.mark.asyncio
async def test_inline_approval_handler_resolves_without_pausing():
    def handler(ctx: Any, requests: DeferredToolRequests) -> DeferredToolResults:
        return requests.build_results(approvals={c.tool_call_id: True for c in requests.approvals})

    agent = FireflyAgent(
        "hitl-inline", model=_approval_model(), tools=[delete_db], approval_handler=handler, auto_register=False
    )
    result = await agent.run("delete prod")
    assert not is_deferred(result)
    assert result.output == "done"


def test_non_hitl_agent_output_type_is_not_widened():
    agent = FireflyAgent("plain", model=_approval_model(), auto_register=False)
    assert agent._hitl_enabled is False


def test_hitl_detected_from_requires_approval_tool():
    agent = FireflyAgent("d1", model=_approval_model(), tools=[delete_db], auto_register=False)
    assert agent._hitl_enabled is True


def test_hitl_detected_from_toolkit():
    kit = ToolKit("danger", [delete_db])
    agent = FireflyAgent("d2", model=_approval_model(), tools=[kit], auto_register=False)
    assert agent._hitl_enabled is True


def test_hitl_detected_from_as_toolset():
    kit = ToolKit("danger", [delete_db])
    agent = FireflyAgent("d3", model=_approval_model(), toolsets=[kit.as_toolset()], auto_register=False)
    assert agent._hitl_enabled is True


def test_hitl_detected_from_approval_required_toolset():
    wrapped = ApprovalRequiredToolset(FunctionToolset(), approval_required_func=lambda *a: True)
    agent = FireflyAgent("d4", model=_approval_model(), toolsets=[wrapped], auto_register=False)
    assert agent._hitl_enabled is True


def test_hitl_forced_via_flag():
    agent = FireflyAgent("d5", model=_approval_model(), hitl=True, auto_register=False)
    assert agent._hitl_enabled is True


@pytest.mark.asyncio
async def test_paused_result_not_persisted_to_memory():
    from fireflyframework_agentic.memory.manager import MemoryManager

    mem = MemoryManager()
    agent = FireflyAgent("hitl-mem", model=_approval_model(), tools=[delete_db], memory=mem, auto_register=False)
    paused = await agent.run("delete prod", conversation_id="c1")
    assert is_deferred(paused)
    # The pause must not be written as a conversation turn.
    assert mem.get_message_history("c1") == []


@pytest.mark.asyncio
async def test_validation_middleware_skips_deferred_output():
    class _AlwaysFailReviewer:
        def _parse_output(self, raw: Any) -> tuple[Any, list[str]]:
            return None, ["reviewer always fails"]

        def _validate_output(self, validated: Any) -> Any:
            return None

    agent = FireflyAgent(
        "hitl-val",
        model=_approval_model(),
        tools=[delete_db],
        middleware=[ValidationMiddleware(reviewer=_AlwaysFailReviewer())],
        default_middleware=False,
        auto_register=False,
    )
    # Would raise OutputReviewError if the deferred output were validated.
    paused = await agent.run("delete prod")
    assert is_deferred(paused)

    # Sanity: the same reviewer DOES fire on a real completed output.
    plain = FireflyAgent(
        "plain-val",
        model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("hello")])),
        middleware=[ValidationMiddleware(reviewer=_AlwaysFailReviewer())],
        default_middleware=False,
        auto_register=False,
    )
    with pytest.raises(OutputReviewError):
        await plain.run("hi")


@pytest.mark.asyncio
async def test_cache_middleware_does_not_cache_a_pause():
    cache = ResultCache()
    agent = FireflyAgent(
        "hitl-cache",
        model=_approval_model(),
        tools=[delete_db],
        middleware=[CacheMiddleware(cache=cache)],
        default_middleware=False,
        auto_register=False,
    )
    paused = await agent.run("delete prod")
    assert is_deferred(paused)
    # The paused run must not have been cached.
    assert cache.get("hitl-cache", "delete prod") is None


def test_is_deferred_helper():
    class _R:
        output = DeferredToolRequests(approvals=[], calls=[], metadata={})

    class _Done:
        output = "final answer"

    assert is_deferred(_R()) is True
    assert is_deferred(_Done()) is False
    assert is_deferred(None) is False


@pytest.mark.asyncio
async def test_run_sync_requires_approval_pauses_then_resumes_approve():
    agent = FireflyAgent("hitl-sync", model=_approval_model(), tools=[delete_db], auto_register=False)
    paused = agent.run_sync("delete prod")
    assert is_deferred(paused)
    call_id = paused.output.approvals[0].tool_call_id
    resumed = agent.run_sync(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={call_id: True}),
    )
    assert not is_deferred(resumed)
    assert resumed.output == "done"


@pytest.mark.asyncio
async def test_resume_approve_with_override_args_replaces_tool_args():
    tool = _RecordingTool()
    agent = FireflyAgent(
        "override", model=_model_calling(("rec_delete", {"name": "prod"}, "c1")), tools=[tool], auto_register=False
    )
    paused = await agent.run("delete prod")
    call_id = paused.output.approvals[0].tool_call_id
    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={call_id: ToolApproved(override_args={"name": "staging"})}),
    )
    assert not is_deferred(resumed)
    assert tool.ran_with == ["staging"]  # override_args replaced the model's "prod"


@pytest.mark.asyncio
async def test_dynamic_approval_required_from_tool_body_with_hitl_flag():
    tool = _DynamicTool()
    agent = FireflyAgent(
        "dyn",
        model=_model_calling(("dyn_delete", {"record_id": "7"}, "c1")),
        tools=[tool],
        hitl=True,
        auto_register=False,
    )
    paused = await agent.run("delete 7")
    assert is_deferred(paused)
    call_id = paused.output.approvals[0].tool_call_id
    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={call_id: True}),
    )
    assert not is_deferred(resumed)
    assert tool.seen.get("approved") is True

    # Without hitl=True the dynamic deferral has nowhere to surface -> UserError.
    bad = FireflyAgent(
        "dyn-bad",
        model=_model_calling(("dyn_delete", {"record_id": "7"}, "c1")),
        tools=[_DynamicTool()],
        auto_register=False,
    )
    with pytest.raises(UserError):
        await bad.run("delete 7")


@pytest.mark.asyncio
async def test_approval_metadata_round_trips_to_run_context():
    tool = _DynamicTool()
    agent = FireflyAgent(
        "meta",
        model=_model_calling(("dyn_delete", {"record_id": "9"}, "c1")),
        tools=[tool],
        hitl=True,
        auto_register=False,
    )
    paused = await agent.run("delete 9")
    call_id = paused.output.approvals[0].tool_call_id
    # Outbound: ApprovalRequired(metadata=...) surfaces in DeferredToolRequests.metadata.
    assert paused.output.metadata.get(call_id) == {"reason": "destructive", "record_id": "9"}
    # Inbound: DeferredToolResults.metadata reaches the tool's RunContext on resume.
    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={call_id: True}, metadata={call_id: {"reviewer": "alice"}}),
    )
    assert not is_deferred(resumed)
    assert tool.seen.get("approved") is True
    assert tool.seen.get("metadata") == {"reviewer": "alice"}


@pytest.mark.asyncio
async def test_approval_required_toolset_pauses_and_resumes_end_to_end():
    ran: list[str] = []

    async def do_thing(x: str) -> str:
        ran.append(x)
        return f"did {x}"

    fts = FunctionToolset()
    fts.add_function(do_thing, name="do_thing")
    gated = ApprovalRequiredToolset(fts, approval_required_func=lambda *a: True)
    agent = FireflyAgent(
        "ars", model=_model_calling(("do_thing", {"x": "go"}, "c1")), toolsets=[gated], auto_register=False
    )

    paused = await agent.run("do it")
    assert is_deferred(paused)
    assert ran == []  # gated tool did not run before approval
    call_id = paused.output.approvals[0].tool_call_id
    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={call_id: True}),
    )
    assert not is_deferred(resumed)
    assert ran == ["go"]


@pytest.mark.asyncio
async def test_output_guard_middleware_skips_deferred_output():
    class _BlockAll:
        def scan(self, text: str) -> Any:
            return SimpleNamespace(
                safe=False, matched_categories=["x"], matched_patterns=["p"], reason="blocked", sanitised_output=None
            )

    agent = FireflyAgent(
        "og",
        model=_approval_model(),
        tools=[delete_db],
        middleware=[OutputGuardMiddleware(guard=_BlockAll())],
        default_middleware=False,
        auto_register=False,
    )
    paused = await agent.run("delete prod")
    assert is_deferred(paused)  # the block-all guard did NOT fire on the paused output

    plain = FireflyAgent(
        "og-plain",
        model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("hi")])),
        middleware=[OutputGuardMiddleware(guard=_BlockAll())],
        default_middleware=False,
        auto_register=False,
    )
    with pytest.raises(OutputGuardError):
        await plain.run("x")


@pytest.mark.asyncio
async def test_explainability_middleware_records_paused_marker():
    records: list[tuple[str, dict[str, Any]]] = []

    class _Recorder:
        def record(self, kind: str, **kw: Any) -> None:
            records.append((kind, kw))

    agent = FireflyAgent(
        "expl",
        model=_approval_model(),
        tools=[delete_db],
        middleware=[ExplainabilityMiddleware(recorder=_Recorder())],
        default_middleware=False,
        auto_register=False,
    )
    paused = await agent.run("delete prod")
    assert is_deferred(paused)
    summaries = [kw.get("output_summary") for _, kw in records]
    assert "<paused: awaiting tool approval>" in summaries


@pytest.mark.asyncio
async def test_logging_middleware_logs_paused_branch(caplog: pytest.LogCaptureFixture):
    agent = FireflyAgent("logp", model=_approval_model(), tools=[delete_db], auto_register=False)
    with caplog.at_level(logging.INFO, logger="fireflyframework_agentic.agents.builtin_middleware"):
        paused = await agent.run("delete prod")
    assert is_deferred(paused)
    assert "paused" in caplog.text and "awaiting tool approval" in caplog.text
    assert "completed in" not in caplog.text  # the normal completion line is NOT emitted


@pytest.mark.asyncio
async def test_multiple_pending_approvals_in_one_pause():
    a = _RecordingTool("del_a")
    b = _RecordingTool("del_b")
    model = _model_calling(("del_a", {"name": "A"}, "ca"), ("del_b", {"name": "B"}, "cb"))
    agent = FireflyAgent("multi", model=model, tools=[a, b], auto_register=False)

    paused = await agent.run("delete both")
    assert is_deferred(paused)
    ids = {c.tool_name: c.tool_call_id for c in paused.output.approvals}
    assert set(ids) == {"del_a", "del_b"}

    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(
            approvals={ids["del_a"]: True, ids["del_b"]: ToolDenied(message="no")}
        ),
    )
    assert not is_deferred(resumed)
    assert a.ran_with == ["A"]  # approved ran
    assert b.ran_with == []  # denied did not run


@pytest.mark.asyncio
async def test_approval_handler_returning_none_still_pauses():
    def decline(ctx: Any, requests: DeferredToolRequests) -> None:
        return None  # decline to resolve inline -> the run pauses normally

    agent = FireflyAgent(
        "handler-none", model=_approval_model(), tools=[delete_db], approval_handler=decline, auto_register=False
    )
    paused = await agent.run("delete prod")
    assert is_deferred(paused)
    call_id = paused.output.approvals[0].tool_call_id
    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={call_id: True}),
    )
    assert not is_deferred(resumed)


def test_raw_pydantic_tool_requires_approval_detected():
    async def fn(x: str) -> str:
        return x

    agent = FireflyAgent("raw", model=_approval_model(), tools=[Tool(fn, requires_approval=True)], auto_register=False)
    assert agent._hitl_enabled is True


@pytest.mark.asyncio
async def test_resume_with_memory_does_not_double_inject():
    mem = MemoryManager()
    agent = FireflyAgent("memr", model=_approval_model(), tools=[delete_db], memory=mem, auto_register=False)
    paused = await agent.run("delete prod", conversation_id="c1")
    assert is_deferred(paused)
    # Resume with an explicit message_history and NO conversation_id: memory injection is
    # skipped (mutually exclusive), so prior messages are not double-injected and it completes.
    resumed = await agent.run(
        None,
        message_history=paused.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={paused.output.approvals[0].tool_call_id: True}),
    )
    assert not is_deferred(resumed)
    assert resumed.output == "done"
