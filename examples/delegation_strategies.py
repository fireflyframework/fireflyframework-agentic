# Copyright 2026 Firefly Software Solutions Inc
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

Demonstrates:
- ``DelegationRouter`` with four built-in strategies.
- ``RoundRobinStrategy`` — cycles through agents evenly.
- ``CapabilityStrategy`` — selects by tag matching.
- ``CostAwareStrategy`` — picks the cheapest model.
- ``ContentBasedStrategy`` — uses an LLM to route by prompt content.

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
    ContentBasedStrategy,
    CostAwareStrategy,
    DelegationRouter,
    RoundRobinStrategy,
)

load_dotenv()

MODEL = os.environ["MODEL"]


async def main() -> None:

    # Create specialised agents with different models and tags
    translator = FireflyAgent(
        name="translator",
        model="openai:gpt-4o-mini",
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
        model="openai:gpt-4o-mini",
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
        agent = await rr._strategy.select(rr._agents, prompt)  # Inspect selection
        result = await agent.run(prompt)
        print(f"  Request {i + 1} → routed to: {agent.name}")

    # ── 2. Capability-Based ─────────────────────────────────────────────
    print("\n=== Capability Strategy (tag='translation') ===\n")
    cap = DelegationRouter(agents, CapabilityStrategy(required_tag="translation"))
    prompt = "Translate 'Good morning' to French."
    agent = await cap._strategy.select(cap._agents, prompt)
    result = await agent.run(prompt)
    print(f"  Routed to: {agent.name}")
    print(f"  Output   : {result.output}\n")

    # ── 3. Cost-Aware ───────────────────────────────────────────────────
    print("=== Cost-Aware Strategy ===\n")
    cost = DelegationRouter(agents, CostAwareStrategy())
    prompt = "Simple classification: is this positive or negative?"
    agent = await cost._strategy.select(cost._agents, prompt)
    result = await agent.run(prompt)
    print(f"  Routed to: {agent.name} (cheapest model)")
    print(f"  Output   : {result.output}\n")

    # ── 4. Content-Based (LLM routing) ──────────────────────────────────
    print("=== Content-Based Strategy (LLM routing) ===\n")
    content = DelegationRouter(agents, ContentBasedStrategy(model="openai:gpt-4o-mini"))
    prompts = [
        "Translate this document to Spanish.",
        "Analyse the sales trends from Q4.",
        "Write a haiku about autumn leaves.",
    ]
    for prompt in prompts:
        agent = await content._strategy.select(content._agents, prompt)
        result = await agent.run(prompt)
        print(f"  Prompt   : {prompt}")
        print(f"  Routed to: {agent.name}")
        print(f"  Output   : {result.output[:100]}...\n")


if __name__ == "__main__":
    asyncio.run(main())
