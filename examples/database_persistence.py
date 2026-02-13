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

"""PostgreSQL persistence backend example.

This example demonstrates how to use PostgreSQL for persistent conversation
and working memory storage. The database backend provides:

- Production-grade persistence across process restarts
- Connection pooling for high concurrency
- Automatic schema migration
- Namespace isolation for multi-tenant scenarios

Prerequisites:
    1. Install PostgreSQL dependencies:
       pip install fireflyframework-genai[postgres]

    2. Start PostgreSQL (using Docker):
       docker run -d \\
         --name firefly-postgres \\
         -p 5432:5432 \\
         -e POSTGRES_PASSWORD=firefly123 \\
         -e POSTGRES_DB=firefly_memory \\
         postgres:17

    3. Set environment variables:
       export FIREFLY_GENAI_MEMORY_BACKEND=postgres
       export FIREFLY_GENAI_MEMORY_POSTGRES_URL=postgresql://postgres:firefly123@localhost/firefly_memory
       export OPENAI_API_KEY=sk-...

Usage:
    python examples/database_persistence.py
"""

import asyncio

from fireflyframework_genai.agents.base import FireflyAgent
from fireflyframework_genai.config import get_config
from fireflyframework_genai.memory.database_store import PostgreSQLStore
from fireflyframework_genai.memory.manager import MemoryManager


async def main() -> None:
    """Demonstrate PostgreSQL-backed memory persistence."""

    print("=" * 70)
    print("PostgreSQL Memory Persistence Example")
    print("=" * 70)

    cfg = get_config()
    print(f"\n✓ Memory backend: {cfg.memory_backend}")
    print(f"✓ PostgreSQL URL: {cfg.memory_postgres_url}")
    print(f"✓ Pool size: {cfg.memory_postgres_pool_size}")

    # Option 1: Use MemoryManager.from_config() (recommended)
    # This reads all settings from environment variables
    print("\n--- Creating MemoryManager from config ---")
    memory = MemoryManager.from_config()

    # Option 2: Create PostgreSQLStore directly for more control
    # store = PostgreSQLStore(
    #     url=cfg.memory_postgres_url,
    #     pool_size=20,  # Custom pool size
    #     schema_name="my_app_memory",  # Custom schema
    # )
    # await store.initialize()
    # memory = MemoryManager(store=store)

    # Create an agent with persistent memory
    agent = FireflyAgent(
        name="postgres_assistant",
        model="openai:gpt-4o-mini",
        description="An assistant with PostgreSQL-backed memory",
        memory=memory,
    )

    # Start a conversation
    conversation_id = memory.new_conversation()
    print(f"\n✓ Started conversation: {conversation_id}")

    # First interaction
    print("\n--- First interaction ---")
    result = await agent.run(
        "Remember that my favorite color is blue and I live in San Francisco.",
        conversation_id=conversation_id,
    )
    print(f"Agent: {result.output}")

    # Store a fact in working memory (persisted to PostgreSQL)
    memory.set_fact("user_name", "Alice")
    memory.set_fact("project", "Firefly GenAI Framework")
    print("\n✓ Stored facts in working memory (PostgreSQL)")

    # Second interaction - memory is recalled from PostgreSQL
    print("\n--- Second interaction ---")
    result = await agent.run(
        "What's my favorite color and where do I live?",
        conversation_id=conversation_id,
    )
    print(f"Agent: {result.output}")

    # Retrieve facts from working memory
    print("\n--- Working memory (from PostgreSQL) ---")
    user_name = memory.get_fact("user_name")
    project = memory.get_fact("project")
    print(f"User name: {user_name}")
    print(f"Project: {project}")

    # Show conversation history (stored in PostgreSQL)
    print("\n--- Conversation history (from PostgreSQL) ---")
    history = memory.get_message_history(conversation_id)
    print(f"Total messages: {len(history)}")

    # Demonstrate persistence: simulate process restart
    print("\n--- Simulating process restart ---")
    print("Creating a NEW MemoryManager instance...")

    new_memory = MemoryManager.from_config()
    new_agent = FireflyAgent(
        name="postgres_assistant",
        model="openai:gpt-4o-mini",
        description="Restarted agent with same memory",
        memory=new_memory,
    )

    # The conversation history and facts are still available!
    print("\n--- Accessing memory after 'restart' ---")
    restored_history = new_memory.get_message_history(conversation_id)
    restored_name = new_memory.get_fact("user_name")
    restored_project = new_memory.get_fact("project")

    print(f"✓ Conversation messages restored: {len(restored_history)}")
    print(f"✓ User name restored: {restored_name}")
    print(f"✓ Project restored: {restored_project}")

    # Continue the conversation from where we left off
    print("\n--- Continuing conversation after restart ---")
    result = await new_agent.run(
        "What do you remember about me?",
        conversation_id=conversation_id,
    )
    print(f"Agent: {result.output}")

    # Cleanup: remove expired entries
    print("\n--- Maintenance: Cleanup expired entries ---")
    if isinstance(memory.store, PostgreSQLStore):
        count = await memory.store.cleanup_expired()
        print(f"✓ Cleaned up {count} expired entries")

    # Optional: Close the connection pool on shutdown
    print("\n--- Closing connection pool ---")
    if isinstance(memory.store, PostgreSQLStore):
        await memory.store.close()
        print("✓ PostgreSQL connection pool closed")

    print("\n" + "=" * 70)
    print("Key Benefits of PostgreSQL Backend:")
    print("=" * 70)
    print("✓ Persistent storage survives process restarts")
    print("✓ Connection pooling for high-performance concurrent access")
    print("✓ Automatic schema migration on first run")
    print("✓ Namespace isolation for multi-tenant applications")
    print("✓ ACID guarantees for data consistency")
    print("✓ Efficient indexes for fast queries")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
