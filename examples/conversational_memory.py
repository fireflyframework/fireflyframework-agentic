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

"""Multi-turn conversational agent with memory.

Demonstrates:
- ``create_conversational_agent`` template factory.
- ``MemoryManager`` for conversation history.
- Multi-turn ``run()`` calls with ``conversation_id``.
- The agent recalling information from earlier turns.

Usage::

    uv run python examples/conversational_memory.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

from fireflyframework_agentic.agents.templates import create_conversational_agent
from fireflyframework_agentic.memory import MemoryManager

load_dotenv(Path(__file__).parent / ".env")

MODEL = "openai:gpt-5.2-2025-12-11"


async def main() -> None:

    memory = MemoryManager()
    agent = create_conversational_agent(
        model=MODEL,
        personality="friendly and knowledgeable",
        domain="science",
        memory=memory,
    )
    cid = memory.new_conversation()

    turns = [
        "My name is Alice and I'm studying astrophysics.",
        "What are the main types of stellar remnants?",
        "Which one is the most massive? And by the way, do you remember my name?",
    ]

    for prompt in turns:
        print(f"User : {prompt}")
        result = await agent.run(prompt, conversation_id=cid)
        print(f"Agent: {result.output}\n")


if __name__ == "__main__":
    asyncio.run(main())
