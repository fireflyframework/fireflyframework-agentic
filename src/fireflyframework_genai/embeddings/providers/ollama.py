"""Ollama (local) embedding provider."""

from __future__ import annotations

import logging
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import EmbeddingProviderError

logger = logging.getLogger(__name__)


class OllamaEmbedder(BaseEmbedder):
    """Ollama local embedding provider via HTTP API.

    Parameters:
        model: Ollama model. Defaults to ``"nomic-embed-text"``.
        base_url: Ollama server URL. Defaults to ``"http://localhost:11434"``.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        dimensions: int | None = None,
        *,
        base_url: str = "http://localhost:11434",
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions, **kwargs)
        if httpx is None:
            raise ImportError("The 'httpx' package is required for OllamaEmbedder. Install it with: pip install httpx")
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts via the Ollama HTTP API."""
        try:
            response = await self._client.post(
                "/api/embed",
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()
            return [list(e) for e in data["embeddings"]]
        except Exception as exc:
            raise EmbeddingProviderError(f"Ollama embedding failed: {exc}") from exc
