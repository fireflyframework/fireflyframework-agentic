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

"""Structure-aware markdown chunker."""

from __future__ import annotations

from dataclasses import dataclass

from markdown_it import MarkdownIt

from fireflyframework_agentic.content.chunking import Chunk, TextChunker


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
        min_body_tokens: int = 1,
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
        tokens = MarkdownIt().parse(content)
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
                i += 2
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
            return [make_chunk(section.body)]

        return [make_chunk(sc.content) for sc in self._fallback.chunk(section.body)]
