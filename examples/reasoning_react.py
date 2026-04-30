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

"""ReAct reasoning example.

Demonstrates:
- ``ReActPattern`` with its Reason-Act-Observe loop.
- ``FireflyAgent.run_with_reasoning()`` convenience method.
- Thought / Action / Observation steps in the trace.

Usage::

    uv run python examples/reasoning_react.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.reasoning import ReActPattern

load_dotenv()

MODEL = os.environ["MODEL"]


async def main() -> None:

    agent = FireflyAgent(name="react-agent", model=MODEL)
    pattern = ReActPattern(max_steps=5, model=MODEL)

    question = "What is the capital of Australia and what is its approximate population?"
    print(f"Question: {question}\n")

    result = await agent.run_with_reasoning(pattern, question)

    print("--- Reasoning Trace ---")
    for i, step in enumerate(result.trace.steps, 1):
        kind = step.kind
        if hasattr(step, "content"):
            detail = step.content[:120]
        elif hasattr(step, "tool_name"):
            detail = f"{step.tool_name}({step.tool_args})"
        else:
            detail = str(step)[:120]
        print(f"  Step {i} [{kind}]: {detail}")
    print()
    print(f"Answer: {result.output}")
    print(f"Steps : {result.steps_taken}")


if __name__ == "__main__":
    asyncio.run(main())
