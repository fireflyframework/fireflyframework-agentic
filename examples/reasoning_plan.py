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

"""Plan-and-Execute reasoning example.

Demonstrates:
- ``PlanAndExecutePattern`` for goal-driven planning.
- Structured ``ReasoningPlan`` with ``PlanStepDef`` status tracking.
- Step-by-step execution with plan/action/observation trace.
- Logging output for real-time progress visibility.
- Per-step timeout to prevent indefinite hangs.

Usage::

    uv run python examples/reasoning_plan.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from fireflyframework_agentic import configure_logging
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.reasoning import PlanAndExecutePattern

load_dotenv()

MODEL = os.environ["MODEL"]

# Enable INFO-level logging so that plan generation and step execution
# progress is printed in real time — only for fireflyframework_agentic loggers.
configure_logging("INFO")


async def main() -> None:

    agent = FireflyAgent(name="planner", model=MODEL)
    pattern = PlanAndExecutePattern(
        max_steps=8,
        model=MODEL,
        step_timeout=120.0,  # 120 s per LLM call
    )

    goal = "List the top 3 benefits and drawbacks of Python for web development."
    print(f"\nGoal: {goal}\n")

    result = await pattern.execute(agent, goal)

    # -- Trace summary -------------------------------------------------------
    print("\n--- Reasoning Trace ---")
    for i, step in enumerate(result.trace.steps, 1):
        kind = step.kind
        if kind == "plan":
            print(f"  Step {i} [plan]: {step.description}")
            for sub in step.sub_steps:
                print(f"    - {sub[:80]}")
        elif hasattr(step, "content"):
            print(f"  Step {i} [{kind}]: {step.content[:120]}")
        elif hasattr(step, "tool_name"):
            print(f"  Step {i} [{kind}]: {step.tool_name}")
    print()
    print(f"Steps: {result.steps_taken}  |  Success: {result.success}")

    if isinstance(result.output, list):
        print(f"\n--- Results ({len(result.output)} steps) ---")
        for j, out in enumerate(result.output, 1):
            print(f"\n  [{j}] {str(out)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
