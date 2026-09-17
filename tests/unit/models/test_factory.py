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

"""``ModelFactory``: a pydantic-ai model from a (provider, model, credential, settings) description.

The framework had identity helpers (``model_utils``) and no way to BUILD a model from data, so
every host that stored its model choice in a catalogue — class, id, provider kwargs, measured
profile corrections, a parameter profile — wrote its own factory, its own Claude 5 table and its
own thinking-settings translation, and each one found the same three provider rules the hard
way: extended thinking refuses ``temperature``/``top_p``/``top_k``; the Claude 4.7+ family
refuses them outright and refuses ``budget_tokens``; Haiku 4.5 still takes a budget. This suite
pins that knowledge upstream.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.profiles.anthropic import AnthropicModelProfile

from fireflyframework_agentic.models import (
    EFFORT_BUDGETS,
    Credential,
    ModelBuildError,
    ModelCapabilities,
    ModelFactory,
    ModelSpec,
    anthropic_effort_for,
    capabilities_for,
    claude_profile,
    effort_for,
    model_settings_for,
)


class _Vault:
    """A credential resolver that hands back a fixture and records what was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, int]] = []

    async def resolve(self, reference: str, version: int) -> str:
        self.asked.append((reference, version))
        return f"secret-for-{reference}-v{version}"


def _spec(model: str, **kw: Any) -> ModelSpec:
    return ModelSpec(provider="anthropic", model=model, credential=Credential.api_key("sk-test"), **kw)


class TestClaudeProfile:
    @pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-5", "claude-opus-5-20260401"])
    def test_the_claude_5_family_is_known_even_when_the_sdk_table_is_not(self, model: str) -> None:
        profile = claude_profile(model)
        assert isinstance(profile, AnthropicModelProfile)
        assert profile.supports_thinking is True
        assert profile.anthropic_supports_adaptive_thinking is True
        assert profile.anthropic_supports_effort is True
        assert profile.anthropic_supports_xhigh_effort is True
        assert profile.anthropic_disallows_budget_thinking is True
        assert profile.anthropic_disallows_sampling_settings is True
        assert profile.supports_json_schema_output is True

    def test_haiku_4_5_keeps_the_budget_rules(self) -> None:
        profile = claude_profile("claude-haiku-4-5")
        assert profile.anthropic_supports_adaptive_thinking is False
        assert profile.anthropic_disallows_budget_thinking is False
        assert profile.anthropic_disallows_sampling_settings is False

    def test_the_sdk_profile_is_replaced_never_constructed(self) -> None:
        """Fields the SDK derives (thinking tags, code-execution versions) survive the corrections."""
        profile = claude_profile("claude-sonnet-5")
        assert profile.thinking_tags == ("<thinking>", "</thinking>")
        assert profile.anthropic_default_code_execution_tool_version


class TestCapabilities:
    def test_derived_from_the_model_id_when_not_given(self) -> None:
        assert capabilities_for("anthropic", "claude-opus-5") == ModelCapabilities(
            thinking=True, thinking_style="adaptive", max_thinking_budget_tokens=None, refuses_sampling=True
        )
        assert capabilities_for("anthropic", "claude-sonnet-4-6").thinking_style == "adaptive"
        assert capabilities_for("anthropic", "claude-sonnet-4-6").refuses_sampling is False
        assert capabilities_for("anthropic", "claude-opus-4-7").refuses_sampling is True
        haiku = capabilities_for("anthropic", "claude-haiku-4-5")
        assert haiku.thinking_style == "budget"
        assert haiku.max_thinking_budget_tokens == 32000
        assert capabilities_for("openai", "gpt-5").thinking_style == "effort"
        assert capabilities_for("openai", "gpt-4o").thinking is False
        assert capabilities_for("bedrock", "anthropic.claude-opus-5").thinking_style == "adaptive"


class TestEffortVocabulary:
    def test_the_budget_table(self) -> None:
        assert EFFORT_BUDGETS == {"minimal": 1024, "low": 4096, "medium": 8192, "high": 16384, "xhigh": 32768}

    def test_labels_read_back_from_budgets(self) -> None:
        assert effort_for(1024) == "minimal"
        assert effort_for(4096) == "low"
        assert effort_for(8192) == "medium"
        assert effort_for(16384) == "high"
        assert effort_for(32768) == "high"  # no fifth level on OpenAI's vocabulary
        assert anthropic_effort_for(1024) == "low"
        assert anthropic_effort_for(8192) == "medium"
        assert anthropic_effort_for(16384) == "high"
        assert anthropic_effort_for(32768) == "xhigh"
        assert anthropic_effort_for(64000) == "max"


