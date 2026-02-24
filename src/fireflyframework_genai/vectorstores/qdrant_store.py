"""Qdrant vector store backend."""

from __future__ import annotations

import logging
from typing import Any

try:
    from qdrant_client import AsyncQdrantClient  # type: ignore[import-untyped]
    from qdrant_client.models import (  # type: ignore[import-untyped]
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointIdsList,
        PointStruct,
        VectorParams,
    )
except ImportError:
    AsyncQdrantClient = None  # type: ignore[assignment,misc]
    PointStruct = None  # type: ignore[assignment,misc]
    VectorParams = None  # type: ignore[assignment,misc]
    Distance = None  # type: ignore[assignment,misc]
    FieldCondition = None  # type: ignore[assignment,misc]
    Filter = None  # type: ignore[assignment,misc]
    MatchValue = None  # type: ignore[assignment,misc]
    PointIdsList = None  # type: ignore[assignment,misc]

from fireflyframework_genai.vectorstores.base import BaseVectorStore
from fireflyframework_genai.vectorstores.types import SearchFilter, SearchResult, VectorDocument

logger = logging.getLogger(__name__)


class QdrantVectorStore(BaseVectorStore):
    """Qdrant-backed vector store.

    Parameters:
        collection_name: Qdrant collection name.
        url: Qdrant server URL. Defaults to ``"http://localhost:6333"``.
        api_key: Qdrant API key (for Qdrant Cloud).
        vector_size: Dimension of vectors. Required for collection creation.
        embedder: Optional embedder for auto-embedding.
    """

    def __init__(
        self,
        collection_name: str = "default",
        *,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        vector_size: int = 1536,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if AsyncQdrantClient is None:
            raise ImportError(
                "qdrant-client package is required for QdrantVectorStore. Install it with: pip install qdrant-client"
            )
        self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._collection_name = collection_name
        self._vector_size = vector_size

    async def _upsert(self, documents: list[VectorDocument], namespace: str) -> None:
        points = [
            PointStruct(  # type: ignore[misc]
                id=doc.id,
                vector=doc.embedding,
                payload={"text": doc.text, "_namespace": namespace, **doc.metadata},
            )
            for doc in documents
        ]
        await self._client.upsert(
            collection_name=self._collection_name,
            points=points,
        )

    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]:
        must_conditions = [FieldCondition(key="_namespace", match=MatchValue(value=namespace))]  # type: ignore[misc]
        if filters:
            for f in filters:
                if f.operator == "eq":
                    must_conditions.append(FieldCondition(key=f.field, match=MatchValue(value=f.value)))  # type: ignore[misc]

        results = await self._client.search(
            collection_name=self._collection_name,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=Filter(must=must_conditions),  # type: ignore[misc]
        )

        search_results = []
        for point in results:
            payload = dict(point.payload or {})
            text = payload.pop("text", "")
            payload.pop("_namespace", None)
            doc = VectorDocument(
                id=str(point.id),
                text=text,
                metadata=payload,
                namespace=namespace,
            )
            search_results.append(SearchResult(document=doc, score=point.score))
        return search_results

    async def _delete(self, ids: list[str], namespace: str) -> None:
        await self._client.delete(
            collection_name=self._collection_name,
            points_selector=PointIdsList(  # type: ignore[misc]
                points=ids,
            ),
        )
