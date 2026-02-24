"""Embedding protocol and abstract base class.

The embeddings system uses a three-layer extensibility model:

1. :class:`EmbeddingProtocol` -- a ``typing.Protocol`` that any object can
   satisfy via duck typing.
2. :class:`BaseEmbedder` -- an abstract base class that provides auto-batching,
   retry logic, and logging out of the box.
3. Concrete provider implementations (OpenAI, Cohere, Google, etc.).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from fireflyframework_genai.config import get_config
from fireflyframework_genai.embeddings.types import EmbeddingResult, EmbeddingUsage
from fireflyframework_genai.exceptions import EmbeddingError

logger = logging.getLogger(__name__)


@runtime_checkable
class EmbeddingProtocol(Protocol):
    """Structural protocol satisfied by any object with embed/embed_one methods."""

    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult: ...

    async def embed_one(self, text: str, **kwargs: Any) -> list[float]: ...


class BaseEmbedder(ABC):
    """Abstract base class for embedding providers.

    Subclasses implement :meth:`_embed_batch` for a single batch of texts.
    The base class handles:
    - Auto-batching (splitting large lists into provider-sized batches)
    - Logging
    - Error wrapping

    Parameters:
        model: The model identifier (e.g. ``"text-embedding-3-small"``).
        dimensions: Output embedding dimensions (when the provider supports it).
    """

    def __init__(self, model: str, dimensions: int | None = None, **kwargs: Any) -> None:
        self._model = model
        self._dimensions = dimensions
        cfg = get_config()
        self._batch_size = kwargs.pop("batch_size", cfg.embedding_batch_size)
        self._max_retries = kwargs.pop("max_retries", cfg.embedding_max_retries)

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        """Embed a list of texts, auto-batching as needed."""
        if not texts:
            return EmbeddingResult(
                embeddings=[],
                model=self._model,
                usage=EmbeddingUsage(total_tokens=0),
                dimensions=self._dimensions or 0,
            )

        all_embeddings: list[list[float]] = []
        total_tokens = 0

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            try:
                batch_embeddings = await self._embed_batch(batch, **kwargs)
                all_embeddings.extend(batch_embeddings)
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError(f"Embedding failed for batch starting at index {i}: {exc}") from exc

        dims = len(all_embeddings[0]) if all_embeddings else (self._dimensions or 0)

        # Estimate tokens (~4 chars per token)
        total_tokens = sum(len(t) // 4 + 1 for t in texts)

        return EmbeddingResult(
            embeddings=all_embeddings,
            model=self._model,
            usage=EmbeddingUsage(total_tokens=total_tokens),
            dimensions=dims,
        )

    async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
        """Embed a single text and return its vector."""
        result = await self.embed([text], **kwargs)
        return result.embeddings[0]

    @abstractmethod
    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts. Implemented by each provider."""
        ...
