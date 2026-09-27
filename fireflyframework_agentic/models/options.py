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

"""Firefly model controls, translated and validated against the selected provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai.models import Model
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles import DEFAULT_PROFILE
from pydantic_ai.profiles.anthropic import anthropic_model_profile
from pydantic_ai.profiles.google import google_model_profile
from pydantic_ai.profiles.openai import openai_model_profile

from fireflyframework_agentic.model_utils import extract_model_info, normalize_model


class ModelOptionsError(ValueError):
    """An explicit Firefly option cannot be honored by the selected model or API."""


class ModelOptions(BaseModel):
    """Portable, immutable controls for a Firefly agent's model requests.

    ``None`` leaves the provider default unchanged. Reasoning labels express effort, while
    ``reasoning_budget_tokens`` requests an exact token budget; they are mutually exclusive.
    Unsupported settings raise :class:`ModelOptionsError` during resolution rather than
    silently disappearing. Provider-specific escape hatches remain in ``model_settings``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    max_tokens: int | None = Field(default=None, gt=0, strict=True)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, gt=0, strict=True)
    seed: int | None = Field(default=None, strict=True)
    stop_sequences: tuple[Annotated[str, Field(min_length=1)], ...] | None = None
    request_timeout: float | None = Field(default=None, gt=0)
    reasoning: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    reasoning_budget_tokens: int | None = Field(default=None, gt=0, strict=True)
    parallel_tool_calls: bool | None = Field(default=None, strict=True)
    store_responses: bool | None = Field(default=None, strict=True)
    output_verbosity: Literal["low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def _one_reasoning_control(self) -> Self:
        if self.reasoning is not None and self.reasoning_budget_tokens is not None:
            raise ValueError("Choose reasoning or reasoning_budget_tokens, not both.")
        return self


@dataclass(frozen=True)
class _Target:
    name: str
    backend: str
    profile: Mapping[str, Any]

    def reject(self, field: str, reason: str) -> None:
        raise ModelOptionsError(f"{field} is not supported for {self.name}: {reason}")


def _target(model: str | Model | None, profile: Mapping[str, Any] | None) -> _Target:
    while isinstance(model, WrapperModel):
        model = model.wrapped
    normalized = normalize_model(model)
    provider, name = extract_model_info(normalized)
    provider = provider.removeprefix("gateway/")
    backend = provider
    if isinstance(model, Model):
        classes = {cls.__name__ for cls in type(model).__mro__}
        for class_name, candidate in (
            ("OpenAIResponsesModel", "openai-responses"),
            ("OpenAIChatModel", "openai-chat"),
            ("AnthropicModel", "anthropic"),
            ("GoogleModel", "google"),
            ("BedrockConverseModel", "bedrock"),
        ):
            if class_name in classes:
                backend = candidate
                break
        derived = model.profile
    else:
        selector = normalized.partition(":")[0].removeprefix("gateway/") if isinstance(normalized, str) else ""
        if selector in {"openai", "openai-chat", "azure", "azure-chat"}:
            backend = "openai-chat"
        elif selector in {"openai-responses", "azure-responses"}:
            backend = "openai-responses"
        elif selector in {"google", "google-gla", "google-vertex"}:
            backend = "google"
        derived: Mapping[str, Any] = {}
        if backend.startswith("openai-"):
            derived = openai_model_profile(name)
        elif backend == "anthropic":
            derived = anthropic_model_profile(name) or {}
        elif backend == "google":
            derived = google_model_profile(name) or {}
        elif backend == "bedrock":
            # AWS is optional; resolving another provider must not require its SDK.
            from pydantic_ai.providers.bedrock import BedrockProvider  # noqa: PLC0415

            derived = BedrockProvider.model_profile(name) or {}
    return _Target(
        f"{provider}:{name}" if provider else name or "unconfigured model",
        backend,
        {**DEFAULT_PROFILE, **derived, **(profile or {})},
    )


_COMMON_FIELDS = ("max_tokens", "temperature", "top_p", "top_k", "seed", "stop_sequences", "parallel_tool_calls")
_SAMPLING_FIELDS = ("temperature", "top_p", "top_k")
_TOP_K_UNSUPPORTED = {
    "openai-chat",
    "openai-responses",
    "mistral",
    "groq",
    "xai",
    "cerebras",
    "openrouter",
    "ollama",
    "deepseek",
}


def _common_options(target: _Target, options: ModelOptions) -> dict[str, Any]:
    out = {field: getattr(options, field) for field in _COMMON_FIELDS if getattr(options, field) is not None}
    if options.stop_sequences is not None:
        out["stop_sequences"] = list(options.stop_sequences)
    if options.request_timeout is not None:
        out["timeout"] = options.request_timeout
    unsupported: set[str] = set()
    if target.backend in _TOP_K_UNSUPPORTED:
        unsupported.add("top_k")
    if target.backend == "openai-responses":
        unsupported.update(("seed", "stop_sequences"))
    if target.backend == "anthropic":
        unsupported.add("seed")
    if target.backend == "google":
        unsupported.add("parallel_tool_calls")
    if target.backend == "bedrock":
        unsupported.update(("seed", "parallel_tool_calls", "timeout"))
        if target.profile.get("bedrock_top_k_variant") not in {"anthropic", "nova"}:
            unsupported.add("top_k")
    if target.backend == "cohere":
        unsupported.update(("parallel_tool_calls", "timeout"))
    if target.backend == "huggingface":
        unsupported.update(("top_k", "parallel_tool_calls", "timeout"))
    unsupported.update(target.profile.get("openai_unsupported_model_settings", ()))
    for field in sorted(unsupported.intersection(out)):
        target.reject("request_timeout" if field == "timeout" else field, "the selected API cannot send this control")
    return out


def _openai_options(target: _Target, options: ModelOptions, out: dict[str, Any]) -> None:
    profile = target.profile
    if options.reasoning_budget_tokens is not None:
        target.reject("reasoning_budget_tokens", "OpenAI accepts reasoning effort, not an exact token budget")
    if options.reasoning is not None:
        if not profile.get("supports_thinking", False):
            target.reject("reasoning", "the model profile does not declare reasoning support")
        level = options.reasoning
        if level == "minimal" and not profile.get("openai_supports_minimal_reasoning_effort", True):
            level = "low"
        out["openai_reasoning_effort"] = level
    if options.store_responses is not None:
        out["openai_store"] = options.store_responses
    if options.output_verbosity is not None:
        if target.backend != "openai-responses":
            target.reject("output_verbosity", "use the Responses API for this control")
        out["openai_text_verbosity"] = options.output_verbosity


def _claude_options(target: _Target, options: ModelOptions, out: dict[str, Any]) -> None:
    profile = target.profile
    bedrock = target.backend == "bedrock"
    adaptive = profile.get(
        "bedrock_supports_adaptive_thinking" if bedrock else "anthropic_supports_adaptive_thinking", False
    )
    thinking: dict[str, Any] | None = None
    effort: str | None = None
    if options.reasoning is not None or options.reasoning_budget_tokens is not None:
        if not profile.get("supports_thinking", False):
            target.reject("reasoning", "the model profile does not declare thinking support")
        if options.reasoning == "none":
            if profile.get("thinking_always_enabled", False):
                target.reject("reasoning", "this model cannot disable thinking")
            thinking = {"type": "disabled"}
        elif options.reasoning_budget_tokens is not None or not adaptive:
            if profile.get("anthropic_disallows_budget_thinking", False):
                target.reject(
                    "reasoning_budget_tokens", "this model requires adaptive reasoning; choose reasoning instead"
                )
            budget = options.reasoning_budget_tokens
            if budget is None:
                assert options.reasoning is not None
                # These are the SDK's portable Claude effort-to-budget values.
                budget = {"minimal": 1024, "low": 2048, "medium": 10000, "high": 16384, "xhigh": 32768}[
                    options.reasoning
                ]
            thinking = {"type": "enabled", "budget_tokens": budget}
        else:
            effort = "low" if options.reasoning == "minimal" else options.reasoning
            if not profile.get("bedrock_supports_effort" if bedrock else "anthropic_supports_effort", False):
                target.reject("reasoning", "the model profile does not support effort selection")
            if effort == "xhigh" and not profile.get("anthropic_supports_xhigh_effort", False):
                target.reject("reasoning", "this model does not support xhigh effort")
            thinking = {"type": "adaptive"}
    if thinking is not None:
        if bedrock:
            fields: dict[str, Any] = {"thinking": thinking}
            if effort is not None:
                fields["output_config"] = {"effort": effort}
            out["bedrock_additional_model_requests_fields"] = fields
        else:
            out["anthropic_thinking"] = thinking
            if effort is not None:
                out["anthropic_effort"] = effort


def _google_options(target: _Target, options: ModelOptions, out: dict[str, Any]) -> None:
    profile = target.profile
    if options.reasoning is None and options.reasoning_budget_tokens is None:
        return
    if not profile.get("supports_thinking", False):
        target.reject("reasoning", "the model profile does not declare thinking support")
    level_based = profile.get("google_supports_thinking_level", False)
    if options.reasoning_budget_tokens is not None:
        if level_based:
            target.reject("reasoning_budget_tokens", "this model uses reasoning levels; choose reasoning instead")
        out["google_thinking_config"] = {"thinking_budget": options.reasoning_budget_tokens}
    elif options.reasoning == "none":
        if level_based or profile.get("thinking_always_enabled", False):
            target.reject("reasoning", "this model cannot fully disable thinking; choose a supported effort level")
        out["google_thinking_config"] = {"thinking_budget": 0}
    elif level_based:
        assert options.reasoning is not None
        levels = profile.get("google_thinking_levels") or {"MINIMAL", "LOW", "MEDIUM", "HIGH"}
        level = options.reasoning.upper()
        if level == "MINIMAL" and (
            not profile.get("google_supports_minimal_thinking_level", True) or level not in levels
        ):
            level = "LOW"
        if level not in levels:
            target.reject("reasoning", f"supported effort levels are {', '.join(sorted(levels))}")
        out["google_thinking_config"] = {"thinking_level": level}
    else:
        assert options.reasoning is not None
        # Gemini's budget-based API accepts the SDK's common portable effort scale.
        budget = {"minimal": 128, "low": 2048, "medium": 8192, "high": 24576, "xhigh": 24576}[options.reasoning]
        out["google_thinking_config"] = {"thinking_budget": budget}


def _validate_effective_options(target: _Target, settings: Mapping[str, Any]) -> None:
    """Validate interactions after model defaults and per-call overrides have been merged."""
    profile = target.profile
    if target.backend in {"openai-chat", "openai-responses"}:
        effort = settings.get("openai_reasoning_effort")
        if effort == "none" and not profile.get("openai_supports_reasoning_effort_none", False):
            target.reject("reasoning", "this model cannot disable reasoning")
        if effort is not None:
            reasoning_active = effort != "none"
        elif settings.get("thinking") is not None:
            reasoning_active = settings["thinking"] is not False
        else:
            reasoning_active = profile.get("openai_reasoning_enabled_by_default", False)
        if profile.get("supports_thinking", False) and reasoning_active:
            for field in _SAMPLING_FIELDS:
                if settings.get(field) is not None:
                    target.reject(
                        field, "sampling is unavailable while reasoning is enabled; use reasoning='none' when supported"
                    )
        if settings.get("openai_store") and profile.get("openai_responses_requires_store_false", False):
            target.reject("store_responses", "the model profile requires storage to be disabled")
    elif target.backend == "anthropic" or (
        target.backend == "bedrock" and profile.get("bedrock_thinking_variant") == "anthropic"
    ):
        bedrock = target.backend == "bedrock"
        fields = settings.get("bedrock_additional_model_requests_fields") or {} if bedrock else settings
        thinking = fields.get("thinking" if bedrock else "anthropic_thinking")
        if not thinking and settings.get("thinking"):
            if profile.get("anthropic_supports_adaptive_thinking", False):
                thinking = {"type": "adaptive"}
            else:
                budget = {
                    True: 10000,
                    "minimal": 1024,
                    "low": 2048,
                    "medium": 10000,
                    "high": 16384,
                    "xhigh": 32768,
                }.get(settings["thinking"])
                thinking = {"type": "enabled", "budget_tokens": budget}
        if settings.get("temperature") is not None and settings["temperature"] > 1:
            target.reject("temperature", "Claude's temperature range is 0 to 1")
        if profile.get("anthropic_disallows_sampling_settings", False) or (
            thinking and thinking.get("type") in {"enabled", "adaptive"}
        ):
            for field in _SAMPLING_FIELDS:
                if settings.get(field) is not None:
                    target.reject(field, "sampling is unavailable for this model or thinking configuration")
        if thinking and thinking.get("type") == "enabled":
            budget = thinking.get("budget_tokens")
            # PydanticAI's Anthropic adapter defaults max_tokens to 4096. Bedrock leaves
            # the limit to the provider, so require one to validate an explicit budget.
            limit = settings.get("max_tokens", None if bedrock else 4096)
            if not isinstance(budget, int) or budget < 1024 or not isinstance(limit, int) or budget >= limit:
                target.reject(
                    "reasoning_budget_tokens",
                    "Claude requires at least 1024 tokens and a budget below max_tokens; set max_tokens explicitly above the reasoning budget",
                )


def resolve_model_options(
    model: str | Model | None,
    options: ModelOptions,
    *,
    profile: Mapping[str, Any] | None = None,
    base_settings: Mapping[str, Any] | None = None,
    override_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve Firefly options for an API/model without creating a credentialed client.

    A native model's effective profile is authoritative. ``profile`` adds measured overrides
    for descriptions such as Azure deployment aliases. Bare Firefly ``openai:`` selectors
    retain Chat Completions semantics; Responses-only controls require an explicit selector.
    Returns effective settings in the order: model defaults, ``base_settings``, portable
    options, ``override_settings``. Validation uses those effective values. Empty portable
    options preserve native-only behavior without adding validation.
    """
    native = (
        {**(model.settings or {}), **(base_settings or {})} if isinstance(model, Model) else dict(base_settings or {})
    )
    if not options.model_dump(exclude_none=True):
        return {**native, **(override_settings or {})}
    target = _target(model, profile)
    out = _common_options(target, options)
    if target.backend in {"openai-chat", "openai-responses"}:
        _openai_options(target, options, out)
    else:
        for field in ("store_responses", "output_verbosity"):
            if getattr(options, field) is not None:
                target.reject(field, "this provider has no corresponding control")
        if target.backend == "anthropic" or (
            target.backend == "bedrock" and target.profile.get("bedrock_thinking_variant") == "anthropic"
        ):
            _claude_options(target, options, out)
        elif target.backend == "google":
            _google_options(target, options, out)
        else:
            for field in ("reasoning", "reasoning_budget_tokens"):
                if getattr(options, field) is not None:
                    target.reject(field, "no supported reasoning translation is known for this provider")
    out = {**native, **out, **(override_settings or {})}
    _validate_effective_options(target, out)
    native_names = {
        "openai_reasoning_effort": "reasoning",
        "openai_store": "store_responses",
        "openai_text_verbosity": "output_verbosity",
    }
    for key in target.profile.get("openai_unsupported_model_settings", ()):
        if key in out:
            target.reject(native_names.get(str(key), str(key)), "the model profile declares this control unsupported")
    return out


__all__ = ["ModelOptions", "ModelOptionsError", "resolve_model_options"]
