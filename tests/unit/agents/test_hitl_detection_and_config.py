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

"""Two things a host with its own configuration tree and nested toolsets needed.

* ``FireflyAgent._detect_hitl`` looked one level deep: a ``BaseTool`` with ``requires_approval``,
  a ``ToolKit``, an ``ApprovalRequiredToolset`` or a toolset with a ``.tools`` dict. A
  ``CombinedToolset`` / ``FilteredToolset`` / ``WrapperToolset`` wrapping an approval tool
  defeated it, and a tool that paused by raising ``CallDeferred`` from its body (a colleague
  ask, an out-of-band job) was invisible to it — so the run crashed with pydantic-ai's
  ``UserError`` at the first pause instead of surfacing ``DeferredToolRequests``. Hosts passed
  ``hitl=True`` unconditionally. Detection now recurses through ``.toolsets`` / ``.wrapped``
  and honours ``BaseTool.defers``.
* ``FireflyAgenticConfig`` was read only through the module singleton, which had no setter, so
  a host that built the settings object from its own tree (a PyFly ``pyfly.yaml``) could not hand
  it to the framework: ``usage_tracker_max_records`` stayed at 10 000 per process and
  ``default_model`` at the framework's default. ``set_config()`` installs an instance and
  ``FireflyAgent(config=...)`` scopes one to an agent.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.exceptions import CallDeferred
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.toolsets import CombinedToolset, FilteredToolset, FunctionToolset, WrapperToolset

from fireflyframework_agentic.agents.base import FireflyAgent, is_deferred
from fireflyframework_agentic.agents.builtin_middleware import LoggingMiddleware
from fireflyframework_agentic.config import FireflyAgenticConfig, get_config, reset_config, set_config
from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec
from fireflyframework_agentic.tools.toolkit import ToolKit


def _model_calling(tool_name: str, args: dict[str, Any]) -> FunctionModel:
    state = {"n": 0}

    def fn(messages: Any, info: Any) -> ModelResponse:
        state["n"] += 1
        if state["n"] == 1:
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=args, tool_call_id="c1")])
        return ModelResponse(parts=[TextPart("done")])

    return FunctionModel(fn)


class _Approval(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            "delete", description="d", parameters=[ParameterSpec(name="name", python_type=str)], requires_approval=True
        )

    async def _execute(self, **kwargs: Any) -> Any:
        return "deleted"


class _AskColleague(BaseTool):
    """Pauses the run from inside the body, the way a delegation tool does."""

    def __init__(self, *, defers: bool) -> None:
        super().__init__(
            "ask_colleague", description="ask", parameters=[ParameterSpec(name="q", python_type=str)], defers=defers
        )

    async def _execute(self, **kwargs: Any) -> Any:
        raise CallDeferred()


class TestDetectHitl:
    def test_a_wrapped_approval_toolset_is_found(self) -> None:
        inner = ToolKit("kit", tools=[_Approval()]).as_toolset()
        combined = CombinedToolset([inner])
        filtered = FilteredToolset(combined, lambda ctx, tool: True)
        assert FireflyAgent._detect_hitl((), [filtered]) is True
        assert FireflyAgent._detect_hitl((), [WrapperToolset(combined)]) is True

    def test_a_toolset_without_approval_tools_is_not_found(self) -> None:
        plain = FunctionToolset()

        @plain.tool
        def echo(x: str) -> str:
            return x

        assert FireflyAgent._detect_hitl((), [CombinedToolset([plain])]) is False

    def test_a_deferring_tool_is_found_by_declaration(self) -> None:
        assert FireflyAgent._detect_hitl([_AskColleague(defers=True)], ()) is True
        assert FireflyAgent._detect_hitl([_AskColleague(defers=False)], ()) is False
        assert FireflyAgent._detect_hitl([ToolKit("k", tools=[_AskColleague(defers=True)])], ()) is True

    async def test_a_deferring_tool_pauses_the_run_without_hitl_true(self) -> None:
        agent = FireflyAgent(
            "lead",
            model=_model_calling("ask_colleague", {"q": "help"}),
            tools=[_AskColleague(defers=True)],
            auto_register=False,
        )
        result = await agent.run("go")
        assert is_deferred(result)
        assert isinstance(result.output, DeferredToolRequests)
        assert [c.tool_name for c in result.output.calls] == ["ask_colleague"]


class TestSetConfig:
    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def test_set_config_installs_the_instance_get_config_returns(self) -> None:
        cfg = FireflyAgenticConfig(usage_tracker_max_records=1, default_model="anthropic:claude-opus-5")
        set_config(cfg)
        assert get_config() is cfg
        assert get_config().usage_tracker_max_records == 1

    def test_set_config_rejects_anything_else(self) -> None:
        with pytest.raises(TypeError):
            set_config({"default_model": "x"})  # type: ignore[arg-type]

    def test_reset_clears_an_installed_instance(self) -> None:
        set_config(FireflyAgenticConfig(usage_tracker_max_records=1))
        reset_config()
        assert get_config().usage_tracker_max_records != 1


class TestAgentConfig:
    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def test_an_explicit_config_reaches_the_agent(self) -> None:
        cfg = FireflyAgenticConfig(default_model="test", max_retries=7, default_temperature=0.2)
        agent = FireflyAgent("scoped", config=cfg, auto_register=False)
        assert agent.config is cfg
        assert agent.agent.model_settings == {"temperature": 0.2}
        # The singleton is untouched: the config is scoped to the agent, not installed globally.
        assert get_config() is not cfg

    def test_the_agent_config_drives_the_default_middleware(self) -> None:
        cfg = FireflyAgenticConfig(default_model="test", observability_enabled=False)
        agent = FireflyAgent("scoped", config=cfg, auto_register=False)
        names = [type(m).__name__ for m in agent.middleware]
        assert names == ["LoggingMiddleware"]

    def test_without_an_explicit_config_the_singleton_is_used(self) -> None:
        set_config(FireflyAgenticConfig(default_model="test", default_temperature=0.9))
        agent = FireflyAgent("global", auto_register=False)
        assert agent.config is get_config()
        assert agent.agent.model_settings == {"temperature": 0.9}


class TestLoggingPreview:
    def test_preview_length_follows_the_content_setting(self) -> None:
        # When prompt/response content is stripped from spans, the log line must not carry it
        # either: one privacy switch, not two.
        assert (
            LoggingMiddleware.for_config(FireflyAgenticConfig(instrumentation_include_content=False))._preview_length
            == 0
        )
        assert (
            LoggingMiddleware.for_config(FireflyAgenticConfig(instrumentation_include_content=True))._preview_length
            == 80
        )

    def test_the_default_agent_middleware_hides_the_prompt_by_default(self) -> None:
        reset_config()
        try:
            agent = FireflyAgent("quiet", config=FireflyAgenticConfig(default_model="test"), auto_register=False)
            (logging_mw,) = [m for m in agent.middleware if isinstance(m, LoggingMiddleware)]
            assert logging_mw._preview_length == 0
        finally:
            reset_config()
