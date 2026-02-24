"""ChromaDB vector store backend."""

from __future__ import annotations

import logging
from typing import Any

try:
    import chromadb  # type: ignore[import-untyped]
except ImportError:
    chromadb = None  # type: ignore[assignment]

from fireflyframework_genai.vectorstores.base import BaseVectorStore
from fireflyframework_genai.vectorstores.types import SearchFilter, SearchResult, VectorDocument

logger = logging.getLogger(__name__)


class ChromaVectorStore(BaseVectorStore):
    """ChromaDB-backed vector store.

    Parameters:
        collection_name: Name of the ChromaDB collection.
        client: Optional pre-configured ChromaDB client. Creates an ephemeral one if not provided.
        embedder: Optional embedder for auto-embedding.
    """

    def __init__(
        self,
        collection_name: str = "default",
        *,
        client: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if chromadb is None:
            raise ImportError(
                "chromadb package is required for ChromaVectorStore. Install it with: pip install chromadb"
            )
        self._client = client or chromadb.Client()
        self._collection_name = collection_name
        self._collection = self._client.get_or_create_collection(name=collection_name)

    async def _upsert(self, documents: list[VectorDocument], namespace: str) -> None:
        ids = [doc.id for doc in documents]
        embeddings = [doc.embedding for doc in documents]
        texts = [doc.text for doc in documents]
        metadatas = [{**doc.metadata, "_namespace": namespace} for doc in documents]
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,  # type: ignore[arg-type]
            documents=texts,
            metadatas=metadatas,
        )

    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]:
        where = {"_namespace": namespace}
        if filters:
            for f in filters:
                if f.operator == "eq":
                    where[f.field] = f.value
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where if where else None,
        )
        search_results = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                doc = VectorDocument(
                    id=doc_id,
                    text=results["documents"][0][i] if results["documents"] else "",
                    metadata={k: v for k, v in (results["metadatas"][0][i] or {}).items() if k != "_namespace"},
                )
                score = 1.0 - (results["distances"][0][i] if results["distances"] else 0.0)
                search_results.append(SearchResult(document=doc, score=score))
        return search_results

    async def _delete(self, ids: list[str], namespace: str) -> None:
        self._collection.delete(ids=ids, where={"_namespace": namespace})
