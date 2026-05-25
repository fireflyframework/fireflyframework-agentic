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

"""Structure-aware markdown chunker."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from markdown_it import MarkdownIt

from fireflyframework_agentic.content.chunking import Chunk, TextChunker

try:
    import tiktoken
except ImportError:  # pragma: no cover - optional dep
    tiktoken = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class _EncoderCache:
    """Lazy-loaded tiktoken encoder cache (cl100k_base — used by
    text-embedding-3-* and all current OpenAI / Azure OpenAI embedding
    models). When available it replaces the word-count heuristic so
    token-budget enforcement is accurate for content shapes the heuristic
    mis-estimates badly — markdown tables in particular, where every
    ``|`` and numeric cell becomes its own BPE token.

    Encapsulated as a class rather than a module-level mutable so static
    analysers correctly read the access pattern (read-write on a class
    attribute) instead of flagging it as an unused global. Same runtime
    behaviour as the previous ``_encoding_cache`` tuple.
    """

    loaded: bool = False
    encoder: Any = None


def _accurate_token_count(text: str) -> int | None:
    """Return real BPE token count via tiktoken, or *None* if unavailable.

    The heuristic ``len(text.split()) * 1.33`` undercounts table-heavy
    content by 5–20×. When that miscalculation pushes a "small" chunk past
    the embedder's 8 192-token input limit, the embed call fails with a
    non-retryable HTTP 400 and the document gets stranded in the ledger as
    ``failed``. tiktoken is a transitive dep of the openai SDK so it's
    almost always present, but we fall back gracefully if not.
    """
    if not _EncoderCache.loaded:
        if tiktoken is not None:
            try:
                _EncoderCache.encoder = tiktoken.get_encoding("cl100k_base")
            except Exception:
                _EncoderCache.encoder = None
        _EncoderCache.loaded = True
    if _EncoderCache.encoder is None:
        return None
    return len(_EncoderCache.encoder.encode(text))


@dataclass
class _Section:
    heading_stack: list[tuple[int, str]]  # [(level, title), ...]
    body: str


class MarkdownChunker:
    """Split markdown at heading boundaries with breadcrumb prepend.

    Uses ``markdown-it-py`` to tokenise so that ``#`` characters inside
    fenced code blocks and tables are never treated as headings. Sections
    whose body exceeds *max_chunk_tokens* are split further by
    :class:`TextChunker` with the same breadcrumb prepended to every
    sub-chunk.
    """

    def __init__(
        self,
        *,
        max_chunk_tokens: int = 600,
        chunk_overlap: int = 80,
        min_body_tokens: int = 10,
        breadcrumb_separator: str = " > ",
    ) -> None:
        self._max_chunk_tokens = max_chunk_tokens
        self._chunk_overlap = chunk_overlap
        self._min_body_tokens = min_body_tokens
        self._breadcrumb_separator = breadcrumb_separator
        self._fallback = TextChunker(
            chunk_size=max_chunk_tokens,
            chunk_overlap=chunk_overlap,
        )
        self._md = MarkdownIt()

    def chunk(self, content: str) -> list[Chunk]:
        """Split *content* into :class:`Chunk` objects at heading boundaries."""
        sections = self._parse_sections(content)
        chunks: list[Chunk] = []
        for section in sections:
            chunks.extend(self._emit_chunks(section))
        for i, c in enumerate(chunks):
            c.index = i
            c.total_chunks = len(chunks)
        return chunks

    def _parse_sections(self, content: str) -> list[_Section]:
        tokens = self._md.parse(content)
        lines = content.splitlines()

        heading_locs: list[tuple[int, int, str]] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == "heading_open" and tok.map:
                level = int(tok.tag[1])  # "h1" -> 1
                line_number = tok.map[0]
                title = tokens[i + 1].content if i + 1 < len(tokens) and tokens[i + 1].type == "inline" else ""
                heading_locs.append((line_number, level, title))
                i += 2  # skip the inline token; heading_close follows and will be skipped by the else branch
            else:
                i += 1

        sections: list[_Section] = []
        heading_stack: list[tuple[int, str]] = []

        first_line = heading_locs[0][0] if heading_locs else len(lines)
        preamble = "\n".join(lines[:first_line]).strip()
        if preamble:
            sections.append(_Section(heading_stack=[], body=preamble))

        for idx, (line_no, level, title) in enumerate(heading_locs):
            next_line = heading_locs[idx + 1][0] if idx + 1 < len(heading_locs) else len(lines)
            body = "\n".join(lines[line_no + 1 : next_line]).strip()
            # Drop entries at the same depth or deeper, then push the new heading.
            heading_stack = [(lvl, ttl) for lvl, ttl in heading_stack if lvl < level]
            heading_stack.append((level, title))
            sections.append(_Section(heading_stack=list(heading_stack), body=body))

        return sections

    def _estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) * 1.33))

    def _emit_chunks(self, section: _Section) -> list[Chunk]:
        if not section.body.strip():
            return []
        if self._estimate_tokens(section.body) < self._min_body_tokens:
            return []

        breadcrumb = self._breadcrumb_separator.join(title for _, title in section.heading_stack)

        def make_chunk(body: str) -> Chunk:
            content = f"{breadcrumb}\n\n{body}" if breadcrumb else body
            return Chunk(content=content, metadata={"breadcrumb": breadcrumb})

        if self._estimate_tokens(section.body) <= self._max_chunk_tokens:
            bodies = [section.body]
        else:
            bodies = [sc.content for sc in self._fallback.chunk(section.body)]

        # Hard-enforce ``max_chunk_tokens`` against the real BPE tokeniser
        # when available, sub-splitting any body whose word-count estimate
        # mis-judged the true token count (markdown tables in particular —
        # every ``|`` and numeric cell becomes its own BPE token, which
        # the heuristic undercounts by 5–20×). Without this pass, oversized
        # chunks make it to the embedder and trigger non-retryable HTTP 400s.
        # Crucially this happens before breadcrumb prepending so the
        # breadcrumb stays attached to every emitted chunk.
        budgeted: list[str] = []
        budget = (
            max(1, self._max_chunk_tokens - self._estimate_tokens(breadcrumb)) if breadcrumb else self._max_chunk_tokens
        )
        for body in bodies:
            budgeted.extend(self._hard_split(body, budget=budget))
        return [make_chunk(b) for b in budgeted]

    def _hard_split(self, content: str, *, budget: int) -> list[str]:
        """Recursively halve *content* on newline boundaries until each
        piece fits under ``budget`` BPE tokens. Falls back to character-
        midpoint splitting when no useful newline exists in a half.

        We split on newlines so that table rows / paragraph boundaries
        survive intact wherever possible; pure character halving is a
        last-resort fallback for content with no whitespace structure
        (e.g. base64 blobs).
        """
        real = _accurate_token_count(content)
        if real is None or real <= budget:
            return [content]
        midpoint = len(content) // 2
        nl = content.rfind("\n", 0, midpoint)
        cut = nl if nl > 0 else midpoint
        left = content[:cut]
        right = content[cut:]
        if not left.strip() or not right.strip():
            # No useful whitespace to split on; force a midpoint cut.
            cut = midpoint
            left = content[:cut]
            right = content[cut:]
        if left == content or right == content:
            return [content]
        return self._hard_split(left, budget=budget) + self._hard_split(right, budget=budget)
