"""Google (Generative AI) embedding provider."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

try:
    import google.generativeai as genai  # type: ignore[import-untyped]
except ImportError:
    genai = None  # type: ignore[assignment]

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import EmbeddingProviderError

logger = logging.getLogger(__name__)


class GoogleEmbedder(BaseEmbedder):
    """Google Generative AI embedding provider.

    Parameters:
        model: Google model. Defaults to ``"models/text-embedding-004"``.
        api_key: Google API key. Falls back to ``GOOGLE_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str = "models/text-embedding-004",
        dimensions: int | None = None,
        *,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions, **kwargs)
        if genai is None:
            raise ImportError(
                "The 'google-generativeai' package is required for GoogleEmbedder. "
                "Install it with: pip install google-generativeai"
            )
        if api_key:
            genai.configure(api_key=api_key)

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts via the Google Generative AI API."""
        try:
            result = await asyncio.to_thread(
                genai.embed_content,  # type: ignore[union-attr]
                model=self._model,
                content=texts,
            )
            return [list(e) for e in result["embedding"]]
        except Exception as exc:
            raise EmbeddingProviderError(f"Google embedding failed: {exc}") from exc
