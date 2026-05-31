"""Pluggable vector storage and retrieval backends."""

from fireflyframework_agentic.vectorstores.base import BaseVectorStore, VectorStoreProtocol
from fireflyframework_agentic.vectorstores.chroma_store import ChromaVectorStore
from fireflyframework_agentic.vectorstores.memory_store import InMemoryVectorStore
from fireflyframework_agentic.vectorstores.pgvector_store import PgVectorVectorStore
from fireflyframework_agentic.vectorstores.pinecone_store import PineconeVectorStore
from fireflyframework_agentic.vectorstores.qdrant_store import QdrantVectorStore
from fireflyframework_agentic.vectorstores.registry import VectorStoreRegistry
from fireflyframework_agentic.vectorstores.scoped import (
    ScopedVectorStore,
    TenantScopedVectorStore,
    parse_scope_namespace,
    scope_namespace,
)
from fireflyframework_agentic.vectorstores.sqlite_vec_store import SqliteVecVectorStore
from fireflyframework_agentic.vectorstores.types import SearchFilter, SearchResult, VectorDocument

__all__ = [
    "BaseVectorStore",
    "ChromaVectorStore",
    "InMemoryVectorStore",
    "PgVectorVectorStore",
    "PineconeVectorStore",
    "QdrantVectorStore",
    "ScopedVectorStore",
    "SearchFilter",
    "SearchResult",
    "SqliteVecVectorStore",
    "TenantScopedVectorStore",
    "VectorDocument",
    "VectorStoreProtocol",
    "VectorStoreRegistry",
    "parse_scope_namespace",
    "scope_namespace",
]
