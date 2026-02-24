"""Vector store protocol and abstract base class.

The vector store system uses a three-layer extensibility model:

1. :class:`VectorStoreProtocol` -- duck-typed protocol.
2. :class:`BaseVectorStore` -- abstract base with auto-embedding and search_text.
3. Concrete backends (in-memory, ChromaDB, Pinecone, Qdrant).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from fireflyframework_genai.embeddings.base import EmbeddingProtocol
from fireflyframework_genai.exceptions import VectorStoreError
from fireflyframework_genai.vectorstores.types import SearchFilter, SearchResult, VectorDocument

logger = logging.getLogger(__name__)


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Structural protocol for vector stores."""

    async def upsert(self, documents: list[VectorDocument], namespace: str = "default") -> None: ...

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        namespace: str = "default",
        filters: list[SearchFilter] | None = None,
    ) -> list[SearchResult]: ...

    async def search_text(
        self,
        query: str,
        top_k: int = 5,
        namespace: str = "default",
        filters: list[SearchFilter] | None = None,
    ) -> list[SearchResult]: ...

    async def delete(self, ids: list[str], namespace: str = "default") -> None: ...


class BaseVectorStore(ABC):
    """Abstract base class for vector store backends.

    Subclasses implement ``_upsert``, ``_search``, and ``_delete``.
    The base class handles:
    - Auto-embedding documents that lack embeddings (if an embedder is set)
    - ``search_text`` convenience method
    - Error wrapping and logging

    Parameters:
        embedder: Optional embedder for auto-embedding on upsert and search_text.
    """

    def __init__(self, embedder: EmbeddingProtocol | None = None, **kwargs: Any) -> None:
        self._embedder = embedder

    async def upsert(self, documents: list[VectorDocument], namespace: str = "default") -> None:
        """Upsert documents, auto-embedding any that lack embeddings."""
        needs_embedding = [d for d in documents if d.embedding is None]
        if needs_embedding:
            if self._embedder is None:
                raise VectorStoreError(
                    f"{len(needs_embedding)} document(s) have no embedding and no embedder is configured."
                )
            texts = [d.text for d in needs_embedding]
            result = await self._embedder.embed(texts)
            for doc, emb in zip(needs_embedding, result.embeddings, strict=True):
                doc.embedding = emb

        try:
            await self._upsert(documents, namespace)
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(f"Upsert failed: {exc}") from exc

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        namespace: str = "default",
        filters: list[SearchFilter] | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors."""
        try:
            return await self._search(query_embedding, top_k, namespace, filters)
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(f"Search failed: {exc}") from exc

    async def search_text(
        self,
        query: str,
        top_k: int = 5,
        namespace: str = "default",
        filters: list[SearchFilter] | None = None,
    ) -> list[SearchResult]:
        """Convenience: embed query text and search."""
        if self._embedder is None:
            raise VectorStoreError("search_text requires an embedder. Pass one to the constructor.")
        query_embedding = await self._embedder.embed_one(query)
        return await self.search(query_embedding, top_k, namespace, filters)

    async def delete(self, ids: list[str], namespace: str = "default") -> None:
        """Delete documents by ID."""
        try:
            await self._delete(ids, namespace)
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(f"Delete failed: {exc}") from exc

    @abstractmethod
    async def _upsert(self, documents: list[VectorDocument], namespace: str) -> None: ...

    @abstractmethod
    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]: ...

    @abstractmethod
    async def _delete(self, ids: list[str], namespace: str) -> None: ...
