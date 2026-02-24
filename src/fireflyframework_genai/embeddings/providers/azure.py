"""Azure OpenAI embedding provider."""

from __future__ import annotations

import logging
from typing import Any

try:
    from openai import AsyncAzureOpenAI
except ImportError:
    AsyncAzureOpenAI = None  # type: ignore[assignment,misc]

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import EmbeddingProviderError

logger = logging.getLogger(__name__)


class AzureEmbedder(BaseEmbedder):
    """Azure OpenAI embedding provider.

    Parameters:
        model: Deployment name. Required.
        azure_endpoint: Azure endpoint URL. Required.
        api_version: API version. Defaults to ``"2024-02-01"``.
        api_key: Azure API key. Falls back to ``AZURE_OPENAI_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str,
        dimensions: int | None = None,
        *,
        azure_endpoint: str,
        api_version: str = "2024-02-01",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions, **kwargs)
        if AsyncAzureOpenAI is None:
            raise ImportError("The 'openai' package is required for AzureEmbedder. Install it with: pip install openai")
        self._client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            api_key=api_key,
        )

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts via the Azure OpenAI API."""
        try:
            params: dict[str, Any] = {"input": texts, "model": self._model}
            if self._dimensions is not None:
                params["dimensions"] = self._dimensions
            response = await self._client.embeddings.create(**params)
            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in sorted_data]
        except Exception as exc:
            raise EmbeddingProviderError(f"Azure embedding failed: {exc}") from exc
