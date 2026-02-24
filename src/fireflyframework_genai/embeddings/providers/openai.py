"""OpenAI embedding provider."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import EmbeddingProviderError

logger = logging.getLogger(__name__)


class OpenAIEmbedder(BaseEmbedder):
    """Embedding provider using OpenAI's API.

    Supports models: text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002.

    Parameters:
        model: OpenAI model name. Defaults to ``"text-embedding-3-small"``.
        dimensions: Output dimensions (supported by text-embedding-3-*).
        api_key: OpenAI API key. Falls back to ``OPENAI_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int | None = None,
        *,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions, **kwargs)
        self._client = AsyncOpenAI(api_key=api_key)

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts via the OpenAI API."""
        try:
            params: dict[str, Any] = {"input": texts, "model": self._model}
            if self._dimensions is not None:
                params["dimensions"] = self._dimensions
            response = await self._client.embeddings.create(**params)
            # Sort by index to maintain order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in sorted_data]
        except Exception as exc:
            raise EmbeddingProviderError(f"OpenAI embedding failed: {exc}") from exc
