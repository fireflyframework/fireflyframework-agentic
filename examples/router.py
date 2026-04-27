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

"""Router (supervisor) template agent example.

Demonstrates:
- ``create_router_agent`` with an agent map.
- ``RoutingDecision`` structured output (target_agent, confidence, reasoning).

Usage::

    uv run python examples/router.py
"""

from __future__ import annotations

import asyncio

from _common import MODEL, ensure_api_key

from fireflyframework_agentic.agents.templates import create_router_agent

REQUESTS = [
    "I was charged twice for my last order.",
    "The dashboard keeps crashing when I click 'Export'.",
    "Do you offer volume discounts for teams over 50 people?",
]


async def main() -> None:
    ensure_api_key()

    agent = create_router_agent(
        agent_map={
            "billing": "Handles invoices, charges, payments, and refunds",
            "technical_support": "Handles bugs, errors, and how-to questions",
            "sales": "Handles pricing, upgrades, and new purchases",
        },
        fallback_agent="technical_support",
        model=MODEL,
    )

    print("=== Request Router ===\n")
    for request in REQUESTS:
        result = await agent.run(request)
        decision = result.output
        print(f"Request   : {request}")
        print(f"Route to  : {decision.target_agent}")
        print(f"Confidence: {decision.confidence:.2f}")
        print(f"Reasoning : {decision.reasoning}\n")


if __name__ == "__main__":
    asyncio.run(main())
