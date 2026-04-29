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

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from fireflyframework_agentic.agents import FireflyAgent

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpandedQuery:
    """A single query issued during retrieval, with routing metadata.

    ``route`` controls which search backends the query hits:

    - ``"hybrid"``: BM25 (FTS5) + vector search — used for the original
      question and paraphrase variants.
    - ``"vec_only"``: vector search only — used for the HyDE passage.
      Routing a hypothetical document through BM25 adds noise because its
      token distribution doesn't match the real document vocabulary.
    """

    text: str
    route: Literal["hybrid", "vec_only"]


class _ExpandedQueries(BaseModel):
    """Structured output schema for the expansion agent."""

    variants: list[str] = Field(default_factory=list)
    hyde: str = Field(
        default="",
        description=(
            "A short hypothetical document passage (2-4 sentences) written as if "
            "it were an excerpt from the source document that answers the question. "
            "This is used for semantic vector retrieval only, not keyword search."
        ),
    )


class QueryExpander:
    """Expand a user question into paraphrase variants plus a HyDE passage.

    Returns a list of ``ExpandedQuery`` objects:

    - The original question always comes first (``route='hybrid'``).
    - Paraphrase variants follow (``route='hybrid'``) — they hit both BM25
      and vector search.
    - A single HyDE (Hypothetical Document Embedding) passage is appended
      last (``route='vec_only'``) — routed to vector search only, because
      its hypothetical token distribution would mislead BM25.

    On LLM failure, falls back to the original question only.
    """

    _INSTRUCTIONS = (
        "You are a retrieval query expander. Given a user's question:\n"
        "1. Generate alternative phrasings (synonyms, related concepts, rephrased "
        "forms) as standalone queries. Do not repeat the original question.\n"
        "2. Write a short hypothetical document passage (2-4 sentences) that would "
        "directly answer the question, phrased as an excerpt from the source document "
        "— not as a question or answer pair, but as prose from the document itself."
    )

    def __init__(self, model: str) -> None:
        self._agent = FireflyAgent(
            name="query_expander",
            model=model,
            output_type=_ExpandedQueries,
            instructions=self._INSTRUCTIONS,
        )

    async def expand(self, question: str, *, n_variants: int = 4) -> list[ExpandedQuery]:
        """Expand *question* into at most ``n_variants + 1`` queries.

        ``n_variants`` controls how many paraphrase variants to request from
        the LLM (one slot is reserved for the HyDE passage). The returned
        list always starts with the original question and ends with the HyDE
        entry when available.
        """
        n_paraphrase = max(1, n_variants - 1)
        prompt = (
            f"Generate {n_paraphrase} alternative phrasings and one hypothetical "
            f"document passage.\n\nQuestion: {question}"
        )
        try:
            result = await self._agent.run(prompt)
            output = getattr(result, "output", _ExpandedQueries())
            variants = list(output.variants)
            hyde = output.hyde.strip() if output.hyde else ""
        except Exception as exc:
            log.warning("query expansion failed for %r: %s", question, exc)
            variants = []
            hyde = ""

        seen: set[str] = {question}
        out: list[ExpandedQuery] = [ExpandedQuery(text=question, route="hybrid")]

        for v in variants:
            v = v.strip()
            if v and v not in seen and len(out) <= n_paraphrase:
                seen.add(v)
                out.append(ExpandedQuery(text=v, route="hybrid"))

        if hyde and hyde not in seen:
            out.append(ExpandedQuery(text=hyde, route="vec_only"))

        log.info("query expansion produced %d query/queries:", len(out))
        for i, q in enumerate(out):
            if i == 0:
                label = "original"
            elif q.route == "vec_only":
                label = "hyde"
            else:
                label = f"variant {i}"
            log.info("  [%s] %s", label, q.text)

        return out
