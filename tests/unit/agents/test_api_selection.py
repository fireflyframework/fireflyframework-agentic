"""Compatibility boundaries around the PydanticAI v2 upgrade."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.native_tools import WebSearchTool

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.config import FireflyAgenticConfig
from fireflyframework_agentic.model_utils import detect_model_family, get_model_identifier
from fireflyframework_agentic.observability.cost_resolvers import CostContext, genai_prices_cost


@pytest.mark.parametrize(
    ("model_id", "model_type"),
    [
        ("openai:gpt-4o", OpenAIChatModel),
        ("openai-chat:gpt-4o", OpenAIChatModel),
        ("openai-responses:gpt-6-sol", OpenAIResponsesModel),
        ("azure:deployment", OpenAIChatModel),
        ("azure-chat:deployment", OpenAIChatModel),
        ("azure-responses:deployment", OpenAIResponsesModel),
    ],
)
def test_agent_preserves_explicit_api_selection(monkeypatch, model_id, model_type):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("OPENAI_API_VERSION", "2024-10-21")
    agent = FireflyAgent("api", model=model_id, auto_register=False)
    assert isinstance(agent.agent.model, model_type)


@pytest.mark.parametrize("prefix", ["openai-chat", "openai-responses", "azure-chat", "azure-responses"])
def test_api_selector_keeps_provider_identity_for_family_and_cost(prefix):
    provider = "azure" if prefix.startswith("azure") else "openai"
    assert get_model_identifier(f"{prefix}:deployment") == f"{provider}:deployment"
    assert detect_model_family(f"{prefix}:deployment") == "openai"


@pytest.mark.parametrize("prefix", ["openai-chat", "openai-responses"])
def test_explicit_api_selector_is_priceable(prefix):
    cost = genai_prices_cost(CostContext(model=f"{prefix}:gpt-4o", input_tokens=1000, output_tokens=500))
    assert cost == pytest.approx(0.0075)


async def test_native_capabilities_reach_the_model():
    def respond(messages, info):
        assert any(isinstance(tool, WebSearchTool) for tool in info.model_request_parameters.native_tools)
        return ModelResponse(parts=[TextPart("Found documentation")])

    model = FunctionModel(respond)
    agent = FireflyAgent("search", model=model, capabilities=[NativeTool(WebSearchTool())], auto_register=False)
    assert (await agent.run("Search for documentation")).output == "Found documentation"


async def test_upgrade_keeps_early_output_without_executing_extra_tool_side_effects():
    class Answer(BaseModel):
        value: str

    calls = []

    def side_effect() -> str:
        calls.append("executed")
        return "done"

    def respond(messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, {"value": "answer"}, "output"),
                ToolCallPart("side_effect", {}, "effect"),
            ]
        )

    agent = FireflyAgent(
        "early", model=FunctionModel(respond), tools=[side_effect], output_type=Answer, auto_register=False
    )
    result = await agent.run("Answer")
    assert result.output.value == "answer"
    assert calls == []


def test_legacy_instrumentation_configuration_constructs_an_agent():
    cfg = FireflyAgenticConfig(instrumentation_version=1, instrumentation_event_mode="logs")
    agent = FireflyAgent("legacy-traces", model="test", config=cfg, auto_register=False)
    assert agent.run_sync("hello").output
