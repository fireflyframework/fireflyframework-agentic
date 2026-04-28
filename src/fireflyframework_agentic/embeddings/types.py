"""Data models for embedding results and usage tracking."""

from __future__ import annotations

from pydantic import BaseModel


class EmbeddingUsage(BaseModel):
    """Token usage information from an embedding API call."""

    total_tokens: int


class EmbeddingResult(BaseModel):
    """Result of an embedding operation."""

    embeddings: list[list[float]]
    model: str
    usage: EmbeddingUsage
    dimensions: int
