# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""End-to-end cost tracking example.

Demonstrates:

* A custom :class:`CostFn` (``fixed_rate_cost``) inserted in front of the
  default resolver chain — useful for contractually-fixed-price models.
* A :class:`BudgetGate` with two rules: a tenant-scoped HARD daily limit
  and an agent-scoped SOFT lifetime limit.
* A custom JSONL sink running alongside the default :class:`OTelMetricsSink`
  and :class:`EventBusSink`.
* One synthetic record that exercises cache tokens and ``CallTier.BATCH``
  so every axis lights up.
"""

from __future__ import annotations

import json
from pathlib import Path

from fireflyframework_agentic.observability.budget import (
    BudgetGate,
    BudgetMode,
    BudgetRule,
    BudgetWindow,
    ScopeContext,
)
from fireflyframework_agentic.observability.cost import (
    CallTier,
    CostContext,
    DEFAULT_RESOLVERS,
)
from fireflyframework_agentic.observability.sinks import (
    EventBusSink,
    JSONLFileSink,
    OTelMetricsSink,
)
from fireflyframework_agentic.observability.usage import UsageRecord, UsageTracker

_FIXED_PRICES = {"acme:internal-llm": (0.5e-6, 2.0e-6)}  # (input, output) per token.


def fixed_rate_cost(ctx: CostContext) -> float | None:
    """Return the negotiated USD cost for contractually-priced models."""
    price = _FIXED_PRICES.get(ctx.model)
    if price is None:
        return None
    input_price, output_price = price
    return ctx.input_tokens * input_price + ctx.output_tokens * output_price


def build_tracker(jsonl_path: Path) -> UsageTracker:
    gate = BudgetGate(
        [
            BudgetRule(
                name="acme-daily",
                limit_usd=5.0,
                mode=BudgetMode.HARD,
                window=BudgetWindow.DAILY,
                match={"tenant": "acme"},
            ),
            BudgetRule(
                name="writer-lifetime",
                limit_usd=100.0,
                mode=BudgetMode.SOFT,
                window=BudgetWindow.LIFETIME,
                match={"agent": "writer"},
            ),
        ]
    )
    sinks = [OTelMetricsSink(), EventBusSink(), JSONLFileSink(jsonl_path)]
    resolvers = [fixed_rate_cost, *DEFAULT_RESOLVERS]
    return UsageTracker(sinks=sinks, gate=gate, resolver=resolvers)


def main() -> None:
    out = Path("/tmp/firefly-cost.jsonl")
    out.unlink(missing_ok=True)
    tracker = build_tracker(out)

    tracker.record_call(
        model="anthropic:claude-3-5-sonnet-latest",
        input_tokens=1_000,
        output_tokens=500,
        cache_creation_tokens=2_000,
        cache_read_tokens=8_000,
        tier=CallTier.BATCH,
        agent="writer",
        correlation_id="demo-run-1",
        scope_ctx=ScopeContext(
            tenant="acme",
            agent="writer",
            correlation_id="demo-run-1",
            labels={"env": "prod"},
        ),
    )

    line = out.read_text(encoding="utf-8").splitlines()[0]
    rec = json.loads(line)
    print(f"emitted record cost_usd=${rec['cost_usd']:.6f}")


if __name__ == "__main__":
    main()
