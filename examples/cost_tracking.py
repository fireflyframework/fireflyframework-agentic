# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""End-to-end cost tracking example.

Demonstrates the *real* shape of cost tracking: every :class:`FireflyAgent`
you run automatically writes into ``default_usage_tracker``. This script
spins up three agents with different roles, runs them, and then prints the
aggregated per-agent / per-model breakdown — no manual ``record_call`` needed.

On top of that it shows:

* Attaching custom sinks (``JSONLFileSink``, ``OTelMetricsSink``) to the
  *existing* tracker so every agent's cost lands on disk for offline
  inspection and is emitted via the OpenTelemetry API. Configuring the OTel
  SDK/exporters (where those metrics ultimately land) is the host's job.
* A :class:`BudgetGate` with HARD/SOFT rules installed on the default
  tracker so it applies to real agent traffic.
* A model-specific :class:`CostFn` (``fixed_rate_cost``) backed by
  :data:`_FIXED_PRICES`, which is keyed by the demo's ``MODEL_ID`` with
  absurd per-token rates. The resolver is only wired into the chain when
  ``--inflated-prices`` is passed; otherwise the chain runs the default
  ``genai-prices`` catalog and budgets stay green.

Examples:

    # Real model pricing
    uv run python examples/cost_tracking.py

    # fixed_rate_cost is prepended to the chain, looks up MODEL_ID in
    # _FIXED_PRICES, and bills several dollars per call. The $2 HARD
    # daily limit trips on the first agent and raises BudgetExceededError;
    # the $4 SOFT lifetime rule also fires and logs a warning.
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
from fireflyframework_agentic.observability.cost_resolvers import (
    DEFAULT_RESOLVERS,
    CostContext,
)
from fireflyframework_agentic.observability.sinks import (
    JSONLFileSink,
    OTelMetricsSink,
)
from fireflyframework_agentic.observability.usage import default_usage_tracker

load_dotenv()

MODEL = os.environ["MODEL"]
MODEL_ID = get_model_identifier(MODEL)
JSONL_PATH = Path("/tmp/firefly-cost.jsonl")

# Per-model (input, output) USD/token overrides. The entry for MODEL_ID uses
# absurd per-token rates (~100× real Sonnet pricing): with a typical
# joke/summary/translation call (~hundreds of tokens) each call costs several
# USD, so the very first agent run breaches the $2 HARD daily budget rule.
# Only consulted when --inflated-prices wires fixed_rate_cost into the chain.
_FIXED_PRICES: dict[str, tuple[float, float]] = {MODEL_ID: (5e-3, 1e-2)}
# _FIXED_PRICES = {"acme:internal-llm": (0.5e-6, 2.0e-6)}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--inflated-prices",
        action="store_true",
        help="Wire fixed_rate_cost (with the absurd rates in _FIXED_PRICES) into the "
        "resolver chain so it overrides genai-prices. Used to demonstrate the "
        "HARD/SOFT budget rules without burning real spend.",
    )
    return p.parse_args()


def fixed_rate_cost(ctx: CostContext) -> float | None:
    """Price a call at the rate in :data:`_FIXED_PRICES`, or fall through."""
    price = _FIXED_PRICES.get(ctx.model)
    if price is None:
        return None
    input_price, output_price = price
    return ctx.input_tokens * input_price + ctx.output_tokens * output_price


def configure_default_tracker(*, inflated_prices: bool) -> None:
    """Install sinks, optional fixed-rate resolver, and budget gate on the singleton."""
    JSONL_PATH.unlink(missing_ok=True)
    default_usage_tracker.add_sink(JSONLFileSink(JSONL_PATH))
    default_usage_tracker.add_sink(OTelMetricsSink())

    resolvers = list(DEFAULT_RESOLVERS)
    if inflated_prices:
        pi, po = _FIXED_PRICES[MODEL_ID]
        print(f"Inflated prices enabled for '{MODEL_ID}': ${pi}/input-token, ${po}/output-token.")
        resolvers.insert(0, fixed_rate_cost)
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
            "You are a fan of Douglas Adams. Tell short jokes in the style of The Hitchhiker's Guide to the Galaxy."
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
    print(f"total tokens: {summary.total_tokens} (in={summary.total_input_tokens}, out={summary.total_output_tokens})")
    print(f"requests    : {summary.total_requests}")
    print(f"records     : {summary.record_count}")

    _print_breakdown("by agent", summary.by_agent, width=12)
    _print_breakdown("by model", summary.by_model, width=40)

    # The sink writes per record AFTER the BudgetGate commits. If the gate
    # raised mid-call (HARD breach), no sink ever fired and the file may
    # not exist yet — surface that explicitly instead of crashing.
    if JSONL_PATH.exists():
        print(f"\nper-call JSONL trail at {JSONL_PATH}:")
        print(JSONL_PATH.read_text(encoding="utf-8"), end="")
    else:
        print(f"\nno JSONL trail at {JSONL_PATH} (budget gate aborted before any sink fired).")


def _print_breakdown(title: str, group: dict, *, width: int) -> None:
    print(f"\n{title}:")
    for key, m in group.items():
        print(f"  {key:<{width}} cost=${m['cost_usd']:.6f}  tokens={m['total_tokens']}")


async def main() -> None:
    args = parse_args()
    configure_default_tracker(inflated_prices=args.inflated_prices)
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
