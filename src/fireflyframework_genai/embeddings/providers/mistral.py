"""Mistral embedding provider."""

from __future__ import annotations

import logging
from typing import Any

try:
    from mistralai import Mistral
except ImportError:
    Mistral = None  # type: ignore[assignment,misc]

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import EmbeddingProviderError

logger = logging.getLogger(__name__)


class MistralEmbedder(BaseEmbedder):
    """Mistral AI embedding provider.

    Parameters:
        model: Mistral model. Defaults to ``"mistral-embed"``.
        api_key: Mistral API key. Falls back to ``MISTRAL_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str = "mistral-embed",
        dimensions: int | None = None,
        *,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions, **kwargs)
        if Mistral is None:
            raise ImportError(
                "The 'mistralai' package is required for MistralEmbedder. Install it with: pip install mistralai"
            )
        self._client = Mistral(api_key=api_key)

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts via the Mistral API."""
        try:
            response = await self._client.embeddings.create_async(
                model=self._model,
                inputs=texts,
            )
            return [list(item.embedding) for item in response.data if item.embedding is not None]
        except Exception as exc:
            raise EmbeddingProviderError(f"Mistral embedding failed: {exc}") from exc
