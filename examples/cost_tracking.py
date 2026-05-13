# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""End-to-end cost tracking example.

Demonstrates the *real* shape of cost tracking: every :class:`FireflyAgent`
you run automatically writes into ``default_usage_tracker``. This script
spins up three agents with different roles, runs them, and then prints the
aggregated per-agent / per-model breakdown — no manual ``record_call`` needed.

On top of that it shows:

* Attaching custom sinks (``JSONLFileSink``) to the *existing* tracker so
  every agent's cost lands on disk for offline inspection.
* Optional Azure Monitor export — when
  ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is in the environment, OTel
  metrics flow to Application Insights; otherwise the demo falls back to
  local sinks only.
* A custom :class:`CostFn` for contractually-priced models and a
  :class:`BudgetGate` with HARD/SOFT rules, both installed on the default
  tracker so they apply to real agent traffic.

Examples:

    # Real Sonnet pricing, budgets stay green.
    uv run python examples/cost_tracking.py

    # Pretend every LLM call costs $5; the $2 HARD daily limit trips on
    # the first agent and raises BudgetExceededError. The soft $4 lifetime
    # rule also fires and logs a warning.
    uv run python examples/cost_tracking.py --inflate-cost-usd 5

    # Inflate but stay under the HARD limit ($2 daily). Only the SOFT
    # lifetime rule will eventually log.
    uv run python examples/cost_tracking.py --inflate-cost-usd 0.5
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.exceptions import BudgetExceededError
from fireflyframework_agentic.observability.budget import (
    BudgetGate,
    BudgetMode,
    BudgetRule,
    BudgetWindow,
)
from fireflyframework_agentic.observability.cost import (
    DEFAULT_RESOLVERS,
    CostContext,
)
from fireflyframework_agentic.observability.exporters import configure_exporters
from fireflyframework_agentic.observability.sinks import (
    JSONLFileSink,
    OTelMetricsSink,
)
from fireflyframework_agentic.observability.usage import default_usage_tracker

load_dotenv()

MODEL = os.environ["MODEL"]
JSONL_PATH = Path("/tmp/firefly-cost.jsonl")

_FIXED_PRICES = {"acme:internal-llm": (0.5e-6, 2.0e-6)}


def fixed_rate_cost(ctx: CostContext) -> float | None:
    """Return the negotiated USD cost for contractually-priced models."""
    price = _FIXED_PRICES.get(ctx.model)
    if price is None:
        return None
    input_price, output_price = price
    return ctx.input_tokens * input_price + ctx.output_tokens * output_price


def make_inflated_resolver(per_call_usd: float):
    """Build a resolver that prices every call at a fixed USD amount."""
    def _resolver(_ctx: CostContext) -> float:
        return per_call_usd
    return _resolver


def _try_attach_app_insights() -> bool:
    """Wire Azure Monitor exporters if a connection string is present."""
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


def configure_default_tracker(*, with_otel: bool, inflate_cost_usd: float | None) -> None:
    """Install sinks, custom resolver, and budget gate on the singleton."""
    JSONL_PATH.unlink(missing_ok=True)
    default_usage_tracker.add_sink(JSONLFileSink(JSONL_PATH))
    if with_otel:
        default_usage_tracker.add_sink(OTelMetricsSink())

    resolvers = [fixed_rate_cost, *DEFAULT_RESOLVERS]
    if inflate_cost_usd is not None:
        print(f"Cost inflation enabled: every call priced at ${inflate_cost_usd:.4f}.")
        resolvers.insert(0, make_inflated_resolver(inflate_cost_usd))
    default_usage_tracker._resolver = resolvers

    default_usage_tracker._gate = BudgetGate(
        [
            BudgetRule(
                name="demo-daily",
                limit_usd=2.0,
                mode=BudgetMode.HARD,
                window=BudgetWindow.DAILY,
            ),
            BudgetRule(
                name="demo-lifetime",
                limit_usd=4.0,
                mode=BudgetMode.SOFT,
                window=BudgetWindow.LIFETIME,
            ),
        ]
    )


async def run_agents() -> None:
    comedian = FireflyAgent(
        name="comedian",
        model=MODEL,
        instructions=(
            "You are a fan of Douglas Adams. Tell short jokes in the style of "
            "The Hitchhiker's Guide to the Galaxy."
        ),
    )
    summarizer = FireflyAgent(
        name="summarizer",
        model=MODEL,
        instructions="Summarize the user's text in one sentence.",
    )
    translator = FireflyAgent(
        name="translator",
        model=MODEL,
        instructions="Translate the user's text to Spanish. Return only the translation.",
    )

    jokes = await comedian.run("Tell me three short jokes from The Hitchhiker's Guide to the Galaxy.")
    print(f"\n[comedian]\n{jokes.output}")

    summary = await summarizer.run(jokes.output)
    print(f"\n[summarizer]\n{summary.output}")

    translation = await translator.run(summary.output)
    print(f"\n[translator]\n{translation.output}")


def print_summary() -> None:
    summary = default_usage_tracker.get_summary()
    print("\n=== aggregated usage ===")
    print(f"total cost  : ${summary.total_cost_usd:.6f}")
    print(f"total tokens: {summary.total_tokens} "
          f"(in={summary.total_input_tokens}, out={summary.total_output_tokens})")
    print(f"requests    : {summary.total_requests}")
    print(f"records     : {summary.record_count}")

    _print_breakdown("by agent", summary.by_agent, width=12)
    _print_breakdown("by model", summary.by_model, width=40)

    print(f"\nper-call JSONL trail at {JSONL_PATH}:")
    print(JSONL_PATH.read_text(encoding="utf-8"), end="")


def _print_breakdown(title: str, group: dict, *, width: int) -> None:
    print(f"\n{title}:")
    for key, m in group.items():
        print(f"  {key:<{width}} cost=${m['cost_usd']:.6f}  tokens={m['total_tokens']}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--inflate-cost-usd",
        type=float,
        default=None,
        metavar="USD",
        help="Override real pricing: every LLM call is billed this fixed amount. "
             "Use to demonstrate the HARD/SOFT budget rules without burning real spend.",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    app_insights_ready = _try_attach_app_insights()
    configure_default_tracker(with_otel=app_insights_ready, inflate_cost_usd=args.inflate_cost_usd)
    try:
        await run_agents()
    except BudgetExceededError as exc:
        print(
            f"\n!! BudgetExceededError: rule '{exc.rule_name}' tripped at "
            f"${exc.spend_usd:.4f} > ${exc.limit_usd:.4f}. Aborting agent chain."
        )
    print_summary()


if __name__ == "__main__":
    asyncio.run(main())
