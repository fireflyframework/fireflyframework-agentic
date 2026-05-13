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
import os
from pathlib import Path
from dotenv import load_dotenv

from fireflyframework_agentic.observability.budget import (
    BudgetGate,
    BudgetMode,
    BudgetRule,
    BudgetWindow,
    ScopeContext,
)
from fireflyframework_agentic.observability.cost import (
    DEFAULT_RESOLVERS,
    CallTier,
    CostContext,
)
from fireflyframework_agentic.observability.exporters import configure_exporters
from fireflyframework_agentic.observability.sinks import (
    EventBusSink,
    JSONLFileSink,
    OTelMetricsSink,
)
from fireflyframework_agentic.observability.usage import UsageTracker

load_dotenv()

_FIXED_PRICES = {"acme:internal-llm": (0.5e-6, 2.0e-6)}  # (input, output) per token.


def fixed_rate_cost(ctx: CostContext) -> float | None:
    """Return the negotiated USD cost for contractually-priced models."""
    price = _FIXED_PRICES.get(ctx.model)
    if price is None:
        return None
    input_price, output_price = price
    return ctx.input_tokens * input_price + ctx.output_tokens * output_price


def _try_attach_app_insights() -> bool:
    """Attempt to wire Azure Monitor exporters; return ``True`` on success.

    Reads ``APPLICATIONINSIGHTS_CONNECTION_STRING`` from the environment (or a
    ``.env`` loaded by the caller). Returns ``False`` when the variable is
    unset, the ``[azure]`` extra is missing, or the connection string is
    rejected — callers should fall back to the non-OTel sinks in that case.
    """
    cs = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not cs:
        print("APPLICATIONINSIGHTS_CONNECTION_STRING not set; skipping App Insights.")
        return False
    try:
        configure_exporters(
            service_name="firefly-cost-demo",
            azure_monitor_connection_string=cs,
            metric_export_interval_ms=5_000,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"App Insights export not enabled ({type(exc).__name__}: {exc}); "
            "falling back to local sinks."
        )
        return False
    print("App Insights exporters attached.")
    return True


def build_tracker(jsonl_path: Path, *, with_otel: bool) -> UsageTracker:
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
    sinks: list = [EventBusSink(), JSONLFileSink(jsonl_path)]
    if with_otel:
        sinks.insert(0, OTelMetricsSink())
    resolvers = [fixed_rate_cost, *DEFAULT_RESOLVERS]
    return UsageTracker(sinks=sinks, gate=gate, resolver=resolvers)


def main() -> None:
    app_insights_ready = _try_attach_app_insights()

    out = Path("/tmp/firefly-cost.jsonl")
    out.unlink(missing_ok=True)
    tracker = build_tracker(out, with_otel=app_insights_ready)

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
    print(json.dumps(rec, indent=2, sort_keys=True))
    print(f"\ncost_usd=${rec['cost_usd']:.6f}")


if __name__ == "__main__":
    main()
