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

When you hit a model genai-prices doesn't know, the chain returns
``None`` after a WARNING + ``cost_unknown`` metric on every call.
Consumers (e.g. :class:`~fireflyframework_agentic.observability.usage.UsageTracker`)
decide whether to coerce ``None`` to ``0.0``, skip the metric, or alert.
Setting ``FIREFLY_AGENTIC_COST_STRICT=true`` (or ``config.cost_strict``)
turns unresolved costs into :class:`UnknownModelCostError` instead.
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import yaml
from genai_prices import Usage as _GenAIUsage  # type: ignore[import-untyped]
from genai_prices import calc_price  # type: ignore[import-untyped]

from fireflyframework_agentic.config import get_config
from fireflyframework_agentic.observability.metrics import default_metrics

logger = logging.getLogger(__name__)

OVERRIDES_PATH_ENV = "FIREFLY_AGENTIC_COST_OVERRIDES_PATH"


class UnknownModelCostError(RuntimeError):
    """Raised by :func:`resolve_cost` in strict mode when no resolver matches."""

    def __init__(self, model: str) -> None:
        super().__init__(f"No cost resolver could price model '{model}'")
        self.model = model


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


def _warn_unknown_model(model: str) -> None:
    """Fire WARNING + ``cost_unknown`` metric for every unresolved call.

    Per-call (no dedup) so dashboards can rate-alert on the metric.
    """
    logger.warning("genai-prices has no entry for model '%s'", model)
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
    WARNING on every call, returns None.
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
        _warn_unknown_model(ctx.model)
        return None
    except Exception:  # noqa: BLE001
        logger.debug("genai-prices lookup raised for '%s'", ctx.model, exc_info=True)
        return None

    return float(result.total_price)


@functools.lru_cache(maxsize=1)
def _load_overrides() -> dict[str, dict[str, float]]:
    """Load the local price-overrides YAML once per process.

    Reads the path from ``FIREFLY_AGENTIC_COST_OVERRIDES_PATH``. Returns
    ``{}`` if the env var is unset, the file is missing, or the file is
    malformed (with a WARNING in the malformed case). No hot reload.

    Expected schema::

        models:
          "openai:some-new-model":
            input_per_1k: 0.005
            output_per_1k: 0.015
    """
    path = os.environ.get(OVERRIDES_PATH_ENV)
    if not path:
        return {}
    if not os.path.isfile(path):
        logger.warning("Cost overrides file not found at '%s'; ignoring", path)
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Failed to load cost overrides from '%s': %s", path, exc)
        return {}
    if not isinstance(data, Mapping):
        logger.warning("Cost overrides at '%s' is not a mapping; ignoring", path)
        return {}
    models = data.get("models")
    if not isinstance(models, Mapping):
        logger.warning("Cost overrides at '%s' missing 'models' mapping; ignoring", path)
        return {}
    out: dict[str, dict[str, float]] = {}
    for key, entry in models.items():
        if not isinstance(key, str) or not isinstance(entry, Mapping):
            logger.warning("Skipping malformed override entry for key %r", key)
            continue
        try:
            out[key] = {
                "input_per_1k": float(entry.get("input_per_1k", 0.0) or 0.0),
                "output_per_1k": float(entry.get("output_per_1k", 0.0) or 0.0),
            }
        except (TypeError, ValueError):
            logger.warning("Skipping override entry with non-numeric rates: %r", key)
    return out


def overrides_cost(ctx: CostContext) -> float | None:
    """Terminal fallback: price ``ctx.model`` from the local overrides file.

    Returns ``None`` (no-op) when the env var is unset, the file is missing
    or malformed, or the model is not present. Same per-1k contract as the
    rest of the chain — total USD cost is returned.
    """
    overrides = _load_overrides()
    entry = overrides.get(ctx.model)
    if entry is None:
        return None
    input_rate = entry.get("input_per_1k", 0.0)
    output_rate = entry.get("output_per_1k", 0.0)
    # Cache and reasoning tokens are folded into input/output respectively,
    # mirroring genai_prices_cost's contract.
    input_total = ctx.input_tokens + ctx.cache_creation_tokens + ctx.cache_read_tokens
    output_total = ctx.output_tokens + ctx.reasoning_tokens
    return (input_total * input_rate + output_total * output_rate) / 1000.0


DEFAULT_RESOLVERS: tuple[CostFn, ...] = (provider_reported_cost, genai_prices_cost, overrides_cost)


def _strict_mode_from_config() -> bool:
    try:
        return bool(get_config().cost_strict)
    except Exception:  # noqa: BLE001
        logger.debug("Failed to read cost_strict from config; assuming False", exc_info=True)
        return False


def resolve_cost(
    ctx: CostContext,
    resolvers: Sequence[CostFn] | None = None,
    *,
    strict: bool | None = None,
) -> float | None:
    """Return the first non-None result from the chain, else ``None``.

    When ``strict`` is ``True`` (or unset and
    ``FIREFLY_AGENTIC_COST_STRICT`` / ``config.cost_strict`` is true),
    raise :class:`UnknownModelCostError` instead of returning ``None``.
    """
    chain = resolvers if resolvers is not None else DEFAULT_RESOLVERS
    for fn in chain:
        result = fn(ctx)
        if result is not None:
            return float(result)
    if strict is None:
        strict = _strict_mode_from_config()
    if strict:
        raise UnknownModelCostError(ctx.model)
    return None
