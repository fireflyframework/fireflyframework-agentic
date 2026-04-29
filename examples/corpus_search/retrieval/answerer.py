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

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from examples.corpus_search.corpus import ChunkHit
from fireflyframework_agentic.agents import FireflyAgent

_NO_INFO_TEXT = "I don't have enough information."

_INSTRUCTIONS = (
    "You answer questions strictly from the provided source chunks. "
    "Cite chunks inline using [chunk_id] notation immediately after each "
    "claim that the chunk supports. If the chunks do not support an answer, "
    "reply exactly: 'I don't have enough information.' Populate the "
    "`citations` field with the unique chunk_ids you actually cited in `text`."
)


class CitedSource(BaseModel):
    """A chunk that the LLM cited, enriched with source-path metadata so
    callers can show users a human-readable filename instead of the opaque
    chunk_id alone.
    """

    chunk_id: str
    source_path: str
    snippet: str


class Answer(BaseModel):
    """Structured answer with inline citations.

    The LLM populates ``text`` and ``citations`` (chunk_ids it referenced).
    ``cited_sources`` is enriched by :class:`AnswerAgent` *after* the LLM
    call from the hits passed in — gives the caller chunk_id → source_path
    mapping without forcing the LLM to handle paths in its output schema.
    """

    text: str
    citations: list[str] = Field(default_factory=list)
    cited_sources: list[CitedSource] = Field(default_factory=list)


def format_chunks_for_prompt(hits: Sequence[ChunkHit]) -> str:
    """Format chunk hits as labelled context blocks for the LLM prompt.

    Each block is ``[chunk_id] (source: path)\\ncontent`` separated by blank lines.
    Empty hit list returns empty string.
    """
    if not hits:
        return ""
    parts = []
    for h in hits:
        parts.append(f"[{h.chunk_id}] (source: {h.source_path})\n{h.content}")
    return "\n\n".join(parts)


def _build_cited_sources(
    citations: Sequence[str], hits: Sequence[ChunkHit], *, snippet_chars: int = 200
) -> list[CitedSource]:
    """Map cited chunk_ids back to their hit metadata.

    Citations the LLM hallucinated (chunk_ids not in `hits`) are dropped;
    the snippet is the first ``snippet_chars`` characters of the chunk's
    actual content.
    """
    by_id = {h.chunk_id: h for h in hits}
    sources: list[CitedSource] = []
    seen: set[str] = set()
    for cid in citations:
        if cid in seen or cid not in by_id:
            continue
        seen.add(cid)
        h = by_id[cid]
        sources.append(
            CitedSource(
                chunk_id=cid,
                source_path=h.source_path,
                snippet=h.content[:snippet_chars].strip(),
            )
        )
    return sources


class AnswerAgent:
    """Synthesise an answer from retrieved chunks via an LLM (Sonnet by default).

    Empty hits short-circuit to a fixed 'no info' answer without an LLM call.
    Cited chunk_ids are enriched post-call into :class:`CitedSource` records
    so callers can present source paths alongside the inline citations.
    """

    def __init__(self, model: str) -> None:
        self._agent = FireflyAgent(
            name="answer_agent",
            model=model,
            output_type=Answer,
            instructions=_INSTRUCTIONS,
        )

    async def answer(self, question: str, hits: Sequence[ChunkHit]) -> Answer:
        if not hits:
            return Answer(text=_NO_INFO_TEXT, citations=[], cited_sources=[])
        formatted = format_chunks_for_prompt(hits)
        prompt = f"Question: {question}\n\nSource chunks:\n\n{formatted}"
        result = await self._agent.run(prompt)
        answer = result.output
        # Enrich with source-path metadata so callers (CLI, API consumers)
        # can show users a filename rather than just an opaque chunk_id.
        answer.cited_sources = _build_cited_sources(answer.citations, hits)
        return answer
