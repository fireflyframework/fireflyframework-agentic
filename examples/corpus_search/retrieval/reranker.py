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

"""Listwise LLM reranker.

Takes the top-N candidates from hybrid retrieval, asks an LLM (Haiku by
default) which of them most directly answer the user's question, and
returns the top-K reordered. RRF is purely positional — it can rank a
mediocre chunk highly because two retrievers happened to agree on
position. The reranker reads each candidate's content against the
question, so it filters precision-killing noise and surfaces relevant
chunks that RRF buried.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel, Field

from examples.corpus_search.corpus import ChunkHit
from examples.corpus_search.retrieval.answerer import format_chunks_for_prompt
from fireflyframework_agentic.agents import FireflyAgent

log = logging.getLogger(__name__)


_INSTRUCTIONS = (
    "You receive a question and a list of candidate text chunks. Return the "
    "chunk_ids of the chunks that most directly help answer the question, "
    "ordered from most to least relevant. Do NOT include chunks that don't "
    "contain information relevant to the question, even if that means "
    "returning fewer than the requested count. Quality over quantity."
)


class RerankerResult(BaseModel):
    """Structured output schema for the reranker agent.

    The LLM returns the chunk_ids it picked, in relevance order. The
    caller resolves these back to :class:`ChunkHit` objects and drops
    any hallucinated ids.
    """

    top_chunk_ids: list[str] = Field(default_factory=list)


class HaikuReranker:
    """Listwise relevance reranker using a small LLM (Haiku by default).

    Cheap (Haiku is ~5x cheaper than Sonnet) and fast (~3 s for 20
    chunks). Falls back gracefully to the input retrieval order if the
    LLM call fails.
    """

    def __init__(self, model: str) -> None:
        self._agent = FireflyAgent(
            name="reranker",
            model=model,
            output_type=RerankerResult,
            instructions=_INSTRUCTIONS,
        )

    async def rerank(
        self,
        question: str,
        hits: Sequence[ChunkHit],
        *,
        top_k: int,
    ) -> list[ChunkHit]:
        """Return the top ``top_k`` hits by LLM-judged relevance.

        Short-circuits without an LLM call when:
        - ``hits`` is empty (returns ``[]``)
        - ``top_k >= len(hits)`` (no rerank needed; returns hits as-is)
        - ``top_k <= 0`` (returns ``[]``)

        On LLM error, logs a warning and falls back to ``hits[:top_k]``.
        Hallucinated chunk_ids in the LLM output (not present in
        ``hits``) are dropped silently.
        """
        if not hits or top_k <= 0:
            return []
        if top_k >= len(hits):
            return list(hits)

        formatted = format_chunks_for_prompt(hits)
        prompt = (
            f"Question: {question}\n\n"
            f"Return the top {top_k} chunk_ids by relevance to the question. "
            f"Skip any chunks that don't contain relevant information.\n\n"
            f"Candidates:\n\n{formatted}"
        )
        try:
            result = await self._agent.run(prompt)
            top_ids = list(getattr(result, "output", RerankerResult()).top_chunk_ids)
        except Exception as exc:
            log.warning(
                "rerank failed (%s); falling back to retrieval order",
                exc,
            )
            return list(hits[:top_k])

        # Resolve ids back to hits; drop hallucinated and duplicate ids.
        by_id = {h.chunk_id: h for h in hits}
        ranked: list[ChunkHit] = []
        seen: set[str] = set()
        for cid in top_ids:
            if cid in seen or cid not in by_id:
                continue
            seen.add(cid)
            ranked.append(by_id[cid])
            if len(ranked) >= top_k:
                break

        # Visibility — log the reranker's decision so users can see what
        # it kept vs what was dropped.
        log.info(
            "rerank: %d candidates -> %d kept (model %s)",
            len(hits),
            len(ranked),
            self._agent.name,
        )
        for i, h in enumerate(ranked, start=1):
            log.info("  [%d] %s (%s)", i, h.chunk_id, h.source_path)

        return ranked
