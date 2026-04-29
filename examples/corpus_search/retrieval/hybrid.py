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
from collections.abc import Sequence

from examples.corpus_search.corpus import ChunkHit, SqliteCorpus
from examples.corpus_search.retrieval.expander import ExpandedQuery
from fireflyframework_agentic.embeddings.base import EmbeddingProtocol
from fireflyframework_agentic.vectorstores.base import VectorStoreProtocol

log = logging.getLogger(__name__)


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], *, k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over multiple ranked lists.

    Given a list of rankings (each a sequence of ``chunk_id`` strings ordered
    best-first), returns ``[(chunk_id, score), ...]`` sorted by descending RRF
    score. Score formula: ``Σ_r 1 / (k + rank_r)`` where rank_r is 1-indexed
    rank in ranking r. Items not present in a ranking simply contribute 0 from
    that ranking.

    The ``k`` constant smooths out lower-ranked items; the standard value is 60.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


class HybridRetriever:
    """Hybrid retrieval: BM25 (FTS5) + dense vectors, fused via RRF.

    For each input query, runs BM25 and/or vector search according to the
    query's route, then fuses all rankings via Reciprocal Rank Fusion.

    Queries are accepted as plain strings or ``ExpandedQuery`` objects:

    - ``route='hybrid'`` (default for plain strings): BM25 + vector.
    - ``route='vec_only'``: vector search only. Used for HyDE passages —
      routing hypothetical document text through BM25 adds noise because the
      token distribution of a generated passage doesn't match real documents.
    """

    def __init__(
        self,
        *,
        corpus: SqliteCorpus,
        vector_store: VectorStoreProtocol,
        embedder: EmbeddingProtocol,
    ) -> None:
        self._corpus = corpus
        self._vector_store = vector_store
        self._embedder = embedder

    async def retrieve(
        self,
        queries: Sequence[str | ExpandedQuery],
        *,
        top_k_per_query: int = 30,
        top_k_final: int = 10,
    ) -> list[ChunkHit]:
        if not queries:
            return []

        rankings: list[list[str]] = []
        for raw_q in queries:
            if isinstance(raw_q, ExpandedQuery):
                text, route = raw_q.text, raw_q.route
            else:
                text, route = raw_q, "hybrid"

            # BM25 — skipped for vec_only (HyDE) queries
            if route != "vec_only":
                try:
                    bm25_hits = await self._corpus.bm25_search(text, top_k=top_k_per_query)
                    rankings.append([h.chunk_id for h in bm25_hits])
                except Exception as exc:  # noqa: BLE001
                    log.warning("bm25 failed for query %r: %s", text, exc)

            # Vector — always
            try:
                qvec = await self._embedder.embed_one(text)
                vec_hits = await self._vector_store.search(qvec, top_k=top_k_per_query)
                vec_ids = [getattr(h, "id", None) for h in vec_hits]
                rankings.append([i for i in vec_ids if i])
            except Exception as exc:  # noqa: BLE001
                log.warning("vector search failed for query %r: %s", text, exc)

        if not any(rankings):
            return []

        fused = reciprocal_rank_fusion(rankings)
        top_ids = [cid for cid, _ in fused[:top_k_final]]
        if not top_ids:
            return []

        # Materialise content from the corpus
        score_by_id = dict(fused[:top_k_final])
        stored = await self._corpus.get_chunks(top_ids)
        stored_by_id = {c.chunk_id: c for c in stored}

        results: list[ChunkHit] = []
        for cid in top_ids:
            chunk = stored_by_id.get(cid)
            if chunk is None:
                # ID came from vector store but isn't in the corpus — skip silently.
                continue
            results.append(
                ChunkHit(
                    chunk_id=chunk.chunk_id,
                    score=score_by_id[cid],
                    content=chunk.content,
                    metadata=chunk.metadata,
                    source_path=chunk.source_path,
                    doc_id=chunk.doc_id,
                )
            )
        return results
