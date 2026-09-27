#!/usr/bin/env python3
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

"""MongoDB conversation and working-memory persistence across manager instances.

Install the [mongodb] extra and use a disposable local MongoDB database.
Set FIREFLY_AGENTIC_MEMORY_BACKEND=mongodb, FIREFLY_AGENTIC_MEMORY_MONGODB_URL,
and FIREFLY_AGENTIC_DEFAULT_MODEL plus its provider credentials. This example
creates storage schema/indexes and retains its own namespaced sample records.
It makes billable model calls. Connection URLs are never printed.
"""

import asyncio
from uuid import uuid4

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.config import get_config
from fireflyframework_agentic.memory.database_store import MongoDBStore
from fireflyframework_agentic.memory.manager import MemoryManager


async def main() -> None:
    """Demonstrate MongoDB-backed memory persistence."""

    print("=" * 70)
    print("MongoDB Memory Persistence Example")
    print("=" * 70)

    cfg = get_config()
    if cfg.memory_backend != "mongodb" or not cfg.memory_mongodb_url:
        raise SystemExit("Set FIREFLY_AGENTIC_MEMORY_BACKEND=mongodb and FIREFLY_AGENTIC_MEMORY_MONGODB_URL.")
    scope_id = f"persistence-example-{uuid4().hex}"
    print(f"\n✓ Memory backend: {cfg.memory_backend}")
    print(f"✓ Database: {cfg.memory_mongodb_database}")
    print(f"✓ Collection: {cfg.memory_mongodb_collection}")

    # Option 1: Use MemoryManager.from_config() (recommended)
    print("\n--- Creating MemoryManager from config ---")
    memory = MemoryManager.from_config().fork(working_scope_id=scope_id)

    stores = [memory.store]
    try:
        # Create an agent with persistent memory
        agent = FireflyAgent(
            name="mongodb_assistant",
            description="An assistant with MongoDB-backed memory",
            memory=memory,
        )

        # Start a conversation
        conversation_id = memory.new_conversation()
        print(f"\n✓ Started conversation: {conversation_id}")

        # First interaction
        print("\n--- First interaction ---")
        result = await agent.run(
            "I'm working on a machine learning project using PyTorch. Please remember this.",
            conversation_id=conversation_id,
        )
        print(f"Agent: {result.output}")

        # Store structured data in working memory
        memory.set_fact(
            "tech_stack",
            {
                "framework": "PyTorch",
                "language": "Python",
                "database": "MongoDB",
            },
        )
        memory.set_fact("team_size", 5)
        memory.set_fact("project_status", "in_progress")
        print("\n✓ Stored structured facts in working memory (MongoDB)")

        # Second interaction
        print("\n--- Second interaction ---")
        result = await agent.run(
            "What framework am I using for my ML project?",
            conversation_id=conversation_id,
        )
        print(f"Agent: {result.output}")

        # Retrieve structured data from working memory
        print("\n--- Working memory (from MongoDB) ---")
        tech_stack = memory.get_fact("tech_stack")
        team_size = memory.get_fact("team_size")
        status = memory.get_fact("project_status")
        print(f"Tech stack: {tech_stack}")
        print(f"Team size: {team_size}")
        print(f"Status: {status}")

        # Show conversation history
        print("\n--- Conversation history (from MongoDB) ---")
        history = memory.get_message_history(conversation_id)
        print(f"Total messages: {len(history)}")

        # Demonstrate multi-namespace isolation
        print("\n--- Multi-namespace demonstration ---")

        # Create a second conversation in a different namespace
        conversation_2 = memory.new_conversation()
        result = await agent.run(
            "This is a completely different conversation about travel plans.",
            conversation_id=conversation_2,
        )
        print(f"Conversation 2 - Agent: {result.output}")

        history_1 = memory.get_message_history(conversation_id)
        history_2 = memory.get_message_history(conversation_2)
        print(f"✓ Conversation 1 messages: {len(history_1)}")
        print(f"✓ Conversation 2 messages: {len(history_2)}")
        print("✓ Conversations are isolated in separate namespaces")

        # Demonstrate persistence: simulate process restart
        print("\n--- Simulating process restart ---")
        print("Creating a NEW MemoryManager instance...")

        new_memory = MemoryManager.from_config().fork(working_scope_id=scope_id)
        stores.append(new_memory.store)
        new_agent = FireflyAgent(
            name="mongodb_assistant",
            description="Restarted agent with same memory",
            memory=new_memory,
        )

        # All data is still available!
        print("\n--- Accessing memory after 'restart' ---")
        restored_history = new_memory.get_message_history(conversation_id)
        restored_tech = new_memory.get_fact("tech_stack")
        restored_size = new_memory.get_fact("team_size")

        if restored_history != history:
            raise RuntimeError("Restored conversation differs from the saved conversation")
        print(f"✓ Conversation messages restored: {len(restored_history)}")
        if (restored_tech, restored_size) != (tech_stack, team_size):
            raise RuntimeError("Working-memory facts were not restored")
        print(f"✓ Tech stack restored: {restored_tech}")
        print(f"✓ Team size restored: {restored_size}")

        # Continue the conversation
        print("\n--- Continuing conversation after restart ---")
        result = await new_agent.run(
            "Remind me what I told you about my project.",
            conversation_id=conversation_id,
        )
        print(f"Agent: {result.output}")

        print("Restored conversation and working-memory facts verified through a second manager.")
    finally:
        for store in stores:
            if isinstance(store, MongoDBStore):
                await store.close()


if __name__ == "__main__":
    asyncio.run(main())
