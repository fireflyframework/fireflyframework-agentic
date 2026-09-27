#!/usr/bin/env python3
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Inspect provider cache usage and reproduce an illustrative cost calculation.

The default run is offline. Pass --live to make six billable requests using
FIREFLY_AGENTIC_DEFAULT_MODEL (MODEL is a legacy fallback). Cache eligibility,
minimum prompt length, retention, and prices vary by model. Omitting middleware
does not disable a provider's automatic cache, so this is not a controlled
uncached-versus-cached benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.agents.prompt_cache import CacheStatistics, PromptCacheMiddleware
from fireflyframework_agentic.models import ModelOptions

LEGAL_ASSISTANT_PROMPT = (
    """You are an expert legal assistant specializing in contract analysis.

Your expertise includes:
- Contract law and interpretation
- Risk identification and assessment
- Compliance verification
- Legal terminology and definitions

When analyzing contracts, you should:
1. Identify key terms and conditions
2. Highlight potential risks or unusual clauses
3. Verify standard legal protections
4. Note any missing standard clauses
5. Summarize obligations for each party

Standard contract elements to review:
- Parties and effective dates
- Scope of services/products
- Payment terms and schedules
- Termination conditions
- Liability and indemnification clauses
- Intellectual property rights
- Confidentiality provisions
- Dispute resolution mechanisms
- Force majeure clauses
- Governing law and jurisdiction

Always provide clear, actionable analysis that non-legal stakeholders can understand.

For questions about specific contract sections, provide detailed analysis with
references to relevant legal principles and potential implications.

"""
    * 10
)  # Repeat to create a ~5000 token system prompt


async def demo_live_caching(*, with_middleware: bool) -> None:
    stats = CacheStatistics()
    agent = FireflyAgent(
        "cache-observer",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "anthropic:claude-sonnet-5")),
        model_options=ModelOptions(max_tokens=2048),
        instructions=LEGAL_ASSISTANT_PROMPT,
        middleware=[PromptCacheMiddleware()] if with_middleware else [],
        auto_register=False,
    )
    print(f"PromptCacheMiddleware enabled: {with_middleware}")
    for question in (
        "Define termination clauses briefly.",
        "Define indemnification briefly.",
        "What is force majeure?",
    ):
        result = await agent.run(question)
        usage = result.usage
        stats.record_usage(usage.cache_write_tokens, usage.cache_read_tokens)
        print(result.output)
        print(f"Cache tokens reported: written={usage.cache_write_tokens}, read={usage.cache_read_tokens}")
    print(f"Requests reporting cache reads: {stats.cache_hit_rate():.1%}")


def illustrative_costs() -> dict[str, float]:
    """Compute a hypothetical tariff, including a cache-write premium."""
    input_price = 3.0 / 1_000_000
    read_price = 0.3 / 1_000_000
    write_price = 1.25 * input_price
    without_cache = 100_000 * input_price
    with_cache = 10_000 * write_price + 90_000 * read_price
    return {"without_cache": without_cache, "with_cache": with_cache, "savings": without_cache - with_cache}


async def demo_cache_statistics() -> None:
    stats = CacheStatistics()
    stats.record_usage(cache_creation_tokens=10_000)
    for _ in range(9):
        stats.record_usage(cache_read_tokens=10_000)
    print("Offline fixture: one cache write followed by nine cache reads.")
    print(f"Cache hit rate: {stats.cache_hit_rate():.1%}")
    print("Illustrative tariff only: input $3/M, cache write $3.75/M, cache read $0.30/M.")
    print(illustrative_costs())


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make six model requests using configured credentials.")
    args = parser.parse_args()
    await demo_cache_statistics()
    if args.live:
        await demo_live_caching(with_middleware=False)
        await demo_live_caching(with_middleware=True)


if __name__ == "__main__":
    asyncio.run(main())
