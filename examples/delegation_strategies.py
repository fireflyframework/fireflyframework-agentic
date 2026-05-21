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

"""Multi-agent delegation strategies example.

Demonstrates ``DelegationRouter`` with the four built-in strategies
(``RoundRobinStrategy``, ``CapabilityStrategy``, ``CostAwareStrategy``,
``ContentBasedStrategy``) plus one combinator (``ChainStrategy``). Shows
both the ``route()`` one-liner and the ``decide()`` form used to inspect
the full ranked candidate list.

See ``docs/agents.md`` for the full API (decide/execute split, all three
combinators, OTel decision event).

Usage::

    uv run python examples/delegation_strategies.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.agents.delegation import (
    CapabilityStrategy,
    ChainStrategy,
    ContentBasedStrategy,
    CostAwareStrategy,
    DelegationRouter,
    RoundRobinStrategy,
)

load_dotenv()

MODEL = os.environ.get("MODEL", "openai:gpt-4o-mini")


async def main() -> None:
    translator = FireflyAgent(
        name="translator",
        model=MODEL,
        instructions="You are a professional translator.",
        tags=["translation", "languages"],
        description="Translates text between languages",
    )
    analyst = FireflyAgent(
        name="analyst",
        model=MODEL,
        instructions="You are a data analyst. Provide concise insights.",
        tags=["analysis", "data"],
        description="Analyses data and provides insights",
    )
    writer = FireflyAgent(
        name="writer",
        model=MODEL,
        instructions="You are a creative writer.",
        tags=["creative", "writing"],
        description="Writes creative content",
    )

    agents = [translator, analyst, writer]

    # ── 1. Round Robin ──────────────────────────────────────────────────
    print("=== Round Robin Strategy ===\n")
    rr = DelegationRouter(agents, RoundRobinStrategy())
    for i in range(6):
        prompt = f"Request #{i + 1}: Hello!"
        decision = await rr.decide(prompt)
        print(f"  Request {i + 1} → routed to: {decision.chosen.name}")

    # ── 2. Capability-Based ─────────────────────────────────────────────
    print("\n=== Capability Strategy (tag='translation') ===\n")
    cap = DelegationRouter(agents, CapabilityStrategy(required_tag="translation"))
    result = await cap.route("Translate 'Good morning' to French.")
    print(f"  Output: {result.output}\n")

    # ── 3. Cost-Aware (show the full ranking, not just the winner) ──────
    print("=== Cost-Aware Strategy ===\n")
    cost = DelegationRouter(agents, CostAwareStrategy())
    decision = await cost.decide("Simple classification: is this positive or negative?")
    for c in decision.candidates:
        print(f"  {c.agent.name:11} ({c.agent.model_identifier:25}) score={c.score:.2f}  {c.reason}")
    print()

    # ── 4. Content-Based (LLM routing) ──────────────────────────────────
    print("=== Content-Based Strategy (LLM routing) ===\n")
    content = DelegationRouter(agents, ContentBasedStrategy(model="openai:gpt-4o-mini"))
    for prompt in [
        "Translate this document to Spanish.",
        "Analyse the sales trends from Q4.",
        "Write a haiku about autumn leaves.",
    ]:
        result = await content.route(prompt)
        print(f"  Prompt   : {prompt}")
        print(f"  Output   : {result.output[:100]}...\n")

    # ── 5. ChainStrategy: capability-filter, then cheapest ──────────────
    print("=== Chain Strategy (capability → cost-aware) ===\n")
    chain = ChainStrategy(CapabilityStrategy(required_tag="translation"), CostAwareStrategy())
    chained = DelegationRouter(agents, chain)
    decision = await chained.decide("Translate 'Thank you' to Japanese.")
    print(f"  Survivors after chain: {[c.agent.name for c in decision.candidates]}")
    print(f"  Chosen: {decision.chosen.name}")


if __name__ == "__main__":
    asyncio.run(main())
