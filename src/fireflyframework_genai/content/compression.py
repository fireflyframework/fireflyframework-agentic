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

"""Context compression: token estimation, truncation, summarization, and map-reduce.

These utilities help fit large documents into model context windows while
preserving the most important information.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Protocol, runtime_checkable

from fireflyframework_genai.content.chunking import TextChunker
from fireflyframework_genai.types import AgentLike

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TokenEstimator:
    """Estimate token counts for text content.

    Uses a word-based heuristic by default.  If ``tiktoken`` is installed
    and an *encoding_name* is provided, uses the exact tokenizer instead.

    Parameters:
        tokens_per_word: Heuristic conversion factor (default 1.33).
        encoding_name: Optional tiktoken encoding (e.g. ``"cl100k_base"``).
    """

    def __init__(
        self,
        *,
        tokens_per_word: float = 1.33,
        encoding_name: str | None = None,
    ) -> None:
        self._tokens_per_word = tokens_per_word
        self._encoder: Any = None
        if encoding_name:
            try:
                import tiktoken

                self._encoder = tiktoken.get_encoding(encoding_name)
            except ImportError:
                logger.debug("tiktoken not installed; falling back to heuristic estimation")

    def estimate(self, text: str) -> int:
        """Return estimated token count for *text*."""
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        return max(1, int(len(text.split()) * self._tokens_per_word))

    def fits(self, text: str, max_tokens: int) -> bool:
        """Return *True* if *text* fits within *max_tokens*."""
        return self.estimate(text) <= max_tokens


# ---------------------------------------------------------------------------
# Compression strategy protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class CompressionStrategy(Protocol):
    """Protocol for context compression strategies."""

    async def compress(self, text: str, max_tokens: int) -> str:
        """Compress *text* to fit within *max_tokens*."""
        ...


# ---------------------------------------------------------------------------
# Built-in strategies
# ---------------------------------------------------------------------------


class TruncationStrategy:
    """Simple truncation that keeps the beginning of the text.

    Parameters:
        tokens_per_word: Conversion factor for word-to-token estimation.
        suffix: Appended to truncated text to indicate truncation.
    """

    def __init__(
        self,
        *,
        tokens_per_word: float = 1.33,
        suffix: str = "\n\n[... truncated ...]",
    ) -> None:
        self._tokens_per_word = tokens_per_word
        self._suffix = suffix

    async def compress(self, text: str, max_tokens: int) -> str:
        words = text.split()
        max_words = max(1, int(max_tokens / self._tokens_per_word))
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]) + self._suffix


class SummarizationStrategy:
    """Use an agent to summarize the text to fit within the token budget.

    Parameters:
        agent: An agent with an async ``run(prompt)`` method.
        system_instruction: Custom summarization instruction.
    """

    def __init__(
        self,
        agent: AgentLike,
        *,
        system_instruction: str = (
            "Summarize the following text concisely while preserving all key "
            "information, facts, names, dates, and figures."
        ),
    ) -> None:
        self._agent = agent
        self._instruction = system_instruction

    async def compress(self, text: str, max_tokens: int) -> str:
        prompt = f"{self._instruction}\n\nTarget maximum length: approximately {max_tokens} tokens.\n\nText:\n{text}"
        result = await self._agent.run(prompt)
        return str(result.output if hasattr(result, "output") else result)


class MapReduceStrategy:
    """Chunk -> summarize each -> merge summaries.

    Parameters:
        agent: An agent used for both the map and reduce phases.
        chunk_size: Token size per chunk for the map phase.
        chunk_overlap: Overlap between map chunks.
    """

    def __init__(
        self,
        agent: AgentLike,
        *,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
    ) -> None:
        self._agent = agent
        self._chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    async def compress(self, text: str, max_tokens: int) -> str:
        chunks = self._chunker.chunk(text)
        if len(chunks) <= 1:
            return text

        # Map phase: summarize each chunk
        summaries: list[str] = []
        for chunk in chunks:
            prompt = f"Summarize this text segment concisely, preserving key facts:\n\n{chunk.content}"
            result = await self._agent.run(prompt)
            summaries.append(str(result.output if hasattr(result, "output") else result))

        # Reduce phase: merge summaries
        merged = "\n\n".join(summaries)
        estimator = TokenEstimator()
        if estimator.fits(merged, max_tokens):
            return merged

        # If still too long, do a final reduction
        prompt = (
            f"Combine these summaries into a single cohesive summary of approximately {max_tokens} tokens:\n\n{merged}"
        )
        result = await self._agent.run(prompt)
        return str(result.output if hasattr(result, "output") else result)


# ---------------------------------------------------------------------------
# ContextCompressor
# ---------------------------------------------------------------------------


class ContextCompressor:
    """Reduce context to fit within a token budget using a pluggable strategy.

    Parameters:
        strategy: The compression strategy to use.
        estimator: Optional :class:`TokenEstimator` (created with defaults
            if not provided).
    """

    def __init__(
        self,
        strategy: CompressionStrategy,
        *,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self._strategy = strategy
        self._estimator = estimator or TokenEstimator()

    async def compress(self, text: str, max_tokens: int) -> str:
        """Compress *text* to fit within *max_tokens* if necessary."""
        if self._estimator.fits(text, max_tokens):
            return text
        return await self._strategy.compress(text, max_tokens)


# ---------------------------------------------------------------------------
# SlidingWindowManager
# ---------------------------------------------------------------------------


class SlidingWindowManager:
    """Maintain a rolling window of context within token limits.

    Useful for conversational or streaming scenarios where new content
    is appended and old content must be evicted to stay within budget.

    Parameters:
        max_tokens: Maximum token capacity of the window.
        estimator: Optional :class:`TokenEstimator`.
    """

    def __init__(
        self,
        *,
        max_tokens: int = 128_000,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self._max_tokens = max_tokens
        self._estimator = estimator or TokenEstimator()
        self._segments: deque[str] = deque()
        self._running_tokens = 0

    def add(self, segment: str) -> None:
        """Append a new segment to the window, evicting oldest if needed."""
        seg_tokens = self._estimator.estimate(segment)
        self._segments.append(segment)
        self._running_tokens += seg_tokens
        self._evict()

    def get_context(self) -> str:
        """Return the current window content as a single string."""
        return "\n\n".join(self._segments)

    @property
    def segment_count(self) -> int:
        return len(self._segments)

    @property
    def estimated_tokens(self) -> int:
        return self._running_tokens if self._segments else 0

    def clear(self) -> None:
        self._segments.clear()
        self._running_tokens = 0

    def _evict(self) -> None:
        """Remove oldest segments until the window fits."""
        while len(self._segments) > 1 and self._running_tokens > self._max_tokens:
            removed = self._segments.popleft()
            self._running_tokens -= self._estimator.estimate(removed)
