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

"""Tests for pre-built template agent factories."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.registry import agent_registry
from fireflyframework_agentic.agents.templates.classifier import (
    ClassificationResult,
    create_classifier_agent,
)
from fireflyframework_agentic.agents.templates.conversational import (
    create_conversational_agent,
)
from fireflyframework_agentic.agents.templates.extractor import (
    create_extractor_agent,
)
from fireflyframework_agentic.agents.templates.router import (
    RoutingDecision,
    create_router_agent,
)
from fireflyframework_agentic.agents.templates.summarizer import (
    create_summarizer_agent,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the agent registry before each test to prevent name collisions."""
    agent_registry.clear()
    yield
    agent_registry.clear()


# ---------------------------------------------------------------------------
# SummarizerAgent
# ---------------------------------------------------------------------------


class TestSummarizerAgent:
    def test_default_creation(self) -> None:
        agent = create_summarizer_agent(model="test")
        assert isinstance(agent, FireflyAgent)
        assert agent.name == "summarizer"
        assert "summarizer" in agent.tags
        assert "template" in agent.tags
        assert agent_registry.has("summarizer")

    def test_custom_name_and_options(self) -> None:
        agent = create_summarizer_agent(
            name="my-summarizer",
            model="test",
            max_length="detailed",
            style="academic",
            output_format="bullets",
        )
        assert agent.name == "my-summarizer"
        assert "detailed" in agent.description
        assert "academic" in agent.description

    def test_extra_instructions(self) -> None:
        agent = create_summarizer_agent(
            name="ext-sum",
            model="test",
            extra_instructions="Always include the document title.",
        )
        assert agent.name == "ext-sum"

    def test_no_auto_register(self) -> None:
        agent = create_summarizer_agent(name="no-reg", model="test", auto_register=False)
        assert agent.name == "no-reg"
        assert not agent_registry.has("no-reg")


# ---------------------------------------------------------------------------
# ClassifierAgent
# ---------------------------------------------------------------------------


class TestClassifierAgent:
    def test_default_creation(self) -> None:
        agent = create_classifier_agent(["spam", "ham", "promo"], model="test")
        assert isinstance(agent, FireflyAgent)
        assert agent.name == "classifier"
        assert "classifier" in agent.tags
        assert "template" in agent.tags
        assert "spam" in agent.description
        assert agent_registry.has("classifier")

    def test_with_descriptions(self) -> None:
        agent = create_classifier_agent(
            ["invoice", "receipt", "letter"],
            name="doc-classifier",
            model="test",
            descriptions={
                "invoice": "A bill requesting payment",
                "receipt": "Proof of payment",
                "letter": "General correspondence",
            },
        )
        assert agent.name == "doc-classifier"

    def test_classification_result_model(self) -> None:
        result = ClassificationResult(category="spam", confidence=0.95, reasoning="test")
        assert result.category == "spam"
        assert result.confidence == 0.95

    def test_no_auto_register(self) -> None:
        create_classifier_agent(["a", "b"], name="no-reg-cls", model="test", auto_register=False)
        assert not agent_registry.has("no-reg-cls")


# ---------------------------------------------------------------------------
# ExtractorAgent
# ---------------------------------------------------------------------------


class TestExtractorAgent:
    def test_default_creation(self) -> None:
        class InvoiceData(BaseModel):
            vendor: str = ""
            total: float = 0.0

        agent = create_extractor_agent(InvoiceData, model="test")
        assert isinstance(agent, FireflyAgent)
        assert agent.name == "extractor"
        assert "extractor" in agent.tags
        assert "InvoiceData" in agent.description
        assert agent_registry.has("extractor")

    def test_with_field_descriptions(self) -> None:
        class Receipt(BaseModel):
            store: str = ""
            amount: float = 0.0

        agent = create_extractor_agent(
            Receipt,
            name="receipt-extractor",
            model="test",
            field_descriptions={
                "store": "The name of the store or merchant",
                "amount": "The total amount paid",
            },
        )
        assert agent.name == "receipt-extractor"

    def test_no_auto_register(self) -> None:
        class Simple(BaseModel):
            value: str = ""

        create_extractor_agent(Simple, name="no-reg-ext", model="test", auto_register=False)
        assert not agent_registry.has("no-reg-ext")


# ---------------------------------------------------------------------------
# ConversationalAgent
# ---------------------------------------------------------------------------


