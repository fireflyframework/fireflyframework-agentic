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

"""PostgreSQL conversation and working-memory persistence across manager instances.

Install the [postgres] extra and use a disposable local PostgreSQL database.
Set FIREFLY_AGENTIC_MEMORY_BACKEND=postgres, FIREFLY_AGENTIC_MEMORY_POSTGRES_URL,
and FIREFLY_AGENTIC_DEFAULT_MODEL plus its provider credentials. This example
creates storage schema/indexes and retains its own namespaced sample records.
It makes billable model calls. Connection URLs are never printed.
"""

import asyncio
from uuid import uuid4

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.config import get_config
from fireflyframework_agentic.memory.database_store import PostgreSQLStore
from fireflyframework_agentic.memory.manager import MemoryManager


async def main() -> None:
    """Demonstrate PostgreSQL-backed memory persistence."""

    print("=" * 70)
    print("PostgreSQL Memory Persistence Example")
    print("=" * 70)

    cfg = get_config()
    if cfg.memory_backend != "postgres" or not cfg.memory_postgres_url:
        raise SystemExit("Set FIREFLY_AGENTIC_MEMORY_BACKEND=postgres and FIREFLY_AGENTIC_MEMORY_POSTGRES_URL.")
    scope_id = f"persistence-example-{uuid4().hex}"
    print(f"\n✓ Memory backend: {cfg.memory_backend}")
    print(f"✓ Pool size: {cfg.memory_postgres_pool_size}")

    # Option 1: Use MemoryManager.from_config() (recommended)
    # This reads all settings from environment variables
    print("\n--- Creating MemoryManager from config ---")
    memory = MemoryManager.from_config().fork(working_scope_id=scope_id)

    stores = [memory.store]
    try:
        # Create an agent with persistent memory
        agent = FireflyAgent(
            name="postgres_assistant",
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
        memory.set_fact("project", "Firefly Agentic Framework")
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

        new_memory = MemoryManager.from_config().fork(working_scope_id=scope_id)
        stores.append(new_memory.store)
        new_agent = FireflyAgent(
            name="postgres_assistant",
            description="Restarted agent with same memory",
            memory=new_memory,
        )

        # The conversation history and facts are still available!
        print("\n--- Accessing memory after 'restart' ---")
        restored_history = new_memory.get_message_history(conversation_id)
        restored_name = new_memory.get_fact("user_name")
        restored_project = new_memory.get_fact("project")

        if restored_history != history:
            raise RuntimeError("Restored conversation differs from the saved conversation")
        print(f"✓ Conversation messages restored: {len(restored_history)}")
        if (restored_name, restored_project) != (user_name, project):
            raise RuntimeError("Working-memory facts were not restored")
        print(f"✓ User name restored: {restored_name}")
        print(f"✓ Project restored: {restored_project}")

        # Continue the conversation from where we left off
        print("\n--- Continuing conversation after restart ---")
        result = await new_agent.run(
            "What do you remember about me?",
            conversation_id=conversation_id,
        )
        print(f"Agent: {result.output}")

        print("Restored conversation and working-memory facts verified through a second manager.")
    finally:
        for store in stores:
            if isinstance(store, PostgreSQLStore):
                await store.close()


if __name__ == "__main__":
    asyncio.run(main())
