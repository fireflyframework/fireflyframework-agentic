# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Cost resolution chain.

Each resolver is a plain callable that returns ``float | None``. The
default chain (:data:`DEFAULT_RESOLVERS`) tries provider-reported cost
first and falls back to ``genai-prices``. Users extend the chain by
passing their own list to :func:`resolve_cost`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fireflyframework_agentic.observability.cost.tiers import CallTier

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
    tier: CallTier = CallTier.STANDARD
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
