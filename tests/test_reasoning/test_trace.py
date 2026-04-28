# Copyright 2026 Firefly Software Solutions Inc
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

"""Tests for reasoning trace."""

from __future__ import annotations

from fireflyframework_agentic.reasoning.trace import (
    ActionStep,
    ObservationStep,
    ReasoningTrace,
    ThoughtStep,
)


class TestReasoningTrace:
    def test_add_steps(self):
        trace = ReasoningTrace(pattern_name="react")
        trace.add_step(ThoughtStep(content="thinking"))
        trace.add_step(ActionStep(tool_name="search", tool_args={"q": "test"}))
        trace.add_step(ObservationStep(content="result"))
        assert len(trace.steps) == 3

    def test_step_kinds(self):
        thought = ThoughtStep(content="x")
        action = ActionStep(tool_name="t")
        obs = ObservationStep(content="z")
        assert thought.kind == "thought"
        assert action.kind == "action"
        assert obs.kind == "observation"

    def test_complete(self):
        trace = ReasoningTrace(pattern_name="test")
        assert trace.completed_at is None
        trace.complete()
        assert trace.completed_at is not None
