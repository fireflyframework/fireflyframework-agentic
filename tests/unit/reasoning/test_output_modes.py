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

"""Reasoning structured-output modes (SP-5).

The real-model run paths wrap the structured ``output_type`` in a pydantic-ai
output mode selected by the per-pattern ``output_mode`` argument or the
framework-wide ``reasoning_output_mode`` config value. The model-less fallback
(duck-typed agents) is unaffected -- it cannot make an LLM call, so it keeps
parsing text via ``_fallback_parse``.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import NativeOutput, PromptedOutput, ToolOutput

from fireflyframework_agentic.config import reset_config
from fireflyframework_agentic.exceptions import ReasoningError
from fireflyframework_agentic.reasoning import (
    ChainOfThoughtPattern,
    GoalDecompositionPattern,
    PlanAndExecutePattern,
    ReActPattern,
    ReflexionPattern,
    TreeOfThoughtsPattern,
)
from fireflyframework_agentic.reasoning.models import ReasoningThought

ALL_PATTERNS = [
    ReActPattern,
    ChainOfThoughtPattern,
    PlanAndExecutePattern,
    TreeOfThoughtsPattern,
    ReflexionPattern,
    GoalDecompositionPattern,
]

MODE_TO_CLASS = {"tool": ToolOutput, "native": NativeOutput, "prompted": PromptedOutput}


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch: pytest.MonkeyPatch):
    """Ensure each test starts from a pristine, env-free config."""
    monkeypatch.delenv("FIREFLY_AGENTIC_REASONING_OUTPUT_MODE", raising=False)
    reset_config()
    yield
    reset_config()


def test_default_returns_bare_type():
    """No mode configured -> pydantic-ai's default (bare BaseModel type)."""
    pattern = ReActPattern()
    assert pattern._wrap_output_type(ReasoningThought) is ReasoningThought


@pytest.mark.parametrize("mode,cls", list(MODE_TO_CLASS.items()))
def test_per_pattern_mode_wraps(mode: str, cls: type):
    pattern = ReActPattern(output_mode=mode)  # type: ignore[arg-type]
    wrapped = pattern._wrap_output_type(ReasoningThought)
    assert isinstance(wrapped, cls)


@pytest.mark.parametrize("pattern_cls", ALL_PATTERNS)
def test_every_pattern_accepts_and_threads_output_mode(pattern_cls: type):
    """All concrete patterns forward output_mode to the base class."""
    pattern = pattern_cls(output_mode="native")
    assert pattern._output_mode == "native"
    assert isinstance(pattern._wrap_output_type(ReasoningThought), NativeOutput)


def test_config_default_applies_when_arg_is_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FIREFLY_AGENTIC_REASONING_OUTPUT_MODE", "prompted")
    reset_config()
    pattern = ReActPattern()  # no per-pattern override
    assert isinstance(pattern._wrap_output_type(ReasoningThought), PromptedOutput)


def test_per_pattern_arg_overrides_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FIREFLY_AGENTIC_REASONING_OUTPUT_MODE", "prompted")
    reset_config()
    pattern = ReActPattern(output_mode="tool")
    assert isinstance(pattern._wrap_output_type(ReasoningThought), ToolOutput)


def test_unknown_mode_raises():
    pattern = ReActPattern()
    pattern._output_mode = "bogus"  # type: ignore[assignment]
    with pytest.raises(ReasoningError, match="Unknown reasoning output mode"):
        pattern._wrap_output_type(ReasoningThought)


@pytest.mark.asyncio
async def test_firefly_route_passes_wrapped_spec_and_returns_model():
    """Branch 1 (FireflyAgent route) forwards the wrapped output spec via run()
    and still returns the validated model."""
    captured: dict[str, Any] = {}

    class _Result:
        output = ReasoningThought(content="hi", is_final=True, final_answer="ok")

    class _FakeFireflyAgent:
        agent = object()  # non-None -> selects the FireflyAgent route

        async def run(self, prompt: Any, **kwargs: Any) -> _Result:
            captured.update(kwargs)
            return _Result()

    pattern = ReActPattern(output_mode="prompted")
    out = await pattern._structured_run(_FakeFireflyAgent(), "p", ReasoningThought)

    assert isinstance(captured["output_type"], PromptedOutput)
    assert isinstance(out, ReasoningThought)
    assert out.final_answer == "ok"


@pytest.mark.asyncio
async def test_firefly_route_default_passes_bare_type():
    captured: dict[str, Any] = {}

    class _Result:
        output = ReasoningThought(content="hi")

    class _FakeFireflyAgent:
        agent = object()

        async def run(self, prompt: Any, **kwargs: Any) -> _Result:
            captured.update(kwargs)
            return _Result()

    pattern = ReActPattern()  # no mode
    await pattern._structured_run(_FakeFireflyAgent(), "p", ReasoningThought)
    assert captured["output_type"] is ReasoningThought
