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

"""Build a pydantic-ai model, and its settings, from a :class:`~fireflyframework_agentic.models.spec.ModelSpec`.

The factory follows a description; it does not make decisions. Which SDK class, which id,
which provider arguments, which profile corrections — all of that is stated on the spec or
derived from the model id by the framework's tables (:mod:`fireflyframework_agentic.models.claude`).
A host that kept a mapping like this in its own code duplicated the framework's knowledge of
each provider, and when the two drifted the symptom was a ``TypeError`` deep inside the SDK, or
a 400 from the provider, rather than a sentence anyone could read.

Two things the factory knows that a host should not have to:

* **profile corrections preserve provider fields** — see :mod:`~fireflyframework_agentic.models.claude`;
* **the provider's rules for thinking and sampling** — :func:`model_settings_for` translates a
  parameter profile into pydantic-ai ``ModelSettings`` keys and sends only what the model takes:
  the sampling knobs are dropped for a model that refuses them and for a budget-style thinking
  turn (Anthropic's "``temperature`` may only be set to 1 when thinking is enabled"), a budget is
  clamped to the model's ceiling, an adaptive model gets ``{"type": "adaptive"}`` plus an effort
  level, an effort-style model gets a label, and a model without thinking gets no thinking key
  at all.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Any, cast

from pydantic_ai.models import Model
from pydantic_ai.profiles import DEFAULT_PROFILE, ModelProfile

from fireflyframework_agentic.model_utils import detect_model_family
from fireflyframework_agentic.models.claude import (
    bedrock_claude_profile,
    claude_capabilities,
    claude_profile,
    is_claude,
)
from fireflyframework_agentic.models.spec import (
    Credential,
    CredentialResolver,
    ModelCapabilities,
    ModelSpec,
)

logger = logging.getLogger(__name__)


class ModelBuildError(RuntimeError):
    """The description could not be followed.

    Distinct from a provider error: this one means the *configuration* is wrong — a class the
    SDK does not have, a credential the resolver would not release, a provider argument missing —
    so retrying will fail identically, and the caller should say so rather than back off.
    """


# ---------------------------------------------------------------------------
# Effort vocabulary
# ---------------------------------------------------------------------------

#: The token budget each effort level means, and therefore the boundaries an effort-style
#: provider's label is read back out of. One knob in a console — a thinking budget — serves
#: two provider vocabularies through this table; a host that prices effort levels prices them
#: from the same numbers.
EFFORT_BUDGETS: Mapping[str, int] = {
    "minimal": 1024,
    "low": 4096,
    "medium": 8192,
    "high": 16384,
    "xhigh": 32768,
}


def _midpoint(low: str, high: str) -> int:
    return (EFFORT_BUDGETS[low] + EFFORT_BUDGETS[high]) // 2


def effort_for(budget: int) -> str:
    """The OpenAI effort label a token budget means: ``minimal``, ``low``, ``medium`` or ``high``.

    The table read backwards: the boundary between two labels is the midpoint of their budgets,
    so a budget that came from ``high`` maps back to ``high`` however hard it was clamped on the
    way through. This preserves the original budget mapping; newer effort levels such as
    ``xhigh`` can be selected explicitly through ``effort`` or ``openai_reasoning_effort``.
    """
    if budget < _midpoint("minimal", "low"):
        return "minimal"
    if budget < _midpoint("low", "medium"):
        return "low"
    if budget < _midpoint("medium", "high"):
        return "medium"
    return "high"


def anthropic_effort_for(budget: int) -> str:
    """The Anthropic effort level a token budget means: ``low``, ``medium``, ``high``, ``xhigh`` or ``max``.

    Anthropic has no ``minimal`` and does have ``xhigh`` and ``max``. A budget under the low
    boundary is ``low`` (there is nothing lower); a budget above ``xhigh``'s own is ``max``,
    because "think as hard as you can" is the honest reading of a ceiling larger than the scale.
    """
    if budget < _midpoint("low", "medium"):
        return "low"
    if budget < _midpoint("medium", "high"):
        return "medium"
    if budget < _midpoint("high", "xhigh"):
        return "high"
    if budget <= EFFORT_BUDGETS["xhigh"]:
        return "xhigh"
    return "max"


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


def capabilities_for(provider: str, model: str) -> ModelCapabilities:
    """Derive :class:`ModelCapabilities` from a provider and model id.

    Claude ids (bare, Bedrock-prefixed or Vertex-suffixed) come from
    :func:`~fireflyframework_agentic.models.claude.claude_capabilities`; the OpenAI reasoning
    models take an effort label; Gemini 2.5+ takes a budget; anything else is assumed to have
    no thinking mode, which is the safe direction — a dropped budget shows in a trace, a 400
    fails the turn.
    """
    if is_claude(model):
        return claude_capabilities(model)
    family = detect_model_family(f"{provider}:{model}")
    name = model.lower()
    if family == "openai":
        from pydantic_ai.profiles.openai import openai_model_profile

        if openai_model_profile(name).get("supports_thinking", False):
            return ModelCapabilities(thinking=True, thinking_style="effort", service_tier=True)
    if family == "google" and name.startswith(("gemini-2.5", "gemini-3")):
        return ModelCapabilities(thinking=True, thinking_style="budget", max_thinking_budget_tokens=32_768)
    return ModelCapabilities()


# ---------------------------------------------------------------------------
# Settings translation
# ---------------------------------------------------------------------------

_SAMPLING_KEYS = ("temperature", "top_p", "top_k")

#: Console vocabulary -> pydantic-ai key. Both spellings are read, so a host may pass either.
_PLAIN_SETTINGS: tuple[tuple[str, str, Callable[[Any], Any]], ...] = (
    ("temperature", "temperature", float),
    ("topP", "top_p", float),
    ("topK", "top_k", int),
    ("maxTokens", "max_tokens", int),
    ("stopSequences", "stop_sequences", list),
    ("seed", "seed", int),
)

_CONSOLE_SETTINGS = {camel for camel, snake, _ in _PLAIN_SETTINGS if camel != snake} | {
    "thinkingBudgetTokens",
    "thinking_budget_tokens",
    "effort",
    "serviceTier",
}


def _setting(settings: Mapping[str, Any], camel: str, snake: str) -> Any:
    if camel in settings:
        return settings[camel]
    if snake in settings:
        return settings[snake]
    return None


def model_settings_for(spec: ModelSpec) -> dict[str, Any]:
    """The spec's parameter profile as pydantic-ai ``ModelSettings`` keys.

    Console aliases are translated; native PydanticAI settings pass through, including
    provider-specific options and structured timeout values. Explicit native thinking settings
    take precedence over the console's portable effort/budget aliases. Unsupported console
    capabilities and incompatible Anthropic sampling settings are dropped.
    """
    settings: Mapping[str, Any] = spec.settings
    capabilities = spec.capabilities if spec.capabilities is not None else capabilities_for(spec.provider, spec.model)
    out: dict[str, Any] = {key: value for key, value in settings.items() if key not in _CONSOLE_SETTINGS}

    for camel, snake, convert in _PLAIN_SETTINGS:
        value = _setting(settings, camel, snake)
        if value is not None:
            out[snake] = convert(value)

    # A MODEL THAT REFUSES THE SAMPLING KNOBS REFUSES THEM WHETHER OR NOT A BUDGET WAS SET. The
    # Claude 4.7+ and Claude 5 families answer 400 to `temperature` on every request — thinking
    # is on by default there, so the budget is not what turns the rule on, the model is. Dropping
    # them only inside the thinking branch left a profile with a temperature and no budget failing
    # every turn.
    if capabilities.refuses_sampling:
        for key in _SAMPLING_KEYS:
            out.pop(key, None)

    raw_budget = _setting(settings, "thinkingBudgetTokens", "thinking_budget_tokens")
    budget: int | None = int(raw_budget) if raw_budget is not None else None
    effort = _setting(settings, "effort", "effort")
    family = detect_model_family(f"{spec.provider}:{spec.model}")

    if capabilities.thinking and (budget is not None or effort is not None):
        style = capabilities.thinking_style
        # One of the two is set here; a label with no budget is folded onto the table's budget.
        resolved_budget = budget if budget is not None else EFFORT_BUDGETS.get(str(effort), EFFORT_BUDGETS["medium"])
        # Bedrock reads `additionalModelRequestFields`, not Anthropic's native setting names.
        bedrock = spec.provider == "bedrock" and is_claude(spec.model)
        if style == "budget":
            ceiling = capabilities.max_thinking_budget_tokens
            tokens = resolved_budget
            if ceiling:
                # Over the ceiling the provider rejects the whole request, so a worker configured
                # a little too ambitiously would fail every turn rather than think a little less.
                tokens = min(tokens, ceiling)
            if family == "google":
                out.setdefault("google_thinking_config", {"thinking_budget": tokens})
            elif bedrock:
                fields = dict(out.get("bedrock_additional_model_requests_fields") or {})
                fields.setdefault("thinking", {"type": "enabled", "budget_tokens": tokens})
                out["bedrock_additional_model_requests_fields"] = fields
            else:
                out.setdefault("anthropic_thinking", {"type": "enabled", "budget_tokens": tokens})
        elif style == "effort":
            from pydantic_ai.profiles.openai import openai_model_profile

            level = str(effort) if effort is not None else effort_for(resolved_budget)
            profile = openai_model_profile(spec.model)
            if level == "minimal" and not profile.get("openai_supports_minimal_reasoning_effort", True):
                level = "low"
            out.setdefault("openai_reasoning_effort", level)
        elif style == "adaptive":
            # Adaptive models take an effort level; a fixed enabled budget is invalid.
            level = str(effort) if effort is not None else anthropic_effort_for(resolved_budget)
            if bedrock:
                fields = dict(out.get("bedrock_additional_model_requests_fields") or {})
                fields.setdefault("thinking", {"type": "adaptive"})
                output_config = dict(fields.get("output_config") or {})
                output_config.setdefault("effort", level)
                fields["output_config"] = output_config
                out["bedrock_additional_model_requests_fields"] = fields
            else:
                out.setdefault("anthropic_thinking", {"type": "adaptive"})
                out.setdefault("anthropic_effort", level)

    # Apply sampling rules to the effective setting after native overrides have won.
    native_thinking = out.get("anthropic_thinking")
    if spec.provider == "bedrock":
        native_thinking = (out.get("bedrock_additional_model_requests_fields") or {}).get("thinking")
    if isinstance(native_thinking, Mapping) and native_thinking.get("type") in {"enabled", "adaptive"}:
        for key in _SAMPLING_KEYS:
            out.pop(key, None)

    tier = settings.get("serviceTier")
    if capabilities.service_tier and tier is not None:
        out["service_tier"] = str(tier)

    if spec.options is not None:
        from fireflyframework_agentic.models.options import ModelOptionsError, resolve_model_options

        if capabilities.refuses_sampling:
            for key in _SAMPLING_KEYS:
                if getattr(spec.options, key) is not None:
                    raise ModelOptionsError(
                        f"{key} is not supported for {spec.model}: model capabilities refuse sampling"
                    )
        requested_budget = spec.options.reasoning_budget_tokens
        if (
            requested_budget is not None
            and capabilities.max_thinking_budget_tokens is not None
            and requested_budget > capabilities.max_thinking_budget_tokens
        ):
            raise ModelOptionsError(
                f"reasoning_budget_tokens exceeds {spec.model}'s declared limit of {capabilities.max_thinking_budget_tokens}"
            )
        provider = spec.provider
        class_name = spec.model_class or DEFAULT_CLASS_BY_PROVIDER.get(provider)
        if class_name in {"OpenAIChatModel", "OpenAIResponsesModel"}:
            family = "azure" if provider.startswith("azure") else "openai"
            provider = f"{family}-{'responses' if class_name == 'OpenAIResponsesModel' else 'chat'}"
        profile = dict(profile_for(spec) or _derived_profile(spec))
        if spec.capabilities is not None:
            profile["supports_thinking"] = spec.capabilities.thinking
        out = resolve_model_options(f"{provider}:{spec.model}", spec.options, profile=profile, base_settings=out)

    return out


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def _derived_profile(spec: ModelSpec) -> ModelProfile:
    """The SDK's own profile for this model, corrected where the framework knows better.

    Unknown ids fall back to the SDK's default profile so measured overrides still apply.
    """
    if is_claude(spec.model):
        if spec.provider == "bedrock":
            try:
                return bedrock_claude_profile(spec.model)
            except ImportError:  # pragma: no cover - boto3 is the bedrock extra; the build fails later, louder
                logger.warning("bedrock support is not installed; using the Anthropic profile for %s", spec.model)
        return claude_profile(spec.model)
    family = detect_model_family(f"{spec.provider}:{spec.model}")
    try:
        if family == "openai":
            from pydantic_ai.profiles.openai import openai_model_profile

            return openai_model_profile(spec.model) or DEFAULT_PROFILE.copy()
        if family == "google":
            from pydantic_ai.profiles.google import google_model_profile

            return google_model_profile(spec.model) or DEFAULT_PROFILE.copy()
        if family == "mistral":
            from pydantic_ai.profiles.mistral import mistral_model_profile

            return mistral_model_profile(spec.model) or DEFAULT_PROFILE.copy()
    except ImportError:  # pragma: no cover - depends on the installed SDK's layout
        logger.warning("no profile module for family %s; using a bare profile", family)
    return DEFAULT_PROFILE.copy()


def _profile_fields(spec: ModelSpec, derived: ModelProfile) -> set[str]:
    """Known override keys, including optional provider fields absent from a derived profile."""
    schema: Any = ModelProfile
    family = detect_model_family(f"{spec.provider}:{spec.model}")
    if spec.provider == "bedrock":
        from pydantic_ai.providers.bedrock import BedrockModelProfile

        schema = BedrockModelProfile
    elif is_claude(spec.model):
        from pydantic_ai.profiles.anthropic import AnthropicModelProfile

        schema = AnthropicModelProfile
    elif family == "openai" or spec.base_url or spec.model_class in {"OpenAIChatModel", "OpenAIResponsesModel"}:
        from pydantic_ai.profiles.openai import OpenAIModelProfile

        schema = OpenAIModelProfile
    elif family == "google":
        from pydantic_ai.profiles.google import GoogleModelProfile

        schema = GoogleModelProfile
    return set(schema.__annotations__) | derived.keys()


def profile_for(spec: ModelSpec) -> ModelProfile | None:
    """The derived profile with the spec's measured corrections applied, or ``None``.

    ``None`` when there is nothing to correct and the SDK knows the model — which is the
    common case, and returning ``None`` rather than a reconstructed profile is what keeps the
    SDK's own derivation in play. A Claude id always gets a profile, because the corrections in
    :mod:`~fireflyframework_agentic.models.claude` are part of what "derived" means here.
    """
    derived = _derived_profile(spec)
    overrides: Mapping[str, Any] = spec.profile_overrides
    if not overrides:
        return derived if is_claude(spec.model) else None

    fields = _profile_fields(spec, derived)
    applicable = {key: value for key, value in overrides.items() if key in fields}
    ignored = set(overrides) - applicable.keys()
    if ignored:
        # Logged rather than raised. An override naming a field this SDK version does not have
        # means the catalogue is ahead of the SDK — a deployment-skew warning, not a reason to
        # refuse a model that would otherwise work.
        logger.warning(
            "model %s: ignoring profile override(s) %s — not fields of %s in this pydantic-ai version",
            spec.model,
            sorted(ignored),
            type(derived).__name__,
        )
    return (
        cast("ModelProfile", {**derived, **applicable}) if applicable else (derived if is_claude(spec.model) else None)
    )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _profile_kwargs(profile: ModelProfile | None) -> dict[str, Any]:
    # Only when there is something to say: passing profile=None is not the same as omitting it
    # in every SDK version.
    return {"profile": profile} if profile is not None else {}


def _anthropic(spec: ModelSpec, secret: str | None, profile: ModelProfile | None) -> Model:
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel(spec.model, provider=AnthropicProvider(api_key=secret), **_profile_kwargs(profile))


def _openai_provider(spec: ModelSpec, secret: str | None) -> Any:
    if spec.provider in {"azure", "azure-chat", "azure-responses"}:
        from pydantic_ai.exceptions import UserError
        from pydantic_ai.providers.azure import AzureProvider

        try:
            return AzureProvider(azure_endpoint=spec.base_url, api_version=spec.api_version, api_key=secret)
        except UserError as exc:
            raise ModelBuildError(f"Azure endpoint, API version or credential configuration is invalid: {exc}") from exc

    from pydantic_ai.providers.openai import OpenAIProvider

    # Empty environment values should also permit keyless compatible endpoints.
    if spec.base_url and secret is None and not (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_ADMIN_KEY")):
        secret = "unused"
    return OpenAIProvider(base_url=spec.base_url, api_key=secret)


def _openai_chat(spec: ModelSpec, secret: str | None, profile: ModelProfile | None) -> Model:
    from pydantic_ai.models.openai import OpenAIChatModel

    return OpenAIChatModel(spec.model, provider=_openai_provider(spec, secret), **_profile_kwargs(profile))


def _openai_responses(spec: ModelSpec, secret: str | None, profile: ModelProfile | None) -> Model:
    # Its own builder: the Responses API is a different request shape (stateful items,
    # built-in tools) and a catalogue asking for it must not be served Chat Completions
    # silently, which is what aliasing the two did.
    from pydantic_ai.models.openai import OpenAIResponsesModel

    return OpenAIResponsesModel(spec.model, provider=_openai_provider(spec, secret), **_profile_kwargs(profile))


def _bedrock(spec: ModelSpec, secret: str | None, profile: ModelProfile | None) -> Model:
    from pydantic_ai.models.bedrock import BedrockConverseModel
    from pydantic_ai.providers.bedrock import BedrockProvider

    # A Bedrock credential travels as `accessKeyId:secretAccessKey` — the one shape that fits a
    # single secret without a second table for a two-part credential. Split on the FIRST colon
    # only: an AWS secret can contain one.
    access_key, _, secret_key = (secret or "").partition(":")
    if secret is not None and (not access_key or not secret_key):
        raise ModelBuildError(
            "A Bedrock credential is carried as 'accessKeyId:secretAccessKey'. This one does not have that shape, "
            "so it cannot be split into the two values the SDK needs."
        )
    return BedrockConverseModel(
        spec.model,
        provider=BedrockProvider(
            region_name=spec.region, aws_access_key_id=access_key or None, aws_secret_access_key=secret_key or None
        ),
        **_profile_kwargs(profile),
    )


def _google(spec: ModelSpec, secret: str | None, profile: ModelProfile | None) -> Model:
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    provider: Any
    if spec.provider == "google-vertex":
        if not spec.project:
            raise ModelBuildError("Vertex AI needs a project id; the spec is missing one.")
        # ``location`` is typed as a closed set of regions; a spec carries a string.
        provider = GoogleProvider(vertexai=True, project=spec.project, location=spec.region)  # type: ignore[arg-type]
    else:
        provider = GoogleProvider(api_key=secret or "")
    return GoogleModel(spec.model, provider=provider, **_profile_kwargs(profile))


def _mistral(spec: ModelSpec, secret: str | None, profile: ModelProfile | None) -> Model:
    from pydantic_ai.models.mistral import MistralModel
    from pydantic_ai.providers.mistral import MistralProvider

    return MistralModel(spec.model, provider=MistralProvider(api_key=secret or ""), **_profile_kwargs(profile))


Builder = Callable[[ModelSpec, "str | None", "ModelProfile | None"], Model]

#: The class names a spec may ask for, and how to build each. A table rather than a chain of
#: ``if`` statements, so an unknown class produces a message naming what IS known.
BUILDERS: Mapping[str, Builder] = {
    "AnthropicModel": _anthropic,
    "OpenAIChatModel": _openai_chat,
    "OpenAIResponsesModel": _openai_responses,
    "BedrockConverseModel": _bedrock,
    "GoogleModel": _google,
    "MistralModel": _mistral,
}

#: The class a provider key means when the spec names none. Legacy OpenAI/Azure keys and
#: custom endpoints retain Chat Completions; explicit API aliases select either protocol.
DEFAULT_CLASS_BY_PROVIDER: Mapping[str, str] = {
    "anthropic": "AnthropicModel",
    "openai": "OpenAIChatModel",
    "openai-chat": "OpenAIChatModel",
    "openai-responses": "OpenAIResponsesModel",
    "azure": "OpenAIChatModel",
    "azure-chat": "OpenAIChatModel",
    "azure-responses": "OpenAIResponsesModel",
    "ollama": "OpenAIChatModel",
    "openrouter": "OpenAIChatModel",
    "deepseek": "OpenAIChatModel",
    "groq": "OpenAIChatModel",
    "xai": "OpenAIChatModel",
    "bedrock": "BedrockConverseModel",
    "google": "GoogleModel",
    "google-vertex": "GoogleModel",
    "mistral": "MistralModel",
}


class ModelFactory:
    """Builds pydantic-ai models from :class:`ModelSpec` descriptions.

    Parameters:
        credentials: The :class:`CredentialResolver` that redeems ``Credential.reference``
            entries. Optional: a spec carrying its key inline, or none, needs no resolver, and
            a spec carrying a reference with no resolver is refused rather than sent anonymous.
    """

    def __init__(self, credentials: CredentialResolver | None = None) -> None:
        self._credentials = credentials

    async def build(self, spec: ModelSpec) -> Model:
        """Construct the model the spec describes."""
        secret = await self._secret_for(spec)
        return self.build_with_secret(spec, secret)

    def build_with_secret(self, spec: ModelSpec, secret: str | None) -> Model:
        """Construct the model with an already-resolved secret (or ``None``)."""
        class_name = spec.model_class or DEFAULT_CLASS_BY_PROVIDER.get(spec.provider)
        if class_name is None:
            if spec.base_url:
                class_name = "OpenAIChatModel"
            else:
                raise ModelBuildError(
                    f"The spec names provider {spec.provider!r}, which this factory does not know and which has no "
                    f"base_url to treat as an OpenAI-compatible endpoint. Known providers: "
                    f"{', '.join(sorted(DEFAULT_CLASS_BY_PROVIDER))}."
                )
        builder = BUILDERS.get(class_name)
        if builder is None:
            raise ModelBuildError(
                f"The spec asks for {class_name!r}, which this factory cannot build. Known classes: "
                f"{', '.join(sorted(BUILDERS))}."
            )
        return builder(spec, secret, profile_for(spec))

    def settings_for(self, spec: ModelSpec) -> dict[str, Any]:
        """:func:`model_settings_for`, as a method for callers holding a factory."""
        return model_settings_for(spec)

    async def _secret_for(self, spec: ModelSpec) -> str | None:
        credential: Credential = spec.credential
        if credential.kind == "none":
            return None
        if credential.kind == "api_key":
            return credential.secret
        if self._credentials is None:
            raise ModelBuildError(
                f"{spec.provider}:{spec.model} carries a credential reference and no resolver was supplied. "
                "A reference is redeemed by a CredentialResolver; the factory never guesses a key."
            )
        assert credential.reference_id is not None
        return await self._credentials.resolve(credential.reference_id, credential.version)


__all__ = [
    "BUILDERS",
    "DEFAULT_CLASS_BY_PROVIDER",
    "EFFORT_BUDGETS",
    "ModelBuildError",
    "ModelFactory",
    "anthropic_effort_for",
    "capabilities_for",
    "effort_for",
    "model_settings_for",
    "profile_for",
]
