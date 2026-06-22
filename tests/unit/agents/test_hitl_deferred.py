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

from typing import Any

import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.toolsets import ApprovalRequiredToolset, FunctionToolset

from fireflyframework_agentic.agents.base import FireflyAgent, is_deferred
from fireflyframework_agentic.agents.builtin_middleware import CacheMiddleware, ValidationMiddleware
from fireflyframework_agentic.agents.cache import ResultCache
from fireflyframework_agentic.exceptions import OutputReviewError
from fireflyframework_agentic.tools.decorators import firefly_tool
from fireflyframework_agentic.tools.toolkit import ToolKit


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
