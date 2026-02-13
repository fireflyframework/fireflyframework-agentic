#!/usr/bin/env python3
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

"""MongoDB persistence backend example.

This example demonstrates how to use MongoDB for persistent conversation
and working memory storage. MongoDB offers:

- Flexible schema for evolving data models
- Horizontal scalability with sharding
- High-performance document storage
- Rich query capabilities

Prerequisites:
    1. Install MongoDB dependencies:
       pip install fireflyframework-genai[mongodb]

    2. Start MongoDB (using Docker):
       docker run -d \\
         --name firefly-mongodb \\
         -p 27017:27017 \\
         -e MONGO_INITDB_DATABASE=firefly_memory \\
         mongo:8

    3. Set environment variables:
       export FIREFLY_GENAI_MEMORY_BACKEND=mongodb
       export FIREFLY_GENAI_MEMORY_MONGODB_URL=mongodb://localhost:27017/
       export OPENAI_API_KEY=sk-...

Usage:
    python examples/mongodb_persistence.py
"""

import asyncio

from fireflyframework_genai.agents.base import FireflyAgent
from fireflyframework_genai.config import get_config
from fireflyframework_genai.memory.database_store import MongoDBStore
from fireflyframework_genai.memory.manager import MemoryManager


async def main() -> None:
    """Demonstrate MongoDB-backed memory persistence."""

    print("=" * 70)
    print("MongoDB Memory Persistence Example")
    print("=" * 70)

    cfg = get_config()
    print(f"\n✓ Memory backend: {cfg.memory_backend}")
    print(f"✓ MongoDB URL: {cfg.memory_mongodb_url}")
    print(f"✓ Database: {cfg.memory_mongodb_database}")
    print(f"✓ Collection: {cfg.memory_mongodb_collection}")

    # Option 1: Use MemoryManager.from_config() (recommended)
    print("\n--- Creating MemoryManager from config ---")
    memory = MemoryManager.from_config()

    # Option 2: Create MongoDBStore directly for more control
    # store = MongoDBStore(
    #     url=cfg.memory_mongodb_url,
    #     database="my_app_memory",  # Custom database
    #     collection="custom_entries",  # Custom collection
    #     pool_size=20,  # Custom pool size
    # )
    # await store.initialize()
    # memory = MemoryManager(store=store)

    # Create an agent with persistent memory
    agent = FireflyAgent(
        name="mongodb_assistant",
        model="openai:gpt-4o-mini",
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

    new_memory = MemoryManager.from_config()
    new_agent = FireflyAgent(
        name="mongodb_assistant",
        model="openai:gpt-4o-mini",
        description="Restarted agent with same memory",
        memory=new_memory,
    )

    # All data is still available!
    print("\n--- Accessing memory after 'restart' ---")
    restored_history = new_memory.get_message_history(conversation_id)
    restored_tech = new_memory.get_fact("tech_stack")
    restored_size = new_memory.get_fact("team_size")

    print(f"✓ Conversation messages restored: {len(restored_history)}")
    print(f"✓ Tech stack restored: {restored_tech}")
    print(f"✓ Team size restored: {restored_size}")

    # Continue the conversation
    print("\n--- Continuing conversation after restart ---")
    result = await new_agent.run(
        "Remind me what I told you about my project.",
        conversation_id=conversation_id,
    )
    print(f"Agent: {result.output}")

    # Cleanup: remove expired entries
    print("\n--- Maintenance: Cleanup expired entries ---")
    if isinstance(memory.store, MongoDBStore):
        count = await memory.store.cleanup_expired()
        print(f"✓ Cleaned up {count} expired entries")

    # Optional: Close the connection on shutdown
    print("\n--- Closing MongoDB connection ---")
    if isinstance(memory.store, MongoDBStore):
        await memory.store.close()
        print("✓ MongoDB connection closed")

    print("\n" + "=" * 70)
    print("Key Benefits of MongoDB Backend:")
    print("=" * 70)
    print("✓ Flexible document schema adapts to changing requirements")
    print("✓ Excellent performance for read-heavy workloads")
    print("✓ Native JSON/BSON storage for complex data structures")
    print("✓ Horizontal scaling with sharding for large deployments")
    print("✓ Rich query language with aggregation pipelines")
    print("✓ Automatic indexing for efficient namespace isolation")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
