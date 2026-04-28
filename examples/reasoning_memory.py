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

"""Reasoning with Memory integration example.

Demonstrates:
- Running a reasoning pattern with a ``MemoryManager``.
- Working memory enrichment across reasoning steps.
- ``FireflyAgent.run_with_reasoning()`` with ``conversation_id``.
- Inspecting working memory facts after execution.

Usage::

    uv run python examples/reasoning_memory.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.memory import MemoryManager
from fireflyframework_agentic.reasoning import ReActPattern

load_dotenv(Path(__file__).parent / ".env")

MODEL = "openai:gpt-5.2-2025-12-11"


async def main() -> None:

    memory = MemoryManager()
    agent = FireflyAgent(name="memory-react", model=MODEL, memory=memory)
    cid = memory.new_conversation()
    pattern = ReActPattern(max_steps=5, model=MODEL)

    question = "What are the three laws of thermodynamics? Summarise each in one sentence."
    print(f"Question: {question}\n")

    result = await agent.run_with_reasoning(
        pattern,
        question,
        conversation_id=cid,
    )

    print("--- Reasoning Trace ---")
    for i, step in enumerate(result.trace.steps, 1):
        kind = step.kind
        if hasattr(step, "content"):
            print(f"  Step {i} [{kind}]: {step.content[:120]}")
        elif hasattr(step, "tool_name"):
            print(f"  Step {i} [{kind}]: {step.tool_name}")
    print()
    print(f"Answer:\n{result.output}\n")

    # Show that working memory captured the reasoning output
    stored = memory.get_fact("reasoning:output")
    if stored:
        print(f"Working memory 'reasoning:output': {str(stored)[:120]}...")

    # Show conversation history was persisted
    history = memory.get_message_history(cid)
    print(f"Conversation turns stored: {len(history)}")


if __name__ == "__main__":
    asyncio.run(main())
