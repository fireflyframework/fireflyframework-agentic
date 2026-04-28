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

"""Reasoning Pipeline example.

Demonstrates:
- ``ReasoningPipeline`` chaining multiple patterns sequentially.
- Output of one pattern flows as input to the next.
- Merged trace across all patterns.

Usage::

    uv run python examples/reasoning_pipeline.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.reasoning import (
    ChainOfThoughtPattern,
    ReasoningPipeline,
    ReflexionPattern,
)

load_dotenv()

MODEL = os.environ["MODEL"]


async def main() -> None:

    agent = FireflyAgent(name="pipeline-agent", model=MODEL)

    pipeline = ReasoningPipeline(
        [
            ChainOfThoughtPattern(max_steps=5, model=MODEL),
            ReflexionPattern(max_steps=2, model=MODEL),
        ]
    )

    task = "Explain the difference between concurrency and parallelism. Give a real-world analogy."
    print(f"Task: {task}\n")

    result = await pipeline.execute(agent, task)

    print(f"--- Merged Trace ({len(result.trace.steps)} steps) ---")
    for i, step in enumerate(result.trace.steps, 1):
        kind = step.kind
        if hasattr(step, "content"):
            print(f"  Step {i} [{kind}]: {step.content[:120]}")
        elif kind == "reflection":
            print(f"  Step {i} [reflection]: retry={step.should_retry} | {step.critique[:100]}")
    print()
    print(f"Final output:\n{result.output}")
    print(f"\nTotal steps: {result.steps_taken}")


if __name__ == "__main__":
    asyncio.run(main())
