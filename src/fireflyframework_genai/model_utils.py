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

"""Centralized model identity extraction for multi-provider support.

Provides helpers that work with both ``"provider:model"`` strings and
:class:`pydantic_ai.models.Model` objects, enabling the framework's
observability and resilience layers to handle any PydanticAI-supported
provider uniformly.
"""

from __future__ import annotations

from pydantic_ai.models import Model

# Maps PydanticAI model class names to provider identifiers.
_CLASS_TO_PROVIDER: dict[str, str] = {
    "AnthropicModel": "anthropic",
    "BedrockConverseModel": "bedrock",
    "OpenAIChatModel": "openai",
    "GeminiModel": "google",
    "GroqModel": "groq",
    "MistralModel": "mistral",
    "OllamaModel": "ollama",
    "DeepSeekModel": "deepseek",
    "CohereModel": "cohere",
}

# Maps OpenAI-based provider class names to more specific provider IDs.
_OPENAI_PROVIDER_TO_ID: dict[str, str] = {
    "AzureProvider": "azure",
    "DeepSeekProvider": "deepseek",
    "OpenAIProvider": "openai",
}

# Maps model name substrings/prefixes to their underlying model family.
_MODEL_FAMILY_PATTERNS: list[tuple[str, str]] = [
    ("claude", "anthropic"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("gemini", "google"),
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
    "groq": "meta",
    "mistral": "mistral",
    "ollama": "unknown",
    "deepseek": "deepseek",
    "cohere": "cohere",
    "bedrock": "unknown",  # Bedrock is a proxy; family depends on model name.
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

    # Model object — inspect class name.
    cls_name = type(model).__name__
    provider = _CLASS_TO_PROVIDER.get(cls_name, "")

    # For OpenAIChatModel, check internal provider for Azure/DeepSeek.
    if cls_name == "OpenAIChatModel":
        internal_provider = getattr(model, "_provider", None)
        if internal_provider is not None:
            prov_cls = type(internal_provider).__name__
            provider = _OPENAI_PROVIDER_TO_ID.get(prov_cls, provider)

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

    # First, try to resolve from the model name — this handles proxy
    # providers like Bedrock where the model name contains the family.
    combined = f"{provider}:{model_name}".lower() if provider else model_name.lower()
    for pattern, family in _MODEL_FAMILY_PATTERNS:
        if pattern in combined:
            return family

    # Fall back to provider-level mapping.
    if provider:
        return _PROVIDER_TO_FAMILY.get(provider, "unknown")

    return "unknown"
