"""Firefly-owned options validate and reach the selected provider without disappearing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from fireflyframework_agentic.models import ModelOptions, ModelOptionsError, resolve_model_options


@pytest.mark.parametrize(
    "values",
    [
        {"max_tokens": 0},
        {"max_tokens": True},
        {"temperature": -1},
        {"temperature": 3},
        {"top_p": 1.1},
        {"top_k": 0},
        {"request_timeout": 0},
        {"reasoning_budget_tokens": 0},
        {"reasoning": "turbo"},
        {"output_verbosity": "huge"},
        {"stop_sequences": [""]},
        {"openai_reasoning_effort": "high"},
    ],
)
def test_invalid_options_fail_at_configuration(values: dict) -> None:
    with pytest.raises(ValidationError):
        ModelOptions(**values)


def test_options_are_frozen_and_do_not_retain_mutable_stop_sequences() -> None:
    stops = ["END"]
    options = ModelOptions(stop_sequences=stops)
    stops.append("OTHER")
    assert options.stop_sequences == ("END",)
    with pytest.raises(ValidationError):
        options.max_tokens = 1


def test_empty_options_preserve_provider_defaults() -> None:
    assert resolve_model_options("openai:gpt-4o", ModelOptions()) == {}


def test_legacy_openai_chat_accepts_chat_only_options() -> None:
    options = ModelOptions(
        max_tokens=100, temperature=0.3, top_p=0.9, seed=7, stop_sequences=["END"], request_timeout=5
    )
    assert resolve_model_options("openai:gpt-4o", options) == {
        "max_tokens": 100,
        "temperature": 0.3,
        "top_p": 0.9,
        "seed": 7,
        "stop_sequences": ["END"],
        "timeout": 5.0,
    }


@pytest.mark.parametrize("provider", ["openai-responses", "azure-responses", "gateway/openai-responses"])
def test_responses_options_translate_to_native_settings(provider: str) -> None:
    settings = resolve_model_options(
        f"{provider}:gpt-6-sol",
        ModelOptions(reasoning="high", store_responses=False, output_verbosity="low", parallel_tool_calls=False),
    )
    assert settings == {
        "openai_reasoning_effort": "high",
        "openai_store": False,
        "openai_text_verbosity": "low",
        "parallel_tool_calls": False,
    }


@pytest.mark.parametrize("field", ["seed", "stop_sequences", "top_k"])
def test_responses_rejects_settings_it_cannot_send(field: str) -> None:
    value = ["END"] if field == "stop_sequences" else 7
    with pytest.raises(ModelOptionsError, match=field):
        resolve_model_options("openai-responses:gpt-6-sol", ModelOptions(**{field: value}))


def test_openai_minimal_uses_the_profile_equivalent() -> None:
    assert resolve_model_options("openai-responses:gpt-6-sol", ModelOptions(reasoning="minimal")) == {
        "openai_reasoning_effort": "low"
    }


def test_openai_none_keeps_sampling_when_the_model_supports_it() -> None:
    assert resolve_model_options("openai-chat:gpt-6-sol", ModelOptions(reasoning="none", temperature=0.2)) == {
        "openai_reasoning_effort": "none",
        "temperature": 0.2,
    }


@pytest.mark.parametrize(
    ("model", "values", "field"),
    [
        ("openai-responses:gpt-6-astra", {"reasoning": "none"}, "reasoning"),
        ("openai-responses:gpt-6-sol", {"temperature": 0.2}, "temperature"),
        ("openai:gpt-4o", {"reasoning": "high"}, "reasoning"),
        ("openai:gpt-4o", {"top_k": 10}, "top_k"),
        ("openai-responses:gpt-6-sol", {"reasoning_budget_tokens": 4096}, "reasoning_budget_tokens"),
        ("anthropic:claude-sonnet-5", {"temperature": 0.2}, "temperature"),
        ("anthropic:claude-sonnet-5", {"reasoning_budget_tokens": 4096}, "reasoning_budget_tokens"),
        ("anthropic:claude-haiku-4-5", {"seed": 7}, "seed"),
        ("anthropic:claude-haiku-4-5", {"reasoning": "high", "top_p": 0.9}, "top_p"),
        ("anthropic:claude-haiku-4-5", {"temperature": 1.2}, "temperature"),
        ("anthropic:claude-sonnet-4-6", {"reasoning": "xhigh"}, "reasoning"),
        ("google:gemini-2.5-pro", {"reasoning": "none"}, "reasoning"),
        ("google:gemini-3-flash-preview", {"reasoning": "none"}, "reasoning"),
        ("google:gemini-3-pro-preview", {"reasoning": "medium"}, "reasoning"),
        ("google:gemini-3-pro-preview", {"reasoning_budget_tokens": 4096}, "reasoning_budget_tokens"),
        ("google:gemini-2.5-flash", {"parallel_tool_calls": False}, "parallel_tool_calls"),
        ("google:gemini-2.5-flash", {"store_responses": False}, "store_responses"),
        ("mistral:mistral-small-latest", {"top_k": 10}, "top_k"),
        ("custom:future-model", {"reasoning": "high"}, "reasoning"),
        ("custom:gpt-6-sol", {"reasoning": "high"}, "reasoning"),
    ],
)
def test_incompatible_options_raise_instead_of_being_dropped(model: str, values: dict, field: str) -> None:
    with pytest.raises(ModelOptionsError, match=field):
        resolve_model_options(model, ModelOptions(**values))


def test_reasoning_level_and_exact_budget_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="reasoning"):
        ModelOptions(reasoning="high", reasoning_budget_tokens=4096)


def test_anthropic_adaptive_effort_and_budget_models_have_distinct_shapes() -> None:
    assert resolve_model_options("anthropic:claude-sonnet-5", ModelOptions(reasoning="high")) == {
        "anthropic_thinking": {"type": "adaptive"},
        "anthropic_effort": "high",
    }
    assert resolve_model_options(
        "anthropic:claude-haiku-4-5", ModelOptions(reasoning_budget_tokens=2048, max_tokens=4096)
    ) == {"anthropic_thinking": {"type": "enabled", "budget_tokens": 2048}, "max_tokens": 4096}


@pytest.mark.parametrize("budget", [512, 4096])
def test_anthropic_budget_must_fit_between_minimum_and_output_limit(budget: int) -> None:
    with pytest.raises(ModelOptionsError, match="reasoning_budget_tokens"):
        resolve_model_options(
            "anthropic:claude-haiku-4-5", ModelOptions(reasoning_budget_tokens=budget, max_tokens=4096)
        )


def test_anthropic_disabled_reasoning_preserves_sampling() -> None:
    assert resolve_model_options("anthropic:claude-haiku-4-5", ModelOptions(reasoning="none", temperature=0.4)) == {
        "anthropic_thinking": {"type": "disabled"},
        "temperature": 0.4,
    }


def test_google_thinking_uses_the_profile_selected_vocabulary() -> None:
    assert resolve_model_options("google:gemini-2.5-flash", ModelOptions(reasoning_budget_tokens=2048)) == {
        "google_thinking_config": {"thinking_budget": 2048}
    }
    assert resolve_model_options("google:gemini-2.5-flash", ModelOptions(reasoning="none")) == {
        "google_thinking_config": {"thinking_budget": 0}
    }
    assert resolve_model_options("google:gemini-3-pro-preview", ModelOptions(reasoning="minimal")) == {
        "google_thinking_config": {"thinking_level": "LOW"}
    }
    assert resolve_model_options("google-vertex:gemini-3.1-pro-preview", ModelOptions(reasoning="medium")) == {
        "google_thinking_config": {"thinking_level": "MEDIUM"}
    }


def test_unknown_provider_keeps_common_controls() -> None:
    assert resolve_model_options("custom:future-model", ModelOptions(max_tokens=50, temperature=0.2)) == {
        "max_tokens": 50,
        "temperature": 0.2,
    }


def test_model_instance_profile_drives_reasoning_for_custom_deployment_names() -> None:
    model = OpenAIResponsesModel(
        "private-deployment",
        provider=OpenAIProvider(api_key="test-key"),
        profile={
            "supports_thinking": True,
            "openai_supports_reasoning": True,
            "openai_supports_minimal_reasoning_effort": False,
        },
    )
    assert resolve_model_options(model, ModelOptions(reasoning="minimal")) == {"openai_reasoning_effort": "low"}
    assert resolve_model_options(WrapperModel(model), ModelOptions(store_responses=False)) == {"openai_store": False}


def test_model_profile_can_disable_a_known_models_reasoning() -> None:
    model = OpenAIResponsesModel(
        "gpt-6-sol", provider=OpenAIProvider(api_key="test-key"), profile={"supports_thinking": False}
    )
    with pytest.raises(ModelOptionsError, match="reasoning"):
        resolve_model_options(model, ModelOptions(reasoning="high"))


def test_native_profile_unsupported_settings_are_not_silently_discarded() -> None:
    model = OpenAIResponsesModel(
        "gpt-6-sol",
        provider=OpenAIProvider(api_key="test-key"),
        profile={"openai_unsupported_model_settings": ["parallel_tool_calls"]},
    )
    with pytest.raises(ModelOptionsError, match="parallel_tool_calls"):
        resolve_model_options(model, ModelOptions(parallel_tool_calls=False))


def test_native_profile_mandatory_store_false_rejects_storage() -> None:
    model = OpenAIResponsesModel(
        "gpt-6-sol",
        provider=OpenAIProvider(api_key="test-key"),
        profile={"openai_responses_requires_store_false": True},
    )
    with pytest.raises(ModelOptionsError, match="store_responses"):
        resolve_model_options(model, ModelOptions(store_responses=True))


def test_profile_overrides_on_an_uninstantiated_deployment_are_applied() -> None:
    assert resolve_model_options(
        "azure-responses:production-deployment",
        ModelOptions(reasoning="minimal"),
        profile={"supports_thinking": True, "openai_supports_minimal_reasoning_effort": False},
    ) == {"openai_reasoning_effort": "low"}


def test_unsupported_native_options_are_checked_after_translation() -> None:
    with pytest.raises(ModelOptionsError, match="store_responses"):
        resolve_model_options(
            "openai-responses:gpt-6-sol",
            ModelOptions(store_responses=False),
            profile={"openai_unsupported_model_settings": ["openai_store"]},
        )


def test_chat_verbosity_is_rejected_instead_of_disappearing() -> None:
    with pytest.raises(ModelOptionsError, match="output_verbosity"):
        resolve_model_options("openai:gpt-6-sol", ModelOptions(output_verbosity="low"))


def test_anthropic_profile_overrides_are_used_without_a_model_id_allowlist() -> None:
    model = AnthropicModel(
        "private-deployment",
        provider=AnthropicProvider(api_key="test-key"),
        profile={
            "supports_thinking": True,
            "anthropic_supports_adaptive_thinking": True,
            "anthropic_supports_effort": True,
        },
    )
    assert resolve_model_options(model, ModelOptions(reasoning="minimal")) == {
        "anthropic_thinking": {"type": "adaptive"},
        "anthropic_effort": "low",
    }


def test_bedrock_claude_uses_bedrock_native_request_fields() -> None:
    pytest.importorskip("boto3")
    assert resolve_model_options("bedrock:us.anthropic.claude-sonnet-5", ModelOptions(reasoning="high")) == {
        "bedrock_additional_model_requests_fields": {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "high"},
        }
    }


@pytest.mark.parametrize("field", ["seed", "request_timeout", "parallel_tool_calls"])
def test_bedrock_rejects_unsupported_per_request_controls(field: str) -> None:
    pytest.importorskip("boto3")
    with pytest.raises(ModelOptionsError, match=field):
        resolve_model_options(
            "bedrock:us.anthropic.claude-haiku-4-5",
            ModelOptions(**{field: False if field == "parallel_tool_calls" else 2}),
        )


@pytest.mark.parametrize("context", ["base_settings", "override_settings"])
def test_native_reasoning_disable_is_considered_before_sampling_validation(context: str) -> None:
    settings = resolve_model_options(
        "openai-responses:gpt-6-sol", ModelOptions(temperature=0.2), **{context: {"openai_reasoning_effort": "none"}}
    )
    assert settings == {"temperature": 0.2, "openai_reasoning_effort": "none"}


def test_native_sampling_override_cannot_bypass_portable_reasoning_validation() -> None:
    with pytest.raises(ModelOptionsError, match="temperature"):
        resolve_model_options(
            "openai-responses:gpt-6-sol", ModelOptions(reasoning="high"), override_settings={"temperature": 0.2}
        )


def test_native_override_can_disable_portable_reasoning_before_validation() -> None:
    assert resolve_model_options(
        "openai-responses:gpt-6-sol",
        ModelOptions(reasoning="high", temperature=0.2),
        override_settings={"openai_reasoning_effort": "none"},
    ) == {"openai_reasoning_effort": "none", "temperature": 0.2}


def test_existing_native_only_settings_are_untouched() -> None:
    native = {"temperature": 0.3, "openai_reasoning_effort": "high", "extra_body": {"future": "value"}}
    assert resolve_model_options("openai-responses:gpt-6-sol", ModelOptions(), base_settings=native) == native


def test_model_default_settings_take_part_in_effective_validation() -> None:
    model = OpenAIResponsesModel(
        "gpt-6-sol", provider=OpenAIProvider(api_key="test-key"), settings={"openai_reasoning_effort": "none"}
    )
    assert resolve_model_options(model, ModelOptions(temperature=0.2)) == {
        "openai_reasoning_effort": "none",
        "temperature": 0.2,
    }


def test_claude_budget_is_checked_against_the_sdk_default_output_limit() -> None:
    with pytest.raises(ModelOptionsError, match="max_tokens"):
        resolve_model_options("anthropic:claude-haiku-4-5", ModelOptions(reasoning="high"))


@pytest.mark.parametrize("context", ["base_settings", "override_settings"])
def test_native_output_limit_is_used_to_validate_claude_reasoning_budget(context: str) -> None:
    settings = resolve_model_options(
        "anthropic:claude-haiku-4-5", ModelOptions(reasoning="high"), **{context: {"max_tokens": 20000}}
    )
    assert settings == {"max_tokens": 20000, "anthropic_thinking": {"type": "enabled", "budget_tokens": 16384}}


def test_native_output_limit_override_can_invalidate_portable_claude_budget() -> None:
    with pytest.raises(ModelOptionsError, match="max_tokens"):
        resolve_model_options(
            "anthropic:claude-haiku-4-5",
            ModelOptions(reasoning_budget_tokens=2048, max_tokens=4096),
            override_settings={"max_tokens": 1024},
        )


def test_native_claude_thinking_is_used_for_portable_sampling_validation() -> None:
    with pytest.raises(ModelOptionsError, match="temperature"):
        resolve_model_options(
            "anthropic:claude-haiku-4-5",
            ModelOptions(temperature=0.3),
            base_settings={"anthropic_thinking": {"type": "enabled", "budget_tokens": 2048}},
        )


@pytest.mark.parametrize("field", ["top_k", "request_timeout", "parallel_tool_calls"])
def test_huggingface_rejects_controls_its_adapter_does_not_send(field: str) -> None:
    with pytest.raises(ModelOptionsError, match=field):
        resolve_model_options(
            "huggingface:some-model", ModelOptions(**{field: False if field == "parallel_tool_calls" else 2})
        )
