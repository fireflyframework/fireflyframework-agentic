"""Voyage AI embedding provider."""

from __future__ import annotations

import logging
from typing import Any

try:
    import voyageai  # type: ignore[import-untyped]
except ImportError:
    voyageai = None  # type: ignore[assignment]

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import EmbeddingProviderError

logger = logging.getLogger(__name__)


class VoyageEmbedder(BaseEmbedder):
    """Voyage AI embedding provider (Anthropic ecosystem).

    Parameters:
        model: Voyage model. Defaults to ``"voyage-3"``.
        api_key: Voyage API key. Falls back to ``VOYAGE_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str = "voyage-3",
        dimensions: int | None = None,
        *,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions, **kwargs)
        if voyageai is None:
            raise ImportError(
                "The 'voyageai' package is required for VoyageEmbedder. Install it with: pip install voyageai"
            )
        self._client = voyageai.AsyncClient(api_key=api_key)

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts via the Voyage AI API."""
        try:
            response = await self._client.embed(
                texts=texts,
                model=self._model,
            )
            return [list(e) for e in response.embeddings]
        except Exception as exc:
            raise EmbeddingProviderError(f"Voyage embedding failed: {exc}") from exc
