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

"""Goal Decomposition reasoning example.

Demonstrates:
- ``GoalDecompositionPattern`` for hierarchical goal breakdown.
- ``GoalPhase`` structured decomposition.
- Task execution across phases.

Usage::

    uv run python examples/reasoning_goal.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.reasoning import GoalDecompositionPattern

load_dotenv()

MODEL = os.environ["MODEL"]


async def main() -> None:

    agent = FireflyAgent(name="goal-agent", model=MODEL)
    pattern = GoalDecompositionPattern(max_steps=15, model=MODEL)

    goal = "Design and document a REST API for a library book management system."
    print(f"Goal: {goal}\n")

    result = await pattern.execute(agent, goal)

    print("--- Reasoning Trace ---")
    for i, step in enumerate(result.trace.steps, 1):
        kind = step.kind
        if kind == "plan":
            print(f"  Step {i} [plan]: {step.description}")
            for sub in step.sub_steps:
                print(f"    - {sub[:80]}")
        elif hasattr(step, "content"):
            print(f"  Step {i} [{kind}]: {step.content[:120]}")
        elif hasattr(step, "tool_name"):
            print(f"  Step {i} [{kind}]: {step.tool_name}({step.tool_args})")
    print()
    print(f"Steps: {result.steps_taken}")
    if isinstance(result.output, list):
        print(f"\n--- Task Results ({len(result.output)}) ---")
        for j, out in enumerate(result.output, 1):
            print(f"\n  [{j}] {str(out)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
