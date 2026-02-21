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

"""Content chunking: text splitting, document splitting, and image tiling.

All chunkers produce :class:`Chunk` objects that carry content together with
positional metadata so that downstream consumers can reconstruct provenance.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from fireflyframework_genai.types import AgentLike

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chunk model
# ---------------------------------------------------------------------------


class Chunk(BaseModel):
    """A single content chunk with provenance metadata.

    Attributes:
        content: The chunk payload (text, base64-encoded image data, etc.).
        index: Zero-based position in the chunk sequence.
        total_chunks: Total number of chunks produced from the source.
        source_start: Start offset in the original content (chars for text,
            pixels for images).
        source_end: End offset in the original content.
        overlap_tokens: Number of tokens shared with the previous chunk.
        metadata: Arbitrary key-value pairs (e.g. page number, tile coords).
    """

    content: str
    index: int = 0
    total_chunks: int = 1
    source_start: int = 0
    source_end: int = 0
    overlap_tokens: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Chunker protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Chunker(Protocol):
    """Protocol for any object that can chunk content."""

    def chunk(self, content: str) -> list[Chunk]:
        """Split *content* into a list of :class:`Chunk` objects."""
        ...


# ---------------------------------------------------------------------------
# TextChunker
# ---------------------------------------------------------------------------


class TextChunker:
    """Split text by estimated token count, sentences, or paragraphs.

    Parameters:
        chunk_size: Maximum number of estimated tokens per chunk.
        chunk_overlap: Number of overlapping tokens between consecutive chunks.
        strategy: ``"token"`` (default), ``"sentence"``, or ``"paragraph"``.
        tokens_per_word: Conversion factor for token estimation.
    """

    def __init__(
        self,
        *,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        strategy: str = "token",
        tokens_per_word: float = 1.33,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._strategy = strategy
        self._tokens_per_word = tokens_per_word

    def chunk(self, content: str) -> list[Chunk]:
        """Split *content* into token-bounded chunks."""
        if not content.strip():
            return []
        if self._strategy == "sentence":
            return self._chunk_by_sentence(content)
        if self._strategy == "paragraph":
            return self._chunk_by_paragraph(content)
        return self._chunk_by_token(content)

    # -- Strategies ----------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) * self._tokens_per_word))

    def _chunk_by_token(self, content: str) -> list[Chunk]:
        words = content.split()
        # Convert token-based limits to word counts using the configured ratio.
        words_per_chunk = max(1, int(self._chunk_size / self._tokens_per_word))
        overlap_words = max(0, int(self._chunk_overlap / self._tokens_per_word))
        # Step size = words per chunk minus overlap, so consecutive chunks share
        # ``overlap_words`` at their boundary for context continuity.
        step = max(1, words_per_chunk - overlap_words)

        chunks: list[Chunk] = []
        search_offset = 0
        for start_idx in range(0, len(words), step):
            end_idx = min(start_idx + words_per_chunk, len(words))
            chunk_words = words[start_idx:end_idx]
            text = " ".join(chunk_words)
            char_start = content.index(chunk_words[0], search_offset) if chunk_words else search_offset
            char_end = char_start + len(text)
            search_offset = char_start + 1
            chunks.append(
                Chunk(
                    content=text,
                    index=len(chunks),
                    source_start=char_start,
                    source_end=char_end,
                    overlap_tokens=self._chunk_overlap if start_idx > 0 else 0,
                )
            )
            if end_idx >= len(words):
                break

        for c in chunks:
            c.total_chunks = len(chunks)
        return chunks

    def _chunk_by_sentence(self, content: str) -> list[Chunk]:
        sentences = re.split(r"(?<=[.!?])\s+", content)
        return self._group_segments(content, sentences)

    def _chunk_by_paragraph(self, content: str) -> list[Chunk]:
        paragraphs = re.split(r"\n\s*\n", content)
        return self._group_segments(content, paragraphs)

    def _group_segments(self, content: str, segments: list[str]) -> list[Chunk]:
        chunks: list[Chunk] = []
        current_segments: list[str] = []
        current_tokens = 0

        for seg in segments:
            seg_tokens = self._estimate_tokens(seg)
            if current_tokens + seg_tokens > self._chunk_size and current_segments:
                text = " ".join(current_segments)
                chunks.append(Chunk(content=text, index=len(chunks)))
                # Keep overlap
                overlap_segs: list[str] = []
                overlap_tok = 0
                for s in reversed(current_segments):
                    t = self._estimate_tokens(s)
                    if overlap_tok + t > self._chunk_overlap:
                        break
                    overlap_segs.insert(0, s)
                    overlap_tok += t
                current_segments = overlap_segs
                current_tokens = overlap_tok

            current_segments.append(seg)
            current_tokens += seg_tokens

        if current_segments:
            text = " ".join(current_segments)
            chunks.append(Chunk(content=text, index=len(chunks)))

        for c in chunks:
            c.total_chunks = len(chunks)
        return chunks


# ---------------------------------------------------------------------------
# DocumentSplitter
# ---------------------------------------------------------------------------


class DocumentSplitter:
    """Split a multi-document text into individual document segments.

    Documents are identified by page breaks, horizontal rules, or a
    custom separator pattern.

    Parameters:
        separator: Regex pattern that separates documents.
        min_length: Minimum character length for a segment to be kept.
    """

    def __init__(
        self,
        *,
        separator: str = r"\f|\n-{3,}\n|\n={3,}\n",
        min_length: int = 10,
    ) -> None:
        self._separator = re.compile(separator)
        self._min_length = min_length

    def split(self, content: str) -> list[Chunk]:
        """Split *content* into document segments."""
        parts = self._separator.split(content)
        chunks: list[Chunk] = []
        offset = 0
        for part in parts:
            stripped = part.strip()
            if len(stripped) >= self._min_length:
                start = content.index(stripped, offset) if stripped else offset
                chunks.append(
                    Chunk(
                        content=stripped,
                        index=len(chunks),
                        source_start=start,
                        source_end=start + len(stripped),
                        metadata={"type": "document_segment"},
                    )
                )
                offset = start + len(stripped)
            else:
                offset += len(part)

        for c in chunks:
            c.total_chunks = len(chunks)
        return chunks


# ---------------------------------------------------------------------------
# ImageTiler
# ---------------------------------------------------------------------------


class ImageTiler:
    """Split a large image into tiles for VLM processing.

    The tiler works with image dimensions and produces :class:`Chunk` objects
    whose metadata contains tile coordinates.  Actual pixel extraction is
    left to the caller (the framework is image-library-agnostic).

    Parameters:
        tile_width: Width of each tile in pixels.
        tile_height: Height of each tile in pixels.
        overlap: Overlap in pixels on each axis.
    """

    def __init__(
        self,
        *,
        tile_width: int = 1024,
        tile_height: int = 1024,
        overlap: int = 64,
    ) -> None:
        self._tile_width = tile_width
        self._tile_height = tile_height
        self._overlap = overlap

    def compute_tiles(self, image_width: int, image_height: int) -> list[Chunk]:
        """Compute tile coordinates for an image of the given dimensions.

        Returns :class:`Chunk` objects where ``metadata`` contains
        ``x``, ``y``, ``width``, ``height`` of each tile.  ``content``
        is set to a descriptive placeholder (callers fill in actual data).
        """
        step_x = max(1, self._tile_width - self._overlap)
        step_y = max(1, self._tile_height - self._overlap)
        cols = math.ceil(image_width / step_x)
        rows = math.ceil(image_height / step_y)

        tiles: list[Chunk] = []
        for row in range(rows):
            for col in range(cols):
                x = col * step_x
                y = row * step_y
                w = min(self._tile_width, image_width - x)
                h = min(self._tile_height, image_height - y)
                tiles.append(
                    Chunk(
                        content=f"tile_{row}_{col}",
                        index=len(tiles),
                        source_start=y * image_width + x,
                        source_end=(y + h) * image_width + (x + w),
                        metadata={"x": x, "y": y, "width": w, "height": h, "row": row, "col": col},
                    )
                )

        for t in tiles:
            t.total_chunks = len(tiles)
        return tiles


# ---------------------------------------------------------------------------
# BatchProcessor
# ---------------------------------------------------------------------------


class BatchProcessor:
    """Process a sequence of chunks through an agent and aggregate results.

    Parameters:
        concurrency: Maximum number of concurrent agent calls.
        result_aggregator: Optional callable to merge individual results.
            Defaults to returning a list of string results.
    """

    def __init__(
        self,
        *,
        concurrency: int = 5,
        result_aggregator: Callable[[list[Any]], Any] | None = None,
    ) -> None:
        self._concurrency = concurrency
        self._aggregator = result_aggregator or (lambda results: results)

    async def process(
        self,
        agent: AgentLike,
        chunks: Sequence[Chunk],
        *,
        prompt_template: str = "{content}",
        **kwargs: Any,
    ) -> Any:
        """Run *agent* on each chunk and aggregate the outputs.

        Parameters:
            agent: A :class:`FireflyAgent` or any object with an async
                ``run(prompt)`` method.
            chunks: The chunks to process.
            prompt_template: A format string where ``{content}`` is replaced
                with the chunk content.  Additional chunk metadata fields
                are also available (e.g. ``{index}``).
            **kwargs: Extra keyword arguments forwarded to ``agent.run()``.
        """
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _run_one(chunk: Chunk) -> str:
            async with semaphore:
                prompt = prompt_template.format(
                    content=chunk.content,
                    index=chunk.index,
                    total_chunks=chunk.total_chunks,
                    **chunk.metadata,
                )
                result = await agent.run(prompt, **kwargs)
                return str(result.output if hasattr(result, "output") else result)

        results = await asyncio.gather(*[_run_one(c) for c in chunks])
        return self._aggregator(list(results))
