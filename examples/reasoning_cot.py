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

"""Chain of Thought reasoning example.

Demonstrates:
- ``ChainOfThoughtPattern`` for step-by-step reasoning.
- Structured ``ReasoningThought`` output with ``is_final`` flag.
- Trace inspection to view each reasoning step.

Usage::

    uv run python examples/reasoning_cot.py
"""

from __future__ import annotations

import asyncio

from _common import MODEL, ensure_api_key

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.reasoning import ChainOfThoughtPattern


async def main() -> None:
    ensure_api_key()

    agent = FireflyAgent(name="cot-thinker", model=MODEL)
    pattern = ChainOfThoughtPattern(max_steps=10, model=MODEL)

    problem = "A farmer has 17 sheep. All but 9 run away. How many sheep does the farmer have left?"
    print(f"Problem: {problem}\n")

    result = await pattern.execute(agent, problem)

    print("--- Reasoning Trace ---")
    for i, step in enumerate(result.trace.steps, 1):
        print(f"  Step {i} [{step.kind}]: {step.content[:120]}")
    print()
    print(f"Answer: {result.output}")
    print(f"Steps : {result.steps_taken}")


if __name__ == "__main__":
    asyncio.run(main())
