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

"""Tests for execution context."""

from __future__ import annotations

from fireflyframework_agentic.agents.context import AgentContext


class TestAgentContext:
    def test_context_creation(self):
        ctx = AgentContext(metadata={"key": "val"})
        assert ctx.correlation_id  # auto-generated UUID
        assert ctx.metadata["key"] == "val"

    def test_context_with_experiment(self):
        ctx = AgentContext(experiment_id="exp-1")
        assert ctx.experiment_id == "exp-1"
