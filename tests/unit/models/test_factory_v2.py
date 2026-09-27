"""ModelSpec compatibility at the PydanticAI 2 provider/settings boundary."""

from __future__ import annotations

import httpx
import pytest
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

from fireflyframework_agentic.models import (
    Credential,
    ModelFactory,
    ModelOptions,
    ModelOptionsError,
    ModelSpec,
    capabilities_for,
    model_settings_for,
    profile_for,
)


def test_portable_spec_options_override_legacy_settings():
    spec = ModelSpec(
        "openai-responses",
        "gpt-6-luna",
        settings={"maxTokens": 10},
        options=ModelOptions(max_tokens=100, reasoning="low"),
    )
    assert model_settings_for(spec) == {"max_tokens": 100, "openai_reasoning_effort": "low"}


def test_portable_spec_options_respect_explicit_api_class():
    spec = ModelSpec(
        "openai", "gpt-6-luna", model_class="OpenAIResponsesModel", options=ModelOptions(output_verbosity="low")
    )
    assert model_settings_for(spec)["openai_text_verbosity"] == "low"


def test_portable_spec_options_use_azure_deployment_profile():
    spec = ModelSpec(
        "azure-responses",
        "tenant-deployment",
        profile_overrides={"supports_thinking": True},
        options=ModelOptions(reasoning="low"),
    )
    assert model_settings_for(spec)["openai_reasoning_effort"] == "low"


def test_portable_spec_options_respect_explicit_capability_denial():
    from fireflyframework_agentic.models import ModelCapabilities

    spec = ModelSpec(
        "openai-responses",
        "gpt-6-luna",
        capabilities=ModelCapabilities(thinking=False),
        options=ModelOptions(reasoning="low"),
    )
    with pytest.raises(ModelOptionsError, match="reasoning"):
        model_settings_for(spec)


def test_portable_spec_options_respect_explicit_sampling_and_budget_limits():
    from fireflyframework_agentic.models import ModelCapabilities

    sampling = ModelSpec(
        "openai", "gpt-4o", capabilities=ModelCapabilities(refuses_sampling=True), options=ModelOptions(temperature=0.2)
    )
    with pytest.raises(ModelOptionsError, match="temperature"):
        model_settings_for(sampling)
    budget = ModelSpec(
        "anthropic",
        "claude-haiku-4-5",
        capabilities=ModelCapabilities(thinking=True, thinking_style="budget", max_thinking_budget_tokens=2048),
        options=ModelOptions(max_tokens=8192, reasoning_budget_tokens=4096),
    )
    with pytest.raises(ModelOptionsError, match="reasoning_budget_tokens"):
        model_settings_for(budget)


@pytest.mark.parametrize(
    ("provider", "model_type"),
    [
        ("openai", OpenAIChatModel),
        ("openai-chat", OpenAIChatModel),
        ("openai-responses", OpenAIResponsesModel),
        ("azure", OpenAIChatModel),
        ("azure-chat", OpenAIChatModel),
        ("azure-responses", OpenAIResponsesModel),
    ],
)
async def test_provider_alias_selects_the_requested_api(provider: str, model_type: type) -> None:
    spec = ModelSpec(
        provider=provider,
        model="gpt-6-sol",
        credential=Credential.api_key("test-key"),
        base_url="https://test.openai.azure.com" if provider.startswith("azure") else None,
        api_version="2025-04-01-preview" if provider.startswith("azure") else None,
    )
    model = await ModelFactory().build(spec)
    assert isinstance(model, model_type)
    if provider.startswith("azure"):
        assert model.provider.name == "azure"


async def test_explicit_model_class_can_override_the_provider_api_default() -> None:
    model = await ModelFactory().build(
        ModelSpec(
            provider="openai-responses",
            model="gpt-4o",
            credential=Credential.api_key("test-key"),
            model_class="OpenAIChatModel",
        )
    )
    assert isinstance(model, OpenAIChatModel)


@pytest.mark.parametrize("env_key", [None, ""])
async def test_unknown_custom_endpoint_keeps_chat_default(monkeypatch, env_key) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    if env_key is not None:
        monkeypatch.setenv("OPENAI_API_KEY", env_key)
    model = await ModelFactory().build(
        ModelSpec(provider="local-gateway", model="custom", base_url="http://localhost/v1")
    )
    assert isinstance(model, OpenAIChatModel)


@pytest.mark.parametrize("provider", ["openai", "openai-responses"])
async def test_no_explicit_credential_reads_the_openai_environment(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-test-key")
    model = await ModelFactory().build(ModelSpec(provider=provider, model="gpt-6-sol"))
    assert model.client.api_key == "environment-test-key"


async def test_custom_endpoint_can_read_environment_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-test-key")
    model = await ModelFactory().build(
        ModelSpec(provider="local-gateway", model="custom", base_url="https://gateway.example/v1")
    )
    assert model.client.api_key == "environment-test-key"


async def test_no_explicit_credential_reads_the_anthropic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "environment-test-key")
    model = await ModelFactory().build(ModelSpec(provider="anthropic", model="claude-sonnet-5"))
    assert model.client.api_key == "environment-test-key"


async def test_azure_responses_accepts_a_v1_endpoint_without_api_version() -> None:
    model = await ModelFactory().build(
        ModelSpec(
            provider="azure-responses",
            model="gpt-6-sol",
            credential=Credential.api_key("test-key"),
            base_url="https://test.openai.azure.com/openai/v1/",
        )
    )
    assert isinstance(model, OpenAIResponsesModel)
    assert model.provider.name == "azure"
    assert str(model.client.base_url) == "https://test.openai.azure.com/openai/v1/"
    assert "api-version" not in model.client.default_query


