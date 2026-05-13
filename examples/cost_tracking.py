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
* A :class:`BudgetGate` with HARD/SOFT rules installed on the default
  tracker so it applies to real agent traffic.
* A model-specific :class:`CostFn` (``fixed_rate_cost``) for
  contractually-priced models. This resolver only fires when
  ``ctx.model == "acme:internal-llm"``; for any other model (including
  the Sonnet model used by the agents below) it returns ``None`` and
  the chain falls through to ``DEFAULT_RESOLVERS`` — i.e. the
  ``genai-prices`` catalog. It is included to show the *shape* of a
  contractual override; swap in your own model id and rates to use it.

Examples:

    # Real Sonnet pricing, budgets stay green.
    uv run python examples/cost_tracking.py

    # Inject an absurd per-token rate for the demo's model into
    # _FIXED_PRICES, so fixed_rate_cost overrides genai-prices and bills
    # roughly several dollars per call. The $2 HARD daily limit trips on
    # the first agent and raises BudgetExceededError; the $4 SOFT lifetime
    # rule also fires and logs a warning.
    uv run python examples/cost_tracking.py --inflated-prices
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.exceptions import BudgetExceededError
from fireflyframework_agentic.model_utils import get_model_identifier
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
MODEL_ID = get_model_identifier(MODEL)
JSONL_PATH = Path("/tmp/firefly-cost.jsonl")

# Per-model (input, output) USD/token overrides for contractually-priced LLMs.
# Add entries here when you have a negotiated rate that differs from the public
# catalog. Models not listed fall through to the next resolver in the chain.
_FIXED_PRICES: dict[str, tuple[float, float]] = {"acme:internal-llm": (0.5e-6, 2.0e-6)}

# $5/1k input + $10/1k output is ~100× real Sonnet pricing. With a typical
# joke/summary/translation call (~hundreds of tokens) it produces several USD
# of cost per call, so the first agent run breaches the $2 HARD daily limit.
_INFLATED_RATE: tuple[float, float] = (5e-3, 1e-2)


def fixed_rate_cost(ctx: CostContext) -> float | None:
    """Price a call at the negotiated rate for contractually-priced models.

    Returns ``None`` for any model not present in :data:`_FIXED_PRICES`, which
    lets the next resolver in the chain handle it (typically genai-prices for
    public catalog pricing). The demo agents below run on Sonnet, so in a
    default run this resolver always returns ``None``; it is wired up to
    illustrate the *pattern* for swapping in your own model id and rates.
    """
    price = _FIXED_PRICES.get(ctx.model)
    if price is None:
        return None
    input_price, output_price = price
    return ctx.input_tokens * input_price + ctx.output_tokens * output_price


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


def configure_default_tracker(*, with_otel: bool, inflated_prices: bool) -> None:
    """Install sinks, custom resolver, and budget gate on the singleton."""
    JSONL_PATH.unlink(missing_ok=True)
    default_usage_tracker.add_sink(JSONLFileSink(JSONL_PATH))
    if with_otel:
        default_usage_tracker.add_sink(OTelMetricsSink())

    if inflated_prices:
        _FIXED_PRICES[MODEL_ID] = _INFLATED_RATE
        pi, po = _INFLATED_RATE
        print(f"Inflated prices enabled for '{MODEL_ID}': ${pi}/input-token, ${po}/output-token.")

    default_usage_tracker._resolver = [fixed_rate_cost, *DEFAULT_RESOLVERS]

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
        "--inflated-prices",
        action="store_true",
        help="Inject an absurd per-token rate for the demo's model into _FIXED_PRICES "
             "so fixed_rate_cost overrides genai-prices. Used to demonstrate the "
             "HARD/SOFT budget rules without burning real spend.",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    app_insights_ready = _try_attach_app_insights()
    configure_default_tracker(with_otel=app_insights_ready, inflated_prices=args.inflated_prices)
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
