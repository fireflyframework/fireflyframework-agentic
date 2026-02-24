"""Pinecone vector store backend."""

from __future__ import annotations

import logging
from typing import Any

try:
    from pinecone import Pinecone  # type: ignore[import-untyped]
except ImportError:
    Pinecone = None  # type: ignore[assignment,misc]

from fireflyframework_genai.vectorstores.base import BaseVectorStore
from fireflyframework_genai.vectorstores.types import SearchFilter, SearchResult, VectorDocument

logger = logging.getLogger(__name__)


class PineconeVectorStore(BaseVectorStore):
    """Pinecone-backed vector store.

    Parameters:
        index_name: Pinecone index name.
        api_key: Pinecone API key. Falls back to ``PINECONE_API_KEY`` env var.
        embedder: Optional embedder for auto-embedding.
    """

    def __init__(
        self,
        index_name: str,
        *,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if Pinecone is None:
            raise ImportError(
                "pinecone package is required for PineconeVectorStore. Install it with: pip install pinecone"
            )
        self._pc = Pinecone(api_key=api_key)
        self._index = self._pc.Index(index_name)

    async def _upsert(self, documents: list[VectorDocument], namespace: str) -> None:
        vectors = []
        for doc in documents:
            vectors.append(
                {
                    "id": doc.id,
                    "values": doc.embedding,
                    "metadata": {**doc.metadata, "_text": doc.text},
                }
            )
        self._index.upsert(vectors=vectors, namespace=namespace)

    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]:
        filter_dict = None
        if filters:
            filter_dict = {}
            for f in filters:
                if f.operator == "eq":
                    filter_dict[f.field] = f.value
                elif f.operator == "in":
                    filter_dict[f.field] = {"$in": f.value}

        response = self._index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=namespace,
            filter=filter_dict,
            include_metadata=True,
        )
        results = []
        for match in response.get("matches", []):
            metadata = dict(match.get("metadata", {}))
            text = metadata.pop("_text", "")
            doc = VectorDocument(
                id=match["id"],
                text=text,
                metadata=metadata,
                namespace=namespace,
            )
            results.append(SearchResult(document=doc, score=match.get("score", 0.0)))
        return results

    async def _delete(self, ids: list[str], namespace: str) -> None:
        self._index.delete(ids=ids, namespace=namespace)
