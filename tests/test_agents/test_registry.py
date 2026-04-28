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

"""Tests for agent registry."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.registry import AgentRegistry


class TestAgentRegistry:
    def test_register_and_get(self):
        registry = AgentRegistry()
        agent = FireflyAgent(name="test_agent", model="test", auto_register=False)
        registry.register(agent)
        assert registry.get("test_agent") is agent

    def test_has_agent(self):
        registry = AgentRegistry()
        agent = FireflyAgent(name="test_agent", model="test", auto_register=False)
        registry.register(agent)
        assert registry.has("test_agent")
        assert not registry.has("nonexistent")

    def test_get_nonexistent_raises(self):
        from fireflyframework_agentic.exceptions import AgentNotFoundError

        registry = AgentRegistry()
        with pytest.raises(AgentNotFoundError):
            registry.get("nonexistent")

    def test_list_agents(self):
        registry = AgentRegistry()
        agent = FireflyAgent(name="a1", model="test", auto_register=False)
        registry.register(agent)
        agents = registry.list_agents()
        assert len(agents) >= 1
