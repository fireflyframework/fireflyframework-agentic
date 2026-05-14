# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Cost resolution chain.

Each resolver is a plain callable that returns ``float | None``. The
default chain (:data:`DEFAULT_RESOLVERS`) tries provider-reported cost
first and falls back to ``genai-prices``. Users extend the chain by
passing their own list to :func:`resolve_cost`.

Why genai-prices
================
We compute per-call cost from token counts and a per-model price table.
The provider response never carries a dollar amount (except OpenRouter,
which is why :func:`provider_reported_cost` runs first), so a local price
table is unavoidable.

We picked `pydantic/genai-prices <https://github.com/pydantic/genai-prices>`_
because it is Pydantic-maintained (fits our stack), exposes a typed
``Usage`` model with explicit fields for cache and reasoning tokens, and
ships pricing for the 16+ providers we care about. The trade-off — shared
by every option in this space — is that the data is community-curated
YAML, not a machine-readable provider feed, so it lags new model variants
by days to weeks.

Alternatives considered:

* `AgentOps tokencost <https://github.com/agentops-ai/tokencost>`_ —
  similar coverage, similar curation lag, also bundles tiktoken. Viable as
  a secondary source if cross-checking becomes worthwhile.
* `LiteLLM model_prices_and_context_window.json <https://github.com/BerriAI/litellm>`_
  — broadest coverage and fastest update cadence in the ecosystem, but
  consuming it standalone (without the LiteLLM proxy) means tracking a
  schema we do not control. Worth revisiting as a fallback resolver.
* LiteLLM proxy / Helicone / Portkey — gateway products that compute cost
  server-side. The right answer if we also need multi-provider routing,
  per-key budget caps, or hosted spend dashboards; today we don't.
* Provider billing APIs (Anthropic Admin, OpenAI Usage, Azure Cost Mgmt)
  — the only authoritative numbers, but lag from minutes (Anthropic
  usage) to ~24h (cost). Use them to reconcile, not to gate live calls.

When you hit a model genai-prices doesn't know, the chain currently
falls through to ``0.0`` after a one-shot warning + ``cost_unknown``
metric. That silent-zero is tracked in
`issue #174 <https://github.com/fireflyframework/fireflyframework-agentic/issues/174>`_.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from genai_prices import Usage as _GenAIUsage  # type: ignore[import-untyped]
from genai_prices import calc_price  # type: ignore[import-untyped]

from fireflyframework_agentic.observability.metrics import default_metrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CostContext:
    """Inputs to a cost resolver."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    provider_payload: Mapping[str, Any] | None = None


CostFn = Callable[[CostContext], float | None]


def provider_reported_cost(ctx: CostContext) -> float | None:
    """Return cost from a known provider-response field, else None.

    Supported sources:
      * OpenRouter — ``provider_payload["usage"]["cost"]`` (USD float).
    """
    payload = ctx.provider_payload
    if not payload:
        return None
    usage = payload.get("usage") if isinstance(payload, Mapping) else None
    if not isinstance(usage, Mapping):
        return None
    cost = usage.get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        return float(cost)
    return None


_UNKNOWN_MODEL_WARNED: set[str] = set()


def _warn_unknown_model_once(model: str) -> None:
    if model in _UNKNOWN_MODEL_WARNED:
        return
    _UNKNOWN_MODEL_WARNED.add(model)
    logger.warning("genai-prices has no entry for model '%s'; cost recorded as 0.0", model)
    try:
        default_metrics.record_error(operation="cost_unknown")
    except Exception:  # noqa: BLE001
        logger.debug("Failed to emit cost_unknown metric", exc_info=True)


def genai_prices_cost(ctx: CostContext) -> float | None:
    """Compute cost via :func:`genai_prices.calc_price`, else return ``None``.

    Token mapping:
      * ``Usage.input_tokens`` = ctx.input_tokens + cache_creation_tokens + cache_read_tokens
        (genai-prices subtracts cache portions internally).
      * ``Usage.cache_write_tokens`` = ctx.cache_creation_tokens.
      * ``Usage.cache_read_tokens`` = ctx.cache_read_tokens.
      * ``Usage.output_tokens`` = ctx.output_tokens + ctx.reasoning_tokens
        (reasoning tokens bill at the output rate).

    On unknown model (LookupError): emits ``cost_unknown`` metric +
    WARNING once per model, returns None.
    """
    parts = ctx.model.split(":", 1)
    if len(parts) == 2:
        provider, model_ref = parts
    else:
        provider, model_ref = None, ctx.model

    usage = _GenAIUsage(
        input_tokens=ctx.input_tokens + ctx.cache_creation_tokens + ctx.cache_read_tokens,
        cache_write_tokens=ctx.cache_creation_tokens or None,
        cache_read_tokens=ctx.cache_read_tokens or None,
        output_tokens=ctx.output_tokens + ctx.reasoning_tokens,
    )
    try:
        result = calc_price(usage, model_ref, provider_id=provider)
    except LookupError:
        _warn_unknown_model_once(ctx.model)
        return None
    except Exception:  # noqa: BLE001
        logger.debug("genai-prices lookup raised for '%s'", ctx.model, exc_info=True)
        return None

    return float(result.total_price)


DEFAULT_RESOLVERS: tuple[CostFn, ...] = (provider_reported_cost, genai_prices_cost)


def resolve_cost(ctx: CostContext, resolvers: Sequence[CostFn] | None = None) -> float:
    """Return the first non-None result from the chain, else 0.0."""
    chain = resolvers if resolvers is not None else DEFAULT_RESOLVERS
    for fn in chain:
        result = fn(ctx)
        if result is not None:
            return float(result)
    return 0.0