async def test_bedrock_can_use_the_sdk_environment_credential_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("boto3")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "environment-test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "environment-test-secret")
    model = await ModelFactory().build(
        ModelSpec(provider="bedrock", model="anthropic.claude-sonnet-5", region="us-east-1")
    )
    assert model.client.meta.region_name == "us-east-1"


def test_bedrock_profile_overrides_accept_provider_specific_fields() -> None:
    pytest.importorskip("boto3")
    profile = profile_for(
        ModelSpec(
            provider="bedrock",
            model="anthropic.claude-sonnet-5",
            profile_overrides={"bedrock_supports_tool_choice": False},
        )
    )
    assert profile is not None
    assert profile["bedrock_supports_tool_choice"] is False
    assert profile["bedrock_supports_prompt_caching"] is True


def test_mistral_overrides_use_the_common_profile_schema() -> None:
    profile = profile_for(
        ModelSpec(
            provider="mistral", model="mistral-large-latest", profile_overrides={"supports_json_schema_output": True}
        )
    )
    assert profile is not None
    assert profile["supports_json_schema_output"] is True


def test_native_responses_settings_survive_console_translation() -> None:
    settings = model_settings_for(
        ModelSpec(
            provider="openai-responses",
            model="gpt-6-sol",
            settings={
                "maxTokens": 2048,
                "openai_reasoning_effort": "xhigh",
                "openai_reasoning_mode": "standard",
                "openai_previous_response_id": "auto",
                "openai_store": False,
                "openai_service_tier": "priority",
                "parallel_tool_calls": False,
                "extra_body": {"metadata": {"workflow": "test"}},
            },
        )
    )
    assert settings == {
        "max_tokens": 2048,
        "openai_reasoning_effort": "xhigh",
        "openai_reasoning_mode": "standard",
        "openai_previous_response_id": "auto",
        "openai_store": False,
        "openai_service_tier": "priority",
        "parallel_tool_calls": False,
        "extra_body": {"metadata": {"workflow": "test"}},
    }


def test_native_settings_take_precedence_over_portable_thinking_aliases() -> None:
    spec = ModelSpec(
        provider="openai-responses",
        model="gpt-6-sol",
        settings={"thinkingBudgetTokens": 8192, "effort": "high", "openai_reasoning_effort": "none"},
    )
    assert model_settings_for(spec) == {"openai_reasoning_effort": "none"}


def test_native_timeout_object_is_not_coerced_to_float() -> None:
    timeout = httpx.Timeout(10.0, connect=2.0)
    spec = ModelSpec(provider="openai", model="gpt-4o", settings={"timeout": timeout})
    assert model_settings_for(spec)["timeout"] is timeout


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-6-sol-2026-09-01"])
def test_latest_openai_capabilities_enable_portable_effort(model: str) -> None:
    assert capabilities_for("openai-responses", model).thinking_style == "effort"
    settings = model_settings_for(ModelSpec(provider="openai-responses", model=model, settings={"effort": "high"}))
    assert settings == {"openai_reasoning_effort": "high"}


@pytest.mark.parametrize("model", ["gpt-5.6", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna"])
def test_portable_minimal_effort_uses_low_when_the_profile_requires_it(model: str) -> None:
    spec = ModelSpec(provider="openai-responses", model=model, settings={"thinkingBudgetTokens": 1024})
    assert model_settings_for(spec) == {"openai_reasoning_effort": "low"}


def test_native_anthropic_thinking_retains_the_sampling_exclusion() -> None:
    spec = ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5",
        settings={
            "anthropic_thinking": {"type": "enabled", "budget_tokens": 2048},
            "temperature": 0.3,
            "top_p": 0.9,
            "top_k": 5,
            "max_tokens": 4096,
        },
    )
    assert model_settings_for(spec) == {
        "anthropic_thinking": {"type": "enabled", "budget_tokens": 2048},
        "max_tokens": 4096,
    }


def test_native_disabled_thinking_wins_over_console_budget_and_keeps_sampling() -> None:
    spec = ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5",
        settings={"anthropic_thinking": {"type": "disabled"}, "thinkingBudgetTokens": 2048, "temperature": 0.3},
    )
    assert model_settings_for(spec) == {"anthropic_thinking": {"type": "disabled"}, "temperature": 0.3}


def test_bedrock_thinking_preserves_other_native_request_fields() -> None:
    native_fields = {"custom_field": True, "output_config": {"format": "json"}}
    spec = ModelSpec(
        provider="bedrock",
        model="anthropic.claude-sonnet-5",
        settings={"effort": "high", "bedrock_additional_model_requests_fields": native_fields},
    )
    assert model_settings_for(spec) == {
        "bedrock_additional_model_requests_fields": {
            "custom_field": True,
            "thinking": {"type": "adaptive"},
            "output_config": {"format": "json", "effort": "high"},
        }
    }
    assert native_fields == {"custom_field": True, "output_config": {"format": "json"}}


async def test_overrides_keep_provider_fields_and_accept_optional_typed_dict_keys() -> None:
    spec = ModelSpec(
        provider="openai-responses",
        model="gpt-6-sol",
        credential=Credential.api_key("test-key"),
        profile_overrides={"openai_responses_requires_store_false": True, "supports_json_schema_output": False},
    )
    profile = profile_for(spec)
    assert profile is not None
    assert profile["openai_responses_requires_store_false"] is True
    model = await ModelFactory().build(spec)
    assert model.profile["openai_supports_reasoning"] is True
    assert model.profile["openai_responses_supports_reasoning_mode"] is True
    assert model.profile["supports_json_schema_output"] is False
