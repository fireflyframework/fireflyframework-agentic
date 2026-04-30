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

"""Tests for FireflyAgent base class."""

from __future__ import annotations

from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent


class TestFireflyAgent:
    def test_agent_creation(self):
        agent = FireflyAgent(name="test", model="test", auto_register=False)
        assert agent.name == "test"

    def test_agent_with_instructions(self):
        agent = FireflyAgent(
            name="test2",
            model="test",
            instructions="You are helpful.",
            auto_register=False,
        )
        assert agent.description == ""  # instructions stored on inner agent

    def test_agent_tags(self):
        agent = FireflyAgent(name="test3", model="test", tags=["writer", "creative"], auto_register=False)
        assert "writer" in agent.tags

    def test_agent_accepts_model_object(self):
        """FireflyAgent should accept a pydantic_ai Model instance, not just strings."""

        class _StubModel(Model):
            """Minimal Model subclass for testing."""

            async def request(self, *args, **kwargs):
                raise NotImplementedError

            @property
            def model_name(self) -> str:
                return "stub-model"

            @property
            def system(self) -> str:
                return "stub"

        stub = _StubModel()
        agent = FireflyAgent(name="model_obj_test", model=stub, auto_register=False)
        assert agent.name == "model_obj_test"
        # The inner pydantic_ai Agent should have received the Model object
        assert agent.agent.model is stub
