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

"""Tests for agent delegation strategies."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.agents.delegation import RoundRobinStrategy
from fireflyframework_agentic.exceptions import DelegationError


class TestRoundRobinStrategy:
    @pytest.mark.asyncio
    async def test_cycles_through_agents(self):
        strategy = RoundRobinStrategy()
        agents = ["a", "b", "c"]
        results = [await strategy.select(agents, "prompt") for _ in range(6)]
        assert results == ["a", "b", "c", "a", "b", "c"]

    @pytest.mark.asyncio
    async def test_empty_agents_raises(self):
        strategy = RoundRobinStrategy()
        with pytest.raises(DelegationError):
            await strategy.select([], "prompt")


# -- CostAwareStrategy -------------------------------------------------------

from fireflyframework_agentic.agents.delegation import CostAwareStrategy  # noqa: E402


class _FakeAgent:
    def __init__(self, name: str, model_name: str = ""):
        self.name = name
        self.model_name = model_name


class TestCostAwareStrategy:
    async def test_picks_cheapest(self):
        strategy = CostAwareStrategy()
        agents = [
            _FakeAgent("expensive", "openai:gpt-4o"),
            _FakeAgent("cheap", "openai:gpt-4o-mini"),
            _FakeAgent("mid", "openai:gpt-4.1"),
        ]
        selected = await strategy.select(agents, "hello")
        assert selected.name == "cheap"

    async def test_empty_raises(self):
        strategy = CostAwareStrategy()
        with pytest.raises(DelegationError):
            await strategy.select([], "hello")

    async def test_unknown_model_gets_mid_tier(self):
        strategy = CostAwareStrategy()
        agents = [
            _FakeAgent("custom", "custom:my-model"),
            _FakeAgent("cheap", "openai:gpt-4o-mini"),
        ]
        selected = await strategy.select(agents, "hello")
        assert selected.name == "cheap"

    async def test_single_agent(self):
        strategy = CostAwareStrategy()
        agents = [_FakeAgent("only", "openai:gpt-4o")]
        selected = await strategy.select(agents, "hello")
        assert selected.name == "only"

    async def test_provider_prefix_stripped(self):
        """Model names like 'openai:gpt-4o-mini' should match after stripping prefix."""
        strategy = CostAwareStrategy()
        agents = [
            _FakeAgent("a", "anthropic:claude-4-opus"),
            _FakeAgent("b", "openai:gpt-4.1-nano"),
        ]
        selected = await strategy.select(agents, "hello")
        assert selected.name == "b"  # nano = tier 0, cheapest

    async def test_no_model_name(self):
        strategy = CostAwareStrategy()
        agents = [_FakeAgent("no_model", ""), _FakeAgent("cheap", "gpt-4o-mini")]
        selected = await strategy.select(agents, "hello")
        assert selected.name == "cheap"  # empty model = tier 3, mini = tier 1


# -- ContentBasedStrategy ----------------------------------------------------

from fireflyframework_agentic.agents.delegation import ContentBasedStrategy  # noqa: E402


class TestContentBasedStrategy:
    async def test_single_agent_skips_llm(self):
        strategy = ContentBasedStrategy()
        agents = [_FakeAgent("only", "test")]
        selected = await strategy.select(agents, "hello")
        assert selected.name == "only"

    async def test_empty_raises(self):
        strategy = ContentBasedStrategy()
        with pytest.raises(DelegationError):
            await strategy.select([], "hello")

    async def test_falls_back_on_error(self):
        """When LLM routing fails, falls back to first agent."""
        strategy = ContentBasedStrategy(model="nonexistent:model")
        agents = [_FakeAgent("first"), _FakeAgent("second")]
        selected = await strategy.select(agents, "hello")
        assert selected.name == "first"