class TestConversationalAgent:
    def test_default_creation(self) -> None:
        agent = create_conversational_agent(model="test")
        assert isinstance(agent, FireflyAgent)
        assert agent.name == "assistant"
        assert "conversational" in agent.tags
        assert "template" in agent.tags
        assert agent_registry.has("assistant")

    def test_custom_personality_and_domain(self) -> None:
        agent = create_conversational_agent(
            name="health-bot",
            model="test",
            personality="empathetic and careful",
            domain="healthcare",
        )
        assert agent.name == "health-bot"
        assert "healthcare" in agent.description

    def test_with_memory(self) -> None:
        from fireflyframework_agentic.memory.manager import MemoryManager

        mem = MemoryManager()
        agent = create_conversational_agent(name="mem-agent", model="test", memory=mem)
        assert agent.memory is mem

    def test_no_auto_register(self) -> None:
        create_conversational_agent(name="no-reg-conv", model="test", auto_register=False)
        assert not agent_registry.has("no-reg-conv")


# ---------------------------------------------------------------------------
# RouterAgent
# ---------------------------------------------------------------------------


class TestRouterAgent:
    def test_default_creation(self) -> None:
        agent = create_router_agent(
            {
                "billing": "Handles billing questions",
                "technical": "Handles technical support",
            },
            model="test",
        )
        assert isinstance(agent, FireflyAgent)
        assert agent.name == "router"
        assert "router" in agent.tags
        assert "template" in agent.tags
        assert "billing" in agent.description
        assert agent_registry.has("router")

    def test_with_fallback(self) -> None:
        agent = create_router_agent(
            {"sales": "Sales inquiries", "support": "General support"},
            name="my-router",
            model="test",
            fallback_agent="support",
        )
        assert agent.name == "my-router"

    def test_routing_decision_model(self) -> None:
        decision = RoutingDecision(target_agent="billing", confidence=0.9, reasoning="test")
        assert decision.target_agent == "billing"
        assert decision.confidence == 0.9

    def test_no_auto_register(self) -> None:
        create_router_agent({"a": "desc"}, name="no-reg-rtr", model="test", auto_register=False)
        assert not agent_registry.has("no-reg-rtr")


# ---------------------------------------------------------------------------
# Import from agents package
# ---------------------------------------------------------------------------


class TestTemplateImports:
    """Verify that all template factories are importable from the agents package."""

    def test_imports_from_agents(self) -> None:
        from fireflyframework_agentic.agents import (
            create_classifier_agent,
            create_conversational_agent,
            create_extractor_agent,
            create_router_agent,
            create_summarizer_agent,
        )

        assert callable(create_summarizer_agent)
        assert callable(create_classifier_agent)
        assert callable(create_extractor_agent)
        assert callable(create_conversational_agent)
        assert callable(create_router_agent)


# ---------------------------------------------------------------------------
# Default tool auto-attachment
# ---------------------------------------------------------------------------


class TestTemplateDefaultTools:
    """Verify that templates auto-attach built-in tools when none are provided."""

    def test_conversational_has_default_tools(self) -> None:
        agent = create_conversational_agent(name="conv-dt", model="test")
        # DateTimeTool + CalculatorTool + TextTool = 3 tools
        assert len(agent.agent._function_toolset.tools) == 3

    def test_summarizer_has_default_tools(self) -> None:
        agent = create_summarizer_agent(name="sum-dt", model="test")
        # TextTool = 1 tool
        assert len(agent.agent._function_toolset.tools) == 1

    def test_extractor_has_default_tools(self) -> None:
        from pydantic import BaseModel

        class Item(BaseModel):
            name: str = ""

        agent = create_extractor_agent(Item, name="ext-dt", model="test")
        # JsonTool + TextTool = 2 tools
        assert len(agent.agent._function_toolset.tools) == 2

    def test_classifier_has_no_default_tools(self) -> None:
        agent = create_classifier_agent(["a", "b"], name="cls-dt", model="test")
        assert len(agent.agent._function_toolset.tools) == 0

    def test_router_has_no_default_tools(self) -> None:
        agent = create_router_agent({"a": "desc"}, name="rtr-dt", model="test")
        assert len(agent.agent._function_toolset.tools) == 0

    def test_explicit_tools_override_defaults(self) -> None:
        """When the user passes explicit tools, default tools are NOT added."""

        async def custom_tool(x: str) -> str:
            return x

        agent = create_conversational_agent(name="conv-custom", model="test", tools=[custom_tool])
        # Only the user's 1 tool, not the 3 defaults
        assert len(agent.agent._function_toolset.tools) == 1
