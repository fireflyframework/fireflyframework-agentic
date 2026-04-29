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

from pydantic import BaseModel, Field

from fireflyframework_agentic.agents import FireflyAgent

log = logging.getLogger(__name__)


class _ExpandedQueries(BaseModel):
    """Structured output schema for the expansion agent."""

    variants: list[str] = Field(default_factory=list)


class QueryExpander:
    """Expand a user question into multiple alternative phrasings via an LLM.

    On LLM failure, falls back to returning just the original question. The
    original question is always returned first; variants are deduplicated
    against each other and the original; empty strings are dropped.
    """

    _INSTRUCTIONS = (
        "Generate alternative ways to phrase the user's question that might "
        "match different wording in source documents. Include synonyms, "
        "related concepts, and rephrased forms. Return only the variants — "
        "do not repeat the original question. Each variant should be a "
        "complete, standalone query."
    )

    def __init__(self, model: str) -> None:
        self._agent = FireflyAgent(
            name="query_expander",
            model=model,
            output_type=_ExpandedQueries,
            instructions=self._INSTRUCTIONS,
        )

    async def expand(self, question: str, *, n_variants: int = 4) -> list[str]:
        prompt = f"Generate {n_variants} alternative phrasings.\n\nQuestion: {question}"
        try:
            result = await self._agent.run(prompt)
            variants = list(getattr(result, "output", _ExpandedQueries()).variants)
        except Exception as exc:
            log.warning("query expansion failed for %r: %s", question, exc)
            variants = []

        # Original always first; dedupe; drop empties; cap at n_variants + 1.
        seen: set[str] = set()
        out: list[str] = []
        for q in [question, *variants]:
            q = q.strip()
            if q and q not in seen:
                seen.add(q)
                out.append(q)
            if len(out) >= n_variants + 1:
                break

        # Visibility — log each query on its own line so the user can see
        # exactly what BM25 + vector search will be issued for. Index 0 is
        # the original question; the rest are LLM-generated reformulations.
        log.info("query expansion produced %d query/queries:", len(out))
        for i, q in enumerate(out):
            label = "original" if i == 0 else f"variant {i}"
            log.info("  [%s] %s", label, q)

        return out
