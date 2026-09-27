# Copyright 2026 Firefly Software Foundation
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

"""OpenAI Responses with tools, conversation history, structured output, and streaming.

Set OPENAI_API_KEY in your environment or .env, then run::

    uv run python examples/openai_responses.py

This makes real, billable API requests. OPENAI_MODEL defaults to gpt-6-luna;
use an unprefixed model ID available to your account. No response storage is
requested: full message history is supplied for the follow-up turn.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from pydantic import BaseModel

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.config import FireflyAgenticConfig
from fireflyframework_agentic.memory import MemoryManager
from fireflyframework_agentic.models import ModelOptions
from fireflyframework_agentic.tools import firefly_tool


class Calculation(BaseModel):
    expression: str
    value: int


@firefly_tool("multiply", auto_register=False)
async def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


async def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY in your environment or .env before running this example.")

    model = f"openai-responses:{os.getenv('OPENAI_MODEL', 'gpt-6-luna')}"
    options = ModelOptions(reasoning="low", store_responses=False)
    config = FireflyAgenticConfig(default_temperature=None)
    memory = MemoryManager()
    conversation_id = memory.new_conversation()
    agent = FireflyAgent(
        name="responses-calculator",
        model=model,
        instructions="Use the multiply tool for multiplication. Keep answers brief.",
        tools=[multiply],
        model_options=options,
        memory=memory,
        config=config,
        auto_register=False,
    )

    first = await agent.run("Multiply 17 by 23 using your tool.", conversation_id=conversation_id)
    print(f"Tool result: {first.output}")
    second = await agent.run("What were the two input numbers?", conversation_id=conversation_id)
    print(f"Follow-up: {second.output}")

    structured = FireflyAgent(
        name="responses-structured",
        model=model,
        output_type=Calculation,
        model_options=options,
        config=config,
        auto_register=False,
    )
    result = await structured.run("Return the expression '17 * 23' and its integer value.")
    print(f"Structured output: {result.output.model_dump_json()}")

    print("Stream: ", end="", flush=True)
    async with await agent.run_stream("Explain in one sentence why multiplication is useful.") as stream:
        async for text in stream.stream_text(delta=True):
            print(text, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())