class TestModelSettings:
    def test_plain_settings_are_renamed_not_passed_through(self) -> None:
        spec = _spec(
            "claude-haiku-4-5",
            settings={"temperature": 0.3, "topP": 0.9, "maxTokens": 2048, "stopSequences": ["END"], "seed": 7},
        )
        assert model_settings_for(spec) == {
            "temperature": 0.3,
            "top_p": 0.9,
            "max_tokens": 2048,
            "stop_sequences": ["END"],
            "seed": 7,
        }

    def test_snake_case_settings_are_accepted_too(self) -> None:
        spec = _spec("claude-haiku-4-5", settings={"max_tokens": 100, "top_p": 0.5})
        assert model_settings_for(spec) == {"max_tokens": 100, "top_p": 0.5}

    def test_adaptive_models_drop_the_sampling_knobs_whether_or_not_a_budget_is_set(self) -> None:
        """Thinking is on by default on the Claude 5 family: the model turns the rule on, not the budget."""
        spec = _spec("claude-sonnet-5", settings={"temperature": 0.2, "topP": 0.9, "topK": 40, "maxTokens": 4096})
        assert model_settings_for(spec) == {"max_tokens": 4096}

    def test_an_adaptive_budget_becomes_adaptive_thinking_plus_an_effort_level(self) -> None:
        spec = _spec("claude-opus-5", settings={"temperature": 0.2, "thinkingBudgetTokens": 16384})
        assert model_settings_for(spec) == {
            "anthropic_thinking": {"type": "adaptive"},
            "anthropic_effort": "high",
        }

    def test_an_explicit_effort_wins_over_a_budget(self) -> None:
        spec = _spec("claude-opus-5", settings={"thinkingBudgetTokens": 1024, "effort": "xhigh"})
        assert model_settings_for(spec)["anthropic_effort"] == "xhigh"

    def test_a_budget_model_gets_a_clamped_budget_and_loses_the_sampling_knobs(self) -> None:
        spec = _spec("claude-haiku-4-5", settings={"temperature": 0.2, "topK": 5, "thinkingBudgetTokens": 64000})
        assert model_settings_for(spec) == {"anthropic_thinking": {"type": "enabled", "budget_tokens": 32000}}

    def test_a_budget_model_without_a_budget_keeps_its_sampling_knobs(self) -> None:
        spec = _spec("claude-haiku-4-5", settings={"temperature": 0.2, "topK": 5})
        assert model_settings_for(spec) == {"temperature": 0.2, "top_k": 5}

    def test_an_effort_model_takes_a_label(self) -> None:
        spec = ModelSpec(
            provider="openai",
            model="gpt-5",
            credential=Credential.api_key("k"),
            settings={"thinkingBudgetTokens": 8192},
        )
        assert model_settings_for(spec) == {"openai_reasoning_effort": "medium"}

    def test_a_model_without_thinking_drops_the_budget_silently(self) -> None:
        spec = ModelSpec(
            provider="openai",
            model="gpt-4o",
            credential=Credential.api_key("k"),
            settings={"thinkingBudgetTokens": 8192},
        )
        assert model_settings_for(spec) == {}

    def test_service_tier_passes_only_when_the_model_has_it(self) -> None:
        spec = _spec("claude-opus-5", settings={"serviceTier": "priority"})
        assert model_settings_for(spec) == {}
        spec = ModelSpec(
            provider="openai",
            model="gpt-5",
            credential=Credential.api_key("k"),
            settings={"serviceTier": "priority"},
            capabilities=ModelCapabilities(thinking=True, thinking_style="effort", service_tier=True),
        )
        assert model_settings_for(spec) == {"service_tier": "priority"}

    def test_explicit_capabilities_override_the_derived_ones(self) -> None:
        caps = ModelCapabilities(thinking=True, thinking_style="budget", max_thinking_budget_tokens=2048)
        spec = _spec("claude-opus-5", settings={"thinkingBudgetTokens": 9999}, capabilities=caps)
        assert model_settings_for(spec) == {"anthropic_thinking": {"type": "enabled", "budget_tokens": 2048}}


