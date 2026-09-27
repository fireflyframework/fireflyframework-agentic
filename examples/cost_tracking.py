# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Record real agent usage in an isolated ledger, JSONL file, and OTel metrics.

Set FIREFLY_AGENTIC_DEFAULT_MODEL and its credentials. Running this example
makes up to three billable requests. The JSONL audit is written to a new
firefly-cost-* temporary directory printed at completion; existing files are
not deleted. The host must configure OTel exporters to send metrics elsewhere.

Pass --inflated-prices to use an intentionally inflated local tariff and
exercise hard/soft BudgetGate rules. This changes accounting, not the provider
bill. Whether a rule trips depends on the actual tokens reported.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
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
from fireflyframework_agentic.observability.usage import UsageTracker

load_dotenv()

MODEL = os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna"))
MODEL_ID = get_model_identifier(MODEL)


# Per-model (input, output) USD/token overrides. The entry for MODEL_ID uses
# deliberately inflated rates to make budget breaches easier to observe.
# Only consulted when --inflated-prices wires fixed_rate_cost into the chain.
_FIXED_PRICES: dict[str, tuple[float, float]] = {MODEL_ID: (5e-3, 1e-2)}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--inflated-prices",
        action="store_true",
        help="Wire fixed_rate_cost (with the absurd rates in _FIXED_PRICES) into the "
        "resolver chain so it overrides genai-prices. Used to demonstrate the "
        "HARD/SOFT budget rules using an illustrative tariff; actual calls are still billable.",
    )
    return p.parse_args()


def fixed_rate_cost(ctx: CostContext) -> float | None:
    """Price a call at the rate in :data:`_FIXED_PRICES`, or fall through."""
    price = _FIXED_PRICES.get(ctx.model)
    if price is None:
        return None
    input_price, output_price = price
    return ctx.input_tokens * input_price + ctx.output_tokens * output_price


def create_tracker(*, inflated_prices: bool, path: Path) -> UsageTracker:
    """Create an isolated ledger with file and OpenTelemetry sinks."""

    resolvers = list(DEFAULT_RESOLVERS)
    if inflated_prices:
        pi, po = _FIXED_PRICES[MODEL_ID]
        print(f"Inflated prices enabled for '{MODEL_ID}': ${pi}/input-token, ${po}/output-token.")
        resolvers.insert(0, fixed_rate_cost)
    gate = BudgetGate(
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

    return UsageTracker(resolver=resolvers, gate=gate, sinks=[JSONLFileSink(path), OTelMetricsSink()])


async def run_agents(tracker: UsageTracker) -> None:
    comedian = FireflyAgent(
        name="comedian",
        model=MODEL,
        usage_tracker=tracker,
        instructions=(
            "You are a fan of Douglas Adams. Tell short jokes in the style of The Hitchhiker's Guide to the Galaxy."
        ),
    )
    summarizer = FireflyAgent(
        name="summarizer",
        model=MODEL,
        usage_tracker=tracker,
        instructions="Summarize the user's text in one sentence.",
    )
    translator = FireflyAgent(
        name="translator",
        model=MODEL,
        usage_tracker=tracker,
        instructions="Translate the user's text to Spanish. Return only the translation.",
    )

    jokes = await comedian.run("Tell me three short jokes from The Hitchhiker's Guide to the Galaxy.")
    print(f"\n[comedian]\n{jokes.output}")

    summary = await summarizer.run(jokes.output)
    print(f"\n[summarizer]\n{summary.output}")

    translation = await translator.run(summary.output)
    print(f"\n[translator]\n{translation.output}")


def print_summary(tracker: UsageTracker, path: Path) -> None:
    summary = tracker.get_summary()
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
    if path.exists():
        print(f"\nper-call JSONL trail at {path}:")
        print(path.read_text(encoding="utf-8"), end="")
    else:
        print(f"\nno JSONL trail at {path} (budget gate aborted before any sink fired).")


def _print_breakdown(title: str, group: dict, *, width: int) -> None:
    print(f"\n{title}:")
    for key, m in group.items():
        print(f"  {key:<{width}} cost=${m['cost_usd']:.6f}  tokens={m['total_tokens']}")


async def main() -> None:
    args = parse_args()
    path = Path(tempfile.mkdtemp(prefix="firefly-cost-")) / "usage.jsonl"
    tracker = create_tracker(inflated_prices=args.inflated_prices, path=path)
    try:
        await run_agents(tracker)
    except BudgetExceededError as exc:
        print(
            f"\n!! BudgetExceededError: rule '{exc.rule_name}' tripped at "
            f"${exc.spend_usd:.4f} > ${exc.limit_usd:.4f}. Aborting agent chain."
        )
    print_summary(tracker, path)


if __name__ == "__main__":
    asyncio.run(main())
