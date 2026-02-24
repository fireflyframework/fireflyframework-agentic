"""Cohere embedding provider."""

from __future__ import annotations

import logging
from typing import Any

try:
    from cohere import AsyncClientV2 as AsyncCohere
except ImportError:
    AsyncCohere = None  # type: ignore[assignment,misc]

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import EmbeddingProviderError

logger = logging.getLogger(__name__)


class CohereEmbedder(BaseEmbedder):
    """Cohere embed API.

    Parameters:
        model: Cohere model. Defaults to ``"embed-english-v3.0"``.
        input_type: ``"search_document"`` or ``"search_query"``.
        api_key: Cohere API key. Falls back to ``CO_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str = "embed-english-v3.0",
        dimensions: int | None = None,
        *,
        input_type: str = "search_document",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions, **kwargs)
        if AsyncCohere is None:
            raise ImportError(
                "The 'cohere' package is required for CohereEmbedder. Install it with: pip install cohere"
            )
        self._input_type = input_type
        self._client = AsyncCohere(api_key=api_key)

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts via the Cohere API."""
        try:
            input_type = kwargs.pop("input_type", self._input_type)
            response = await self._client.embed(
                texts=texts,
                model=self._model,
                input_type=input_type,
                embedding_types=["float"],
            )
            embeddings = response.embeddings
            if embeddings is None or embeddings.float_ is None:
                return []
            return [list(e) for e in embeddings.float_]
        except Exception as exc:
            raise EmbeddingProviderError(f"Cohere embedding failed: {exc}") from exc
