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

"""Cost calculation for LLM API calls.

Provides a :class:`CostCalculator` protocol and two implementations:

* :class:`StaticPriceCostCalculator` — uses a configurable lookup table.
* :class:`GenAIPricesCostCalculator` — delegates to the ``genai-prices``
  library (optional dependency) for accurate, up-to-date pricing.

Use :func:`get_cost_calculator` to obtain the best available calculator.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Prices per 1 M tokens: (input_price, output_price)
_DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    # OpenAI
    "openai:gpt-4o": (2.50, 10.00),
    "openai:gpt-4o-mini": (0.15, 0.60),
    "openai:gpt-4.1": (2.00, 8.00),
    "openai:gpt-4.1-mini": (0.40, 1.60),
    "openai:gpt-4.1-nano": (0.10, 0.40),
    "openai:gpt-5": (2.50, 10.00),
    "openai:gpt-5-mini": (0.30, 1.20),
    "openai:gpt-5.2": (2.50, 10.00),
    "openai:o3": (2.00, 8.00),
    "openai:o3-mini": (1.10, 4.40),
    "openai:o4-mini": (1.10, 4.40),
    # Anthropic
    "anthropic:claude-sonnet-4-20250514": (3.00, 15.00),
    "anthropic:claude-3-5-sonnet-latest": (3.00, 15.00),
    "anthropic:claude-3-5-haiku-latest": (0.80, 4.00),
    "anthropic:claude-3-opus-latest": (15.00, 75.00),
    # Google
    "google:gemini-2.0-flash": (0.10, 0.40),
    "google:gemini-2.5-pro": (1.25, 10.00),
    "google:gemini-2.5-flash": (0.15, 0.60),
    # DeepSeek
    "deepseek:deepseek-chat": (0.28, 0.42),
    "deepseek:deepseek-reasoner": (0.55, 2.19),
    # Groq
    "groq:llama-3.3-70b-versatile": (0.59, 0.79),
    "groq:llama-3.1-8b-instant": (0.05, 0.08),
    # Mistral
    "mistral:mistral-large-latest": (2.00, 6.00),
    "mistral:mistral-small-latest": (0.10, 0.30),
    "mistral:codestral-latest": (0.30, 0.90),
    # Ollama (local — free)
    "ollama:": (0.0, 0.0),
}


@runtime_checkable
class CostCalculator(Protocol):
    """Protocol for computing the estimated USD cost of an LLM call."""

    def estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Return estimated cost in USD."""
        ...


