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

"""Centralized model identity extraction for multi-provider support.

Provides helpers that work with both ``"provider:model"`` strings and
:class:`pydantic_ai.models.Model` objects, enabling the framework's
observability and resilience layers to handle any PydanticAI-supported
provider uniformly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.models import Model

# Defensive fallback only: the provider is normally read from the model's own
# ``_provider.name`` (every pydantic-ai provider implements it). This map covers
# any object that lacks a provider. Class names track pydantic-ai 1.x.
_CLASS_TO_PROVIDER: dict[str, str] = {
    "AnthropicModel": "anthropic",
    "BedrockConverseModel": "bedrock",
    "OpenAIChatModel": "openai",
    "OpenAIResponsesModel": "openai",
    "GoogleModel": "google",
    "GeminiModel": "google",  # legacy alias
    "GroqModel": "groq",
    "MistralModel": "mistral",
    "OllamaModel": "ollama",
    "CohereModel": "cohere",
    "XaiModel": "xai",
    "HuggingFaceModel": "huggingface",
    "CerebrasModel": "cerebras",
    "OpenRouterModel": "openrouter",
}

# Maps model name substrings/prefixes to their underlying model family.
_MODEL_FAMILY_PATTERNS: list[tuple[str, str]] = [
    ("claude", "anthropic"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("gemini", "google"),
    ("grok", "xai"),
    ("llama", "meta"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("deepseek", "deepseek"),
    ("command", "cohere"),
]

# Maps provider identifiers to their underlying model family.
_PROVIDER_TO_FAMILY: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "azure": "openai",
    "google": "google",
    "groq": "unknown",  # multi-vendor proxy; family comes from the model name.
    "mistral": "mistral",
    "ollama": "unknown",  # multi-vendor; family comes from the model name.
    "deepseek": "deepseek",
    "cohere": "cohere",
    "bedrock": "unknown",  # Bedrock is a proxy; family depends on model name.
    "openrouter": "unknown",  # multi-vendor proxy; family comes from the model name.
}


def extract_model_info(model: str | Model | None) -> tuple[str, str]:
    """Return ``(provider, model_name)`` from a model identifier.

    Examples::

        >>> extract_model_info("openai:gpt-4o")
        ('openai', 'gpt-4o')
        >>> extract_model_info("bedrock:anthropic.claude-3-5-sonnet-latest")
        ('bedrock', 'anthropic.claude-3-5-sonnet-latest')
        >>> extract_model_info(None)
        ('', '')

    For :class:`pydantic_ai.models.Model` objects the provider is inferred
    from the class name, and for ``OpenAIChatModel`` the internal
    ``_provider`` is inspected to distinguish OpenAI from Azure etc.
    """
    if model is None:
        return ("", "")

    if isinstance(model, str):
        if ":" in model:
            provider, _, model_name = model.partition(":")
            return (provider, model_name)
        return ("", model)

    # Model object — prefer the provider's own ``.name``. Every pydantic-ai
    # provider implements it with a correct, fine-grained id (openai, google,
    # xai, cerebras, openrouter, azure, deepseek, bedrock, groq, mistral, cohere,
    # huggingface), which also distinguishes OpenAI-compatible backends (Azure,
    # DeepSeek, OpenRouter) that share the OpenAI model classes. Fall back to the
    # class-name map only for an object without a provider.
    prov = getattr(getattr(model, "_provider", None), "name", None)
    provider = prov or _CLASS_TO_PROVIDER.get(type(model).__name__, "")
    model_name = getattr(model, "model_name", "") or ""
    return (provider, model_name)


def get_model_identifier(model: str | Model | None) -> str:
    """Return a normalized ``"provider:model"`` string.

    Examples::

        >>> get_model_identifier("openai:gpt-4o")
        'openai:gpt-4o'
        >>> get_model_identifier(None)
        ''
    """
    provider, model_name = extract_model_info(model)
    if not provider and not model_name:
        return ""
    if not provider:
        return model_name
    return f"{provider}:{model_name}"


def detect_model_family(model: str | Model | None) -> str:
    """Return the underlying model family for a model identifier.

    Resolves through provider layers so that proxy providers like
    Bedrock, Azure, and Groq map to the correct family.

    Returns one of: ``'anthropic'``, ``'openai'``, ``'google'``,
    ``'meta'``, ``'mistral'``, ``'deepseek'``, ``'cohere'``, or
    ``'unknown'``.

    Examples::

        >>> detect_model_family("bedrock:anthropic.claude-3-5-sonnet-latest")
        'anthropic'
        >>> detect_model_family("azure:gpt-4o")
        'openai'
        >>> detect_model_family("groq:llama-3.3-70b")
        'meta'
    """
    provider, model_name = extract_model_info(model)
    if not provider and not model_name:
        return "unknown"

    # Resolve from the MODEL NAME only — this handles proxy providers like
    # Bedrock/Groq/OpenRouter where the model name carries the family. Scanning
    # the provider token too would misfire (e.g. ``ollama`` contains ``llama``).
    name = model_name.lower()
    for pattern, family in _MODEL_FAMILY_PATTERNS:
        if pattern in name:
            return family

    # Fall back to provider-level mapping.
    if provider:
        return _PROVIDER_TO_FAMILY.get(provider, "unknown")

    return "unknown"


def serialize_model_messages(messages: Sequence[ModelMessage]) -> list[Any]:
    """Serialize pydantic-ai ``ModelMessage`` objects to a JSON-able list.

    Uses pydantic-ai's canonical ``ModelMessagesTypeAdapter`` so the full,
    model-agnostic message structure (typed parts, tool calls, usage, kinds)
    survives a round-trip through :func:`deserialize_model_messages`. A plain
    ``list[Any]`` dump loses the typed parts on reload — this does not.
    """
    if not messages:
        return []
    return ModelMessagesTypeAdapter.dump_python(list(messages), mode="json")


def deserialize_model_messages(data: Any) -> list[ModelMessage]:
    """Reconstruct ``ModelMessage`` objects produced by :func:`serialize_model_messages`."""
    if not data:
        return []
    return list(ModelMessagesTypeAdapter.validate_python(data))
