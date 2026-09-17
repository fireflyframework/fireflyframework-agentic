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
``Usage`` model with explicit fields for cache tokens, and ships pricing for
the 16+ providers we care about. (It has no reasoning-token field; reasoning
tokens not already in ``output_tokens`` are folded into output by the caller —
see :func:`genai_prices_cost`.) The trade-off — shared
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

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from genai_prices import Usage as _GenAIUsage  # type: ignore[import-untyped]
from genai_prices import calc_price  # type: ignore[import-untyped]

from fireflyframework_agentic.config import get_config
from fireflyframework_agentic.models.claude import bare_claude_id
from fireflyframework_agentic.observability.metrics import default_metrics

logger = logging.getLogger(__name__)


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

    Runs first so a provider's authoritative per-call USD wins over the local
    estimate. Note: pydantic-ai 1.107 does not surface OpenRouter's cost on the
    result/usage, so ``provider_payload`` is currently populated only by custom
    integrations that pass the raw response through to ``record_call``.
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
      * ``Usage.output_tokens`` = ctx.output_tokens + ctx.reasoning_tokens, where
        ``ctx.reasoning_tokens`` is reasoning the provider does NOT already
        include in ``output_tokens`` — i.e. Gemini ``thoughts_tokens`` (OpenAI's
        reasoning is already in output, Anthropic folds thinking into output, so
        those callers pass ``0``). These bill at the output rate.

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
        # Bedrock ids carry a vendor prefix (e.g. "anthropic.claude-3-5-sonnet-latest")
        # and region/inference-profile variants genai-prices may not key on. Retry
        # on the bare model name with the vendor as the provider before giving up.
        if provider == "bedrock" and "." in model_ref:
            vendor, base = model_ref.split(".", 1)
            try:
                return float(calc_price(usage, base, provider_id=vendor).total_price)
            except LookupError:
                pass
        _warn_unknown_model(ctx.model)
        return None
    except Exception:  # noqa: BLE001
        logger.debug("genai-prices lookup raised for '%s'", ctx.model, exc_info=True)
        return None

    return float(result.total_price)


# ---------------------------------------------------------------------------
# The framework's own price rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceRow:
    """USD per million tokens for one model: input, output, and the cache multipliers.

    Anthropic prices a cache write at 1.25x input and a cache read at 0.10x input; the
    multipliers are on the row so a provider with a different rule can carry its own.
    """

    input_per_million: float
    output_per_million: float
    cache_write_multiplier: float = 1.25
    cache_read_multiplier: float = 0.10

    def cost(self, ctx: CostContext) -> float:
        per_token_in = self.input_per_million / 1_000_000
        per_token_out = self.output_per_million / 1_000_000
        return (
            ctx.input_tokens * per_token_in
            + ctx.cache_creation_tokens * per_token_in * self.cache_write_multiplier
            + ctx.cache_read_tokens * per_token_in * self.cache_read_multiplier
            + (ctx.output_tokens + ctx.reasoning_tokens) * per_token_out
        )


#: Rows genai-prices 0.0.66 does not carry, keyed by the model-id PREFIX (a dated snapshot, a
#: Vertex ``@version`` suffix and a Bedrock ``anthropic.`` prefix all resolve to the same row).
#: Anthropic first-party rates at the date of this release. A row is deleted the day
#: genai-prices prices the id, so the community table stays the source of record; until then
#: a Claude 5 call resolved to ``None`` — WARNING + ``cost_unknown`` on every call, and a host
#: in strict mode could not run the current generation at all.
FRAMEWORK_PRICE_TABLE: dict[str, PriceRow] = {
    "claude-opus-5": PriceRow(5.00, 25.00),
    "claude-sonnet-5": PriceRow(2.00, 10.00),
    "claude-fable-5": PriceRow(10.00, 50.00),
}


def _bare_model_ref(model: str) -> str:
    """``provider:`` prefix, Bedrock geo/vendor prefix and version, Vertex ``@version`` removed.

    The ``provider:`` split is on the FIRST colon; a Bedrock version suffix (``-v1:0``) also
    carries a colon, which is why it is stripped afterwards and never mistaken for a provider.
    """
    ref = model.split(":", 1)[1] if ":" in model else model
    return bare_claude_id(ref)


def framework_price_table_cost(ctx: CostContext) -> float | None:
    """Price a model from :data:`FRAMEWORK_PRICE_TABLE`, else return ``None``.

    Runs before :func:`genai_prices_cost` and answers only for the ids it carries, so it never
    shadows a community price. Match is by prefix on the bare id: ``claude-opus-5``,
    ``claude-opus-5-20260401``, ``anthropic.claude-opus-5`` and ``claude-opus-5@20260401`` are
    one row.
    """
    ref = _bare_model_ref(ctx.model)
    for prefix, row in FRAMEWORK_PRICE_TABLE.items():
        if ref == prefix or ref.startswith(prefix + "-") or ref.startswith(prefix + "@"):
            return row.cost(ctx)
    return None


DEFAULT_RESOLVERS: tuple[CostFn, ...] = (provider_reported_cost, framework_price_table_cost, genai_prices_cost)


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

    To override or extend pricing, compose your own resolver chain by
    prepending a custom ``CostFn`` to ``DEFAULT_RESOLVERS``. See
    ``examples/cost_tracking.py`` for the canonical pattern.
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