class TestBuild:
    async def test_an_anthropic_model_is_built_with_the_claude_5_profile(self) -> None:
        model = await ModelFactory().build(_spec("claude-opus-5"))
        assert isinstance(model, AnthropicModel)
        assert model.model_name == "claude-opus-5"
        profile = AnthropicModelProfile.from_profile(model.profile)
        assert profile.anthropic_supports_adaptive_thinking is True
        assert profile.anthropic_disallows_budget_thinking is True

    async def test_profile_overrides_are_applied_with_replace_and_unknown_fields_ignored(self, caplog: Any) -> None:
        spec = _spec("claude-haiku-4-5", profile_overrides={"supports_json_schema_output": False, "not_a_field": 1})
        model = await ModelFactory().build(spec)
        assert model.profile.supports_json_schema_output is False
        assert model.profile.supports_thinking is True
        assert "not_a_field" in caplog.text

    async def test_the_credential_is_resolved_by_reference(self) -> None:
        vault = _Vault()
        spec = ModelSpec(provider="anthropic", model="claude-opus-5", credential=Credential.reference("acct-1", 3))
        model = await ModelFactory(credentials=vault).build(spec)
        assert vault.asked == [("acct-1", 3)]
        assert isinstance(model, AnthropicModel)

    async def test_a_reference_without_a_resolver_is_refused(self) -> None:
        spec = ModelSpec(provider="anthropic", model="claude-opus-5", credential=Credential.reference("acct-1", 1))
        with pytest.raises(ModelBuildError, match="resolver"):
            await ModelFactory().build(spec)

    async def test_openai_chat_and_responses_are_distinct(self) -> None:
        chat = await ModelFactory().build(
            ModelSpec(provider="openai", model="gpt-5", credential=Credential.api_key("k"))
        )
        assert isinstance(chat, OpenAIChatModel)
        responses = await ModelFactory().build(
            ModelSpec(
                provider="openai", model="gpt-5", credential=Credential.api_key("k"), model_class="OpenAIResponsesModel"
            )
        )
        assert isinstance(responses, OpenAIResponsesModel)
        assert not isinstance(responses, OpenAIChatModel)

    async def test_an_openai_compatible_base_url_reaches_the_provider(self) -> None:
        model = await ModelFactory().build(
            ModelSpec(
                provider="ollama",
                model="llama3.1:8b",
                credential=Credential.none(),
                base_url="http://localhost:11434/v1",
            )
        )
        assert isinstance(model, OpenAIChatModel)
        assert str(model.client.base_url).startswith("http://localhost:11434/v1")

    async def test_azure_needs_an_endpoint_and_an_api_version(self) -> None:
        with pytest.raises(ModelBuildError, match="API version"):
            await ModelFactory().build(
                ModelSpec(
                    provider="azure",
                    model="gpt-5",
                    credential=Credential.api_key("k"),
                    base_url="https://x.openai.azure.com",
                )
            )

    async def test_bedrock_splits_the_two_part_credential_on_the_first_colon(self) -> None:
        pytest.importorskip("boto3")
        from pydantic_ai.models.bedrock import BedrockConverseModel

        model = await ModelFactory().build(
            ModelSpec(
                provider="bedrock",
                model="anthropic.claude-opus-5",
                credential=Credential.api_key("AKIA:se:cret"),
                region="eu-west-1",
            )
        )
        assert isinstance(model, BedrockConverseModel)

    async def test_bedrock_refuses_a_credential_of_the_wrong_shape(self) -> None:
        pytest.importorskip("boto3")
        with pytest.raises(ModelBuildError, match="accessKeyId:secretAccessKey"):
            await ModelFactory().build(
                ModelSpec(
                    provider="bedrock", model="anthropic.claude-opus-5", credential=Credential.api_key("only-one-part")
                )
            )

    async def test_an_unknown_class_names_the_known_ones(self) -> None:
        with pytest.raises(ModelBuildError, match="AnthropicModel"):
            await ModelFactory().build(_spec("claude-opus-5", model_class="FancyModel"))

    async def test_an_unknown_provider_is_refused(self) -> None:
        with pytest.raises(ModelBuildError, match="provider"):
            await ModelFactory().build(ModelSpec(provider="carrier-pigeon", model="x", credential=Credential.none()))

    def test_specs_are_frozen(self) -> None:
        spec = _spec("claude-opus-5")
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.model = "other"  # type: ignore[misc]


class TestSettingsAgainstTheSdk:
    """The translated settings pass pydantic-ai's own per-model validation for the built model."""

    async def test_claude_5_adaptive_settings_are_accepted_and_sampling_is_gone(self) -> None:
        from pydantic_ai.models import ModelRequestParameters

        spec = _spec("claude-sonnet-5", settings={"temperature": 0.2, "thinkingBudgetTokens": 8192, "maxTokens": 1000})
        model = await ModelFactory().build(spec)
        prepared, _ = model.prepare_request(model_settings_for(spec), ModelRequestParameters())  # type: ignore[arg-type]
        assert prepared == {
            "max_tokens": 1000,
            "anthropic_thinking": {"type": "adaptive"},
            "anthropic_effort": "medium",
        }

    async def test_a_budget_on_claude_5_is_refused_by_the_sdk_because_the_profile_says_so(self) -> None:
        from pydantic_ai.exceptions import UserError
        from pydantic_ai.models import ModelRequestParameters

        model = await ModelFactory().build(_spec("claude-opus-5"))
        with pytest.raises(UserError, match="adaptive"):
            model.prepare_request(
                {"anthropic_thinking": {"type": "enabled", "budget_tokens": 1024}},  # type: ignore[arg-type]
                ModelRequestParameters(),
            )

    async def test_haiku_budget_settings_are_accepted(self) -> None:
        from pydantic_ai.models import ModelRequestParameters

        spec = _spec("claude-haiku-4-5", settings={"thinkingBudgetTokens": 2048, "maxTokens": 4096})
        model = await ModelFactory().build(spec)
        prepared, _ = model.prepare_request(model_settings_for(spec), ModelRequestParameters())  # type: ignore[arg-type]
        assert prepared == {"max_tokens": 4096, "anthropic_thinking": {"type": "enabled", "budget_tokens": 2048}}
