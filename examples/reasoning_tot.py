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

"""Tree of Thoughts reasoning example.

Demonstrates:
- ``TreeOfThoughtsPattern`` for parallel branch exploration.
- ``BranchList`` structured branch generation.
- ``BranchEvaluation`` scoring and best-branch selection.

Usage::

    uv run python examples/reasoning_tot.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.reasoning import TreeOfThoughtsPattern

load_dotenv()

MODEL = os.environ["MODEL"]


async def main() -> None:

    agent = FireflyAgent(name="tot-agent", model=MODEL)
    pattern = TreeOfThoughtsPattern(branching_factor=3, max_depth=1, model=MODEL)

    problem = "Design a caching strategy for a social media feed that handles 10 million daily active users."
    print(f"Problem: {problem}\n")

    result = await pattern.execute(agent, problem)

    print("--- Reasoning Trace ---")
    for i, step in enumerate(result.trace.steps, 1):
        kind = step.kind
        if hasattr(step, "content"):
            print(f"  Step {i} [{kind}]: {step.content[:150]}")
    print()
    print(f"Best approach:\n{result.output}")
    print(f"\nSteps: {result.steps_taken}")


if __name__ == "__main__":
    asyncio.run(main())