class StaticPriceCostCalculator:
    """Cost calculator using a static lookup table.

    Parameters:
        prices: Mapping of model identifier to ``(input_price_per_M,
            output_price_per_M)`` in USD.  Defaults to a built-in table
            covering common OpenAI, Anthropic, Google, DeepSeek, and Groq
            models.
    """

    def __init__(self, prices: dict[str, tuple[float, float]] | None = None) -> None:
        self._prices = dict(_DEFAULT_PRICES)
        if prices:
            self._prices.update(prices)

    def estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost from the static price table.

        Performs an exact match first, then a prefix match (e.g.
        ``"openai:gpt-4o-2024-08-06"`` matches ``"openai:gpt-4o"``).
        Returns ``0.0`` if no match is found.
        """
        price = self._prices.get(model)
        if price is None:
            # Try prefix match: longest matching key wins
            best_key = ""
            for key in self._prices:
                if model.startswith(key) and len(key) > len(best_key):
                    best_key = key
            price = self._prices.get(best_key) if best_key else None
        if price is None:
            # Cross-provider alias matching: strip provider prefix and
            # try to match against known entries from the canonical provider.
            price = self._cross_provider_lookup(model)
        if price is None:
            return 0.0
        input_cost, output_cost = price
        return (input_tokens * input_cost + output_tokens * output_cost) / 1_000_000

    def _cross_provider_lookup(self, model: str) -> tuple[float, float] | None:
        """Attempt to match a model across providers.

        For proxy providers (Bedrock, Azure, Groq, etc.) strip the
        provider prefix and match the underlying model against known
        canonical entries.

        E.g. ``"bedrock:anthropic.claude-3-5-sonnet-latest"`` →
        strips ``"bedrock:anthropic."`` → matches ``"anthropic:claude-3-5-sonnet"``
        entries.  ``"azure:gpt-4o"`` → matches ``"openai:gpt-4o"``.
        """
        if ":" not in model:
            return None

        provider, _, model_name = model.partition(":")

        # Provider alias map: which canonical provider to search.
        alias_map: dict[str, str] = {
            "azure": "openai",
            "bedrock": "",  # Determined by model name below.
            "groq": "",
        }
        if provider not in alias_map:
            return None

        # For Bedrock, strip nested provider prefix (e.g. "anthropic." or "meta.").
        canonical = alias_map.get(provider, "")
        bare_name = model_name
        if provider == "bedrock" and "." in model_name:
            nested_provider, _, bare_name = model_name.partition(".")
            canonical = nested_provider

        if not canonical:
            # Try matching by model name patterns against all keys.
            best: tuple[float, float] | None = None
            best_len = 0
            for key, price in self._prices.items():
                _, _, key_name = key.partition(":")
                if key_name and bare_name.startswith(key_name) and len(key_name) > best_len:
                    best = price
                    best_len = len(key_name)
            return best

        # Search for canonical provider entries matching the bare model name.
        target_prefix = f"{canonical}:"
        best_price: tuple[float, float] | None = None
        best_key_len = 0
        for key, price in self._prices.items():
            if not key.startswith(target_prefix):
                continue
            canonical_model = key[len(target_prefix):]
            if bare_name.startswith(canonical_model) and len(canonical_model) > best_key_len:
                best_price = price
                best_key_len = len(canonical_model)
        return best_price


class GenAIPricesCostCalculator:
    """Cost calculator using the ``genai-prices`` library.

    Falls back to ``0.0`` if the library is not installed or the model
    is not found in its database.
    """

    def __init__(self) -> None:
        self._available = False
        self._find_model: object = None
        try:
            from genai_prices import find_model  # type: ignore[import-untyped]

            self._find_model = find_model
            self._available = True
        except ImportError:
            logger.debug("genai-prices is not installed; GenAIPricesCostCalculator will return 0.0 for all estimates.")

    @property
    def available(self) -> bool:
        """Whether the ``genai-prices`` library is importable."""
        return self._available

    def estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost using genai-prices.

        Returns ``0.0`` if the library is unavailable or the model
        cannot be resolved.
        """
        if not self._available or self._find_model is None:
            return 0.0
        try:
            # genai-prices expects provider:model format, which is what
            # Pydantic AI uses natively.
            parts = model.split(":", 1)
            provider = parts[0] if len(parts) > 1 else ""
            model_name = parts[1] if len(parts) > 1 else model
            price_info = self._find_model(model_name, provider=provider or None)  # type: ignore[operator]
            if price_info is None:
                return 0.0
            # genai-prices price_info has .input_price and .output_price per token
            input_price = getattr(price_info, "input_price", 0.0) or 0.0
            output_price = getattr(price_info, "output_price", 0.0) or 0.0
            return input_tokens * input_price + output_tokens * output_price
        except Exception:  # noqa: BLE001
            logger.debug("genai-prices lookup failed for model '%s'", model, exc_info=True)
            return 0.0


def get_cost_calculator(preference: str = "auto") -> CostCalculator:
    """Return the best available cost calculator.

    Parameters:
        preference: One of ``"auto"``, ``"genai_prices"``, or
            ``"static"``.  ``"auto"`` tries ``genai-prices`` first.
    """
    if preference == "static":
        return StaticPriceCostCalculator()
    if preference in ("auto", "genai_prices"):
        calc = GenAIPricesCostCalculator()
        if calc.available:
            return calc
        if preference == "genai_prices":
            logger.warning("genai-prices requested but not installed; falling back to static price table.")
    return StaticPriceCostCalculator()
