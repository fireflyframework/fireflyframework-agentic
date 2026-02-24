"""In-memory vector store using brute-force cosine similarity.

No external dependencies required. Suitable for dev, testing, and small datasets.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any

from fireflyframework_genai.embeddings.similarity import cosine_similarity
from fireflyframework_genai.vectorstores.base import BaseVectorStore
from fireflyframework_genai.vectorstores.types import SearchFilter, SearchResult, VectorDocument

logger = logging.getLogger(__name__)


class InMemoryVectorStore(BaseVectorStore):
    """Dict-backed in-memory vector store with brute-force search.

    Uses cosine similarity for ranking. Thread-safe via a lock.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._data: dict[str, dict[str, VectorDocument]] = defaultdict(dict)
        self._lock = threading.Lock()

    async def _upsert(self, documents: list[VectorDocument], namespace: str) -> None:
        with self._lock:
            for doc in documents:
                self._data[namespace][doc.id] = doc

    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]:
        with self._lock:
            candidates = list(self._data.get(namespace, {}).values())

        if filters:
            candidates = self._apply_filters(candidates, filters)

        scored = []
        for doc in candidates:
            if doc.embedding is None:
                continue
            score = cosine_similarity(query_embedding, doc.embedding)
            scored.append(SearchResult(document=doc, score=score))

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    async def _delete(self, ids: list[str], namespace: str) -> None:
        with self._lock:
            ns_data = self._data.get(namespace, {})
            for id_ in ids:
                ns_data.pop(id_, None)

    @staticmethod
    def _apply_filters(docs: list[VectorDocument], filters: list[SearchFilter]) -> list[VectorDocument]:
        result = docs
        for f in filters:
            result = [d for d in result if _match_filter(d, f)]
        return result


def _match_filter(doc: VectorDocument, f: SearchFilter) -> bool:
    val = doc.metadata.get(f.field)
    if val is None:
        return False
    match f.operator:
        case "eq":
            return val == f.value
        case "ne":
            return val != f.value
        case "gt":
            return val > f.value
        case "lt":
            return val < f.value
        case "gte":
            return val >= f.value
        case "lte":
            return val <= f.value
        case "in":
            return val in f.value
        case _:
            return False
