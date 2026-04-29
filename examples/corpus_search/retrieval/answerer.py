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

from fireflyframework_agentic.agents import FireflyAgent

from examples.corpus_search.corpus import ChunkHit


_NO_INFO_TEXT = "I don't have enough information."

_INSTRUCTIONS = (
    "You answer questions strictly from the provided source chunks. "
    "Cite chunks inline using [chunk_id] notation immediately after each "
    "claim that the chunk supports. If the chunks do not support an answer, "
    "reply exactly: 'I don't have enough information.' Populate the "
    "`citations` field with the unique chunk_ids you actually cited in `text`."
)


class Answer(BaseModel):
    """Structured answer with inline citations."""

    text: str
    citations: list[str] = Field(default_factory=list)


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


class AnswerAgent:
    """Synthesise an answer from retrieved chunks via an LLM (Sonnet by default).

    Empty hits short-circuit to a fixed 'no info' answer without an LLM call.
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
            return Answer(text=_NO_INFO_TEXT, citations=[])
        formatted = format_chunks_for_prompt(hits)
        prompt = f"Question: {question}\n\nSource chunks:\n\n{formatted}"
        result = await self._agent.run(prompt)
        return result.output
