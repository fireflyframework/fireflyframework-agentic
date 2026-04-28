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

"""Basic FireflyAgent example.

Demonstrates:
- Creating a ``FireflyAgent`` with a model, instructions, and tags.
- Running a prompt asynchronously.
- Inspecting agent metadata (name, version, tags).

Usage::

    uv run python examples/basic_agent.py
"""

from __future__ import annotations

import asyncio

from _common import MODEL, ensure_api_key

from fireflyframework_agentic.agents import FireflyAgent


async def main() -> None:
    ensure_api_key()

    agent = FireflyAgent(
        name="poet",
        model=MODEL,
        instructions="You are a creative poet. Write short, evocative poems.",
        tags=["creative", "poetry"],
        version="1.0.0",
    )

    print(f"Agent : {agent.name} v{agent.version}")
    print(f"Tags  : {agent.tags}")
    print()

    result = await agent.run("Write a four-line poem about the ocean at dawn.")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
