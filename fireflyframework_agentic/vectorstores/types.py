"""Data models for vector documents, search results, and filters."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class VectorDocument(BaseModel):
    """A document with optional embedding for vector storage."""

    id: str
    text: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = {}
    namespace: str = "default"


class SearchResult(BaseModel):
    """A single search result with similarity score."""

    document: VectorDocument
    score: float


class SearchFilter(BaseModel):
    """Metadata filter for vector search."""

    field: str
    operator: Literal["eq", "ne", "gt", "lt", "gte", "lte", "in"]
    value: Any
