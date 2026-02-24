"""Embedding generation: protocol, base class, providers, and similarity utilities."""

from fireflyframework_genai.embeddings.base import BaseEmbedder, EmbeddingProtocol
from fireflyframework_genai.embeddings.registry import EmbedderRegistry
from fireflyframework_genai.embeddings.similarity import (
    cosine_similarity,
    dot_product,
    euclidean_distance,
)
from fireflyframework_genai.embeddings.types import EmbeddingResult, EmbeddingUsage

__all__ = [
    "BaseEmbedder",
    "EmbedderRegistry",
    "EmbeddingProtocol",
    "EmbeddingResult",
    "EmbeddingUsage",
    "cosine_similarity",
    "dot_product",
    "euclidean_distance",
]
