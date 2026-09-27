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

"""Tools, memory, structured output, and streaming through Firefly's public API.

Set your provider's API key in the environment, then run::

    uv run python examples/model_agnostic_agent.py

FIREFLY_AGENTIC_DEFAULT_MODEL selects the model and API. This example defaults
to openai-responses:gpt-6-luna and makes real, billable requests. Choose a model
that supports tools and structured output; endpoint selection stays explicit.
"""

from __future__ import annotations

import asyncio
import os

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
    config = FireflyAgenticConfig(
        default_model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", "openai-responses:gpt-6-luna"),
        default_temperature=None,
    )
    memory = MemoryManager()
    conversation_id = memory.new_conversation()
    agent = FireflyAgent(
        name="calculator",
        instructions="Use the multiply tool for multiplication. Keep answers brief.",
        tools=[multiply],
        memory=memory,
        model_options=ModelOptions(max_tokens=4096),
        config=config,
        auto_register=False,
    )

    first = await agent.run("Multiply 17 by 23 using your tool.", conversation_id=conversation_id)
    print(f"Tool result: {first.output}")
    second = await agent.run("What were the two input numbers?", conversation_id=conversation_id)
    print(f"Follow-up: {second.output}")

    structured = FireflyAgent(
        name="structured-calculation",
        output_type=Calculation,
        model_options=ModelOptions(max_tokens=4096),
        config=config,
        auto_register=False,
    )
    result = await structured.run("Return the expression '17 * 23' and its integer value.")
    print(f"Structured output: {result.output.model_dump_json()}")

    print("Stream: ", end="", flush=True)
    async with await agent.run_stream(
        "Explain in one sentence why multiplication is useful.",
        model_options=ModelOptions(max_tokens=2048),
    ) as stream:
        async for text in stream.stream_text(delta=True):
            print(text, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())
