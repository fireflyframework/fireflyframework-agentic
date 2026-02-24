"""Tests for the Ollama embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_genai.embeddings.providers.ollama import OllamaEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult


class TestOllamaEmbedder:
    @patch("fireflyframework_genai.embeddings.providers.ollama.httpx")
    async def test_embed_batch(self, mock_httpx):
        mock_client = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        embedder = OllamaEmbedder()
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "nomic-embed-text"

    @patch("fireflyframework_genai.embeddings.providers.ollama.httpx")
    async def test_embed_one(self, mock_httpx):
        mock_client = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        embedder = OllamaEmbedder()
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 3

    @patch("fireflyframework_genai.embeddings.providers.ollama.httpx")
    def test_default_model(self, mock_httpx):
        embedder = OllamaEmbedder()
        assert embedder.model == "nomic-embed-text"
