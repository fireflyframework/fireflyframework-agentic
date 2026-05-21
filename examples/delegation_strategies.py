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

MODEL = os.environ["MODEL"]


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
    # Cycles through agents in order, ignoring the prompt. Useful for
    # evenly distributing load when all agents are interchangeable.
    # `decide()` returns the selection without running the agent — handy
    # for inspecting routing behaviour cheaply.
    print("=== Round Robin Strategy ===\n")
    rr = DelegationRouter(agents, RoundRobinStrategy())
    for i in range(6):
        prompt = f"Request #{i + 1}: Hello!"
        decision = await rr.decide(prompt)
        print(f"  Request {i + 1} → routed to: {decision.chosen.name}")

    # ── 2. Capability-Based ─────────────────────────────────────────────
    # Picks the agent whose `tags` include the required tag. Here only
    # `translator` has "translation", so it always wins. `route()` is the
    # one-liner: decide + run + return the agent's output in one call.
    print("\n=== Capability Strategy (tag='translation') ===\n")
    cap = DelegationRouter(agents, CapabilityStrategy(required_tag="translation"))
    result = await cap.route("Translate 'Good morning' to French.")
    print(f"  Output: {result.output}\n")

    # ── 3. Cost-Aware (show the full ranking, not just the winner) ──────
    # Ranks agents by the price of their underlying model and picks the
    # cheapest. Here all three agents use the same MODEL, so prices tie —
    # the printed ranking exposes the score/reason the strategy assigned
    # to each candidate (useful for debugging routing decisions).
    print("=== Cost-Aware Strategy ===\n")
    cost = DelegationRouter(agents, CostAwareStrategy())
    decision = await cost.decide("Simple classification: is this positive or negative?")
    for c in decision.candidates:
        print(f"  {c.agent.name:11} ({c.agent.model_identifier:25}) score={c.score:.2f}  {c.reason}")
    print()

    # ── 4. Content-Based (LLM routing) ──────────────────────────────────
    # Uses a small LLM to read the prompt and pick the best-matching
    # agent based on each agent's `description`. This is the only built-in
    # strategy that costs an extra model call — use it when rules over
    # tags/cost aren't expressive enough.
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
    # Strategies run in order, each narrowing the candidate pool:
    #   1. CapabilityStrategy(required_tag="translation") keeps only agents
    #      tagged "translation" (here: just the `translator` agent).
    #   2. CostAwareStrategy ranks the survivors by model price and picks
    #      the cheapest.
    # Use chains when one rule isn't enough — e.g. "must be able to do X,
    # and among those that can, pick the cheapest / fastest / least loaded".
    print("=== Chain Strategy (capability → cost-aware) ===\n")
    chain = ChainStrategy(CapabilityStrategy(required_tag="translation"), CostAwareStrategy())
    router = DelegationRouter(agents, chain)
    decision = await router.decide("Translate 'Thank you' to Japanese.")
    print(f"  Survivors after capability filter: {[c.agent.name for c in decision.candidates]}")
    print(f"  Chosen (cheapest survivor)       : {decision.chosen.name}")


if __name__ == "__main__":
    asyncio.run(main())
