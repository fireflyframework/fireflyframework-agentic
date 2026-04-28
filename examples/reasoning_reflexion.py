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

"""Reflexion reasoning example.

Demonstrates:
- ``ReflexionPattern`` with its Execute-Reflect-Retry loop.
- ``ReflectionVerdict`` structured self-critique.
- How the agent improves its answer based on feedback.

Usage::

    uv run python examples/reasoning_reflexion.py
"""

from __future__ import annotations

import asyncio

from _common import MODEL, ensure_api_key

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.reasoning import ReflexionPattern


async def main() -> None:
    ensure_api_key()

    agent = FireflyAgent(name="reflexion-agent", model=MODEL)
    pattern = ReflexionPattern(max_steps=3, model=MODEL)

    task = "Write a concise Python function that checks whether a string is a valid IPv4 address."
    print(f"Task: {task}\n")

    result = await pattern.execute(agent, task)

    print("--- Reasoning Trace ---")
    for i, step in enumerate(result.trace.steps, 1):
        kind = step.kind
        if kind == "reflection":
            print(f"  Step {i} [reflection]: retry={step.should_retry} | {step.critique[:100]}")
        elif hasattr(step, "content"):
            print(f"  Step {i} [{kind}]: {step.content[:120]}")
    print()
    print(f"Final answer:\n{result.output}")
    print(f"\nSteps: {result.steps_taken}")


if __name__ == "__main__":
    asyncio.run(main())
