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

"""Conversation memory: multi-turn chat history with token management.

:class:`ConversationMemory` wraps pydantic-ai's ``message_history``
mechanism and adds per-conversation scoping, automatic token-budget
enforcement, and optional summarization of older turns.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from pydantic_ai.messages import ModelMessage

from fireflyframework_genai.content.compression import TokenEstimator
from fireflyframework_genai.memory.types import ConversationTurn

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Token-aware, multi-conversation message history.

    Each conversation is identified by a ``conversation_id`` and stores
    an ordered list of :class:`ConversationTurn` objects.  Before each
    agent run, :meth:`get_message_history` returns the pydantic-ai
    ``ModelMessage`` list trimmed to fit the token budget.

    Parameters:
        max_tokens: Maximum total tokens for the conversation history
            passed to the model.  Older turns are evicted (FIFO) when
            this limit is exceeded.
        summarize_threshold: When evicting turns, if the number of
            evicted turns exceeds this count, the framework can call
            :meth:`summarize` to compress them into a summary turn.
            Set to ``0`` to disable summarization.
        estimator: :class:`TokenEstimator` for counting tokens.
    """

    def __init__(
        self,
        *,
        max_tokens: int = 4096,
        summarize_threshold: int = 3072,
        estimator: TokenEstimator | None = None,
        summarizer: Callable[[list[ConversationTurn]], str] | None = None,
    ) -> None:
        self._max_tokens = max_tokens
        self._summarize_threshold = summarize_threshold
        self._estimator = estimator or TokenEstimator()
        self._summarizer = summarizer
        self._summaries: dict[str, str] = {}
        self._conversations: dict[str, list[ConversationTurn]] = defaultdict(list)
        self._lock = threading.Lock()

    # -- Public API --------------------------------------------------------

    def add_turn(
        self,
        conversation_id: str,
        user_prompt: str,
        assistant_response: str,
        raw_messages: list[ModelMessage],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """Record a completed turn in the conversation.

        Returns the :class:`ConversationTurn` that was stored.
        """
        with self._lock:
            turns = self._conversations[conversation_id]
            combined_text = f"{user_prompt}\n{assistant_response}"
            token_estimate = self._estimator.estimate(combined_text)

            turn = ConversationTurn(
                turn_id=len(turns),
                user_prompt=user_prompt,
                assistant_response=assistant_response,
                raw_messages=raw_messages,
                token_estimate=token_estimate,
                metadata=metadata or {},
            )
            turns.append(turn)

            # Check if summarization is needed
            total = sum(t.token_estimate for t in turns)
            if self._summarizer is not None and total > self._summarize_threshold:
                evicted = self._evict_oldest(conversation_id, turns)
                if evicted:
                    self._summaries[conversation_id] = self._summarizer(evicted)

            return turn

    def get_message_history(self, conversation_id: str) -> list[ModelMessage]:
        """Return the ``ModelMessage`` list for *conversation_id*,
        trimmed to fit the token budget.

        Older turns are dropped from the front (FIFO) until the total
        estimated token count fits within ``max_tokens``.
        """
        with self._lock:
            turns = list(self._conversations.get(conversation_id, []))
        if not turns:
            return []

        # Walk turns newest-first so the most recent context is always kept.
        # Older turns are dropped once the cumulative token count exceeds the budget.
        selected: list[ConversationTurn] = []
        total_tokens = 0
        for turn in reversed(turns):
            if total_tokens + turn.token_estimate > self._max_tokens:
                break
            selected.append(turn)
            total_tokens += turn.token_estimate

        selected.reverse()

        # Flatten raw_messages
        messages: list[ModelMessage] = []
        for turn in selected:
            messages.extend(turn.raw_messages)
        return messages

    def get_summary(self, conversation_id: str) -> str | None:
        """Return the summary for *conversation_id*, or *None*."""
        with self._lock:
            return self._summaries.get(conversation_id)

    def _evict_oldest(
        self,
        conversation_id: str,
        turns: list[ConversationTurn],
    ) -> list[ConversationTurn]:
        """Remove oldest turns until total tokens is within budget."""
        evicted: list[ConversationTurn] = []
        total = sum(t.token_estimate for t in turns)
        while total > self._max_tokens and len(turns) > 1:
            old = turns.pop(0)
            evicted.append(old)
            total -= old.token_estimate
        return evicted

    def get_turns(self, conversation_id: str) -> list[ConversationTurn]:
        """Return all turns for a conversation (unfiltered)."""
        with self._lock:
            return list(self._conversations.get(conversation_id, []))

    def get_total_tokens(self, conversation_id: str) -> int:
        """Return the total estimated token count for a conversation."""
        with self._lock:
            return sum(t.token_estimate for t in self._conversations.get(conversation_id, []))

    def clear(self, conversation_id: str) -> None:
        """Remove all turns for a conversation."""
        with self._lock:
            self._conversations.pop(conversation_id, None)
            self._summaries.pop(conversation_id, None)

    def clear_all(self) -> None:
        """Remove all conversations."""
        with self._lock:
            self._conversations.clear()
            self._summaries.clear()

    def new_conversation(self) -> str:
        """Create a new conversation and return its ID."""
        with self._lock:
            cid = uuid.uuid4().hex
            self._conversations[cid] = []
            return cid

    @property
    def conversation_ids(self) -> list[str]:
        """Return all active conversation IDs."""
        with self._lock:
            return list(self._conversations.keys())

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def export_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Export a conversation as a JSON-serialisable dictionary.

        Returns a dict with ``conversation_id``, ``turns``, ``summary``,
        and ``total_tokens`` suitable for backup, migration, or debugging.
        """
        with self._lock:
            turns = list(self._conversations.get(conversation_id, []))
            summary = self._summaries.get(conversation_id)

        return {
            "conversation_id": conversation_id,
            "turns": [
                {
                    "turn_id": t.turn_id,
                    "user_prompt": t.user_prompt,
                    "assistant_response": t.assistant_response,
                    "token_estimate": t.token_estimate,
                    "metadata": t.metadata,
                }
                for t in turns
            ],
            "summary": summary,
            "total_tokens": sum(t.token_estimate for t in turns),
        }

    def import_conversation(
        self,
        data: dict[str, Any],
        *,
        conversation_id: str | None = None,
    ) -> str:
        """Import a conversation from a previously exported dictionary.

        Parameters:
            data: A dict in the format produced by :meth:`export_conversation`.
            conversation_id: Override the conversation ID.  When *None*,
                uses the ID from *data*, or generates a new one.

        Returns:
            The conversation ID of the imported conversation.
        """
        cid = conversation_id or data.get("conversation_id") or uuid.uuid4().hex
        turns: list[ConversationTurn] = []

        for t in data.get("turns", []):
            user_prompt = t.get("user_prompt", "")
            assistant_response = t.get("assistant_response", "")
            token_estimate = t.get("token_estimate", 0)

            # Re-estimate tokens if the exported value is missing or zero
            if token_estimate <= 0 and (user_prompt or assistant_response):
                token_estimate = self._estimator.estimate(f"{user_prompt}\n{assistant_response}")

            turns.append(
                ConversationTurn(
                    turn_id=t.get("turn_id", len(turns)),
                    user_prompt=user_prompt,
                    assistant_response=assistant_response,
                    raw_messages=[],  # Raw messages are not portable
                    token_estimate=token_estimate,
                    metadata=t.get("metadata", {}),
                )
            )

        with self._lock:
            self._conversations[cid] = turns
            summary = data.get("summary")
            if summary:
                self._summaries[cid] = summary

        logger.debug("Imported conversation '%s' with %d turns", cid, len(turns))
        return cid

    def __repr__(self) -> str:
        return f"ConversationMemory(conversations={len(self._conversations)}, max_tokens={self._max_tokens})"
