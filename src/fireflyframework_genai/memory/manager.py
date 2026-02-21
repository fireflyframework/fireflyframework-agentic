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

"""Memory manager: single entry point for all memory operations.

:class:`MemoryManager` composes :class:`ConversationMemory` and
:class:`WorkingMemory` behind a unified API.  It is the object that
gets wired into :class:`FireflyAgent`, :class:`DelegationRouter`,
pipeline steps, and reasoning patterns.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai.messages import ModelMessage

from fireflyframework_genai.memory.conversation import ConversationMemory
from fireflyframework_genai.memory.store import InMemoryStore, MemoryStore
from fireflyframework_genai.memory.working import WorkingMemory

logger = logging.getLogger(__name__)


class MemoryManager:
    """Unified memory facade for agents, pipelines, and reasoning patterns.

    A ``MemoryManager`` owns one :class:`ConversationMemory` (for chat
    history) and one :class:`WorkingMemory` (for session facts).  It
    provides convenience methods that combine both.

    Parameters:
        store: Backend used by :class:`WorkingMemory`.  Defaults to
            :class:`InMemoryStore`.
        max_conversation_tokens: Token budget for conversation history.
        summarize_threshold: Turns before summarization kicks in.
        working_scope_id: Scope identifier for working memory.
    """

    def __init__(
        self,
        *,
        store: MemoryStore | None = None,
        max_conversation_tokens: int = 128_000,
        summarize_threshold: int = 10,
        working_scope_id: str = "default",
    ) -> None:
        self._store = store or InMemoryStore()
        self._conversation = ConversationMemory(
            max_tokens=max_conversation_tokens,
            summarize_threshold=summarize_threshold,
        )
        self._working = WorkingMemory(
            store=self._store,
            scope_id=working_scope_id,
        )

    @classmethod
    def from_config(cls) -> MemoryManager:
        """Create a :class:`MemoryManager` from framework configuration.

        Reads ``memory_backend``, ``memory_max_conversation_tokens``,
        ``memory_summarize_threshold``, and backend-specific configuration
        from :func:`~fireflyframework_genai.config.get_config`.

        Supported backends:
            - ``in_memory``: Fast dict-backed storage (default, non-persistent)
            - ``file``: JSON file-based persistence
            - ``postgres``: PostgreSQL with connection pooling
            - ``mongodb``: MongoDB with connection pooling

        Note:
            Database backends require their respective optional dependencies:
            ``pip install fireflyframework-genai[postgres]`` or
            ``pip install fireflyframework-genai[mongodb]``
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from fireflyframework_genai.config import get_config

        def _run_sync(coro: object) -> object:
            """Run *coro* synchronously, safe even when an event loop is already running."""
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                pool = ThreadPoolExecutor(max_workers=1)
                try:
                    return pool.submit(asyncio.run, coro).result()
                finally:
                    pool.shutdown(wait=False)
            return asyncio.run(coro)

        cfg = get_config()

        store: MemoryStore
        if cfg.memory_backend == "file":
            from fireflyframework_genai.memory.store import FileStore

            store = FileStore(base_dir=cfg.memory_file_dir)

        elif cfg.memory_backend == "postgres":
            from fireflyframework_genai.memory.database_store import PostgreSQLStore

            if cfg.memory_postgres_url is None:
                raise ValueError(
                    "memory_postgres_url must be set when using postgres backend. "
                    "Set FIREFLY_GENAI_MEMORY_POSTGRES_URL environment variable."
                )

            store = PostgreSQLStore(
                url=cfg.memory_postgres_url,
                pool_size=cfg.memory_postgres_pool_size,
                pool_min_size=cfg.memory_postgres_pool_min_size,
                schema_name=cfg.memory_postgres_schema,
            )
            # Initialize the database connection pool
            _run_sync(store.initialize())
            logger.info("PostgreSQL memory backend initialized")

        elif cfg.memory_backend == "mongodb":
            from fireflyframework_genai.memory.database_store import MongoDBStore

            if cfg.memory_mongodb_url is None:
                raise ValueError(
                    "memory_mongodb_url must be set when using mongodb backend. "
                    "Set FIREFLY_GENAI_MEMORY_MONGODB_URL environment variable."
                )

            store = MongoDBStore(
                url=cfg.memory_mongodb_url,
                database=cfg.memory_mongodb_database,
                collection=cfg.memory_mongodb_collection,
                pool_size=cfg.memory_mongodb_pool_size,
            )
            # Initialize the database connection pool
            _run_sync(store.initialize())
            logger.info("MongoDB memory backend initialized")

        else:
            store = InMemoryStore()

        return cls(
            store=store,
            max_conversation_tokens=cfg.memory_max_conversation_tokens,
            summarize_threshold=cfg.memory_summarize_threshold,
        )

    # -- Accessors ---------------------------------------------------------

    @property
    def conversation(self) -> ConversationMemory:
        """The conversation memory subsystem."""
        return self._conversation

    @property
    def working(self) -> WorkingMemory:
        """The working memory subsystem."""
        return self._working

    @property
    def store(self) -> MemoryStore:
        """The underlying persistence backend."""
        return self._store

    # -- Conversation shortcuts --------------------------------------------

    def get_message_history(self, conversation_id: str) -> list[ModelMessage]:
        """Shortcut to :meth:`ConversationMemory.get_message_history`."""
        return self._conversation.get_message_history(conversation_id)

    def add_turn(
        self,
        conversation_id: str,
        user_prompt: str,
        assistant_response: str,
        raw_messages: list[ModelMessage],
        **kwargs: Any,
    ) -> Any:
        """Shortcut to :meth:`ConversationMemory.add_turn`."""
        return self._conversation.add_turn(conversation_id, user_prompt, assistant_response, raw_messages, **kwargs)

    def new_conversation(self) -> str:
        """Create a new conversation and return its ID."""
        return self._conversation.new_conversation()

    # -- Working memory shortcuts ------------------------------------------

    def set_fact(self, key: str, value: Any, **kwargs: Any) -> None:
        """Store a fact in working memory."""
        self._working.set(key, value, **kwargs)

    def get_fact(self, key: str, default: Any = None) -> Any:
        """Retrieve a fact from working memory."""
        return self._working.get(key, default)

    def get_working_context(self) -> str:
        """Render working memory as a text block for prompt injection."""
        return self._working.to_context_string()

    # -- Lifecycle ---------------------------------------------------------

    def clear_conversation(self, conversation_id: str) -> None:
        """Clear a single conversation."""
        self._conversation.clear(conversation_id)

    def clear_working(self) -> None:
        """Clear working memory."""
        self._working.clear()

    def clear_all(self) -> None:
        """Clear all memory (conversation + working)."""
        self._conversation.clear_all()
        self._working.clear()

    def fork(self, *, working_scope_id: str) -> MemoryManager:
        """Create a child :class:`MemoryManager` that shares the same
        conversation memory and store but has an independent working
        memory scope.

        This is used when delegating to a sub-agent or forking a
        pipeline branch: the child can read/write its own facts without
        polluting the parent's working memory, while still sharing
        conversation context.
        """
        # Bypass __init__ to avoid creating a new store/conversation.
        # The child shares the parent's store and conversation objects
        # (reference sharing, not copy) but gets a fresh WorkingMemory
        # under its own scope to isolate working facts.
        child = MemoryManager.__new__(MemoryManager)
        child._store = self._store
        child._conversation = self._conversation  # shared reference
        child._working = WorkingMemory(store=self._store, scope_id=working_scope_id)
        return child

    def __repr__(self) -> str:
        return (
            f"MemoryManager(conversations={len(self._conversation.conversation_ids)}, "
            f"working_keys={len(self._working.keys())})"
        )
