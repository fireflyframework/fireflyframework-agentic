"""Tests for the Cohere embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_genai.embeddings.providers.cohere import CohereEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult


class TestCohereEmbedder:
    @patch("fireflyframework_genai.embeddings.providers.cohere.AsyncCohere")
    async def test_embed_batch(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.embeddings = MagicMock()
        mock_response.embeddings.float_ = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.embed = AsyncMock(return_value=mock_response)

        embedder = CohereEmbedder()
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "embed-english-v3.0"

    @patch("fireflyframework_genai.embeddings.providers.cohere.AsyncCohere")
    async def test_embed_one(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.embeddings = MagicMock()
        mock_response.embeddings.float_ = [[0.1, 0.2, 0.3]]
        mock_client.embed = AsyncMock(return_value=mock_response)

        embedder = CohereEmbedder()
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 3

    @patch("fireflyframework_genai.embeddings.providers.cohere.AsyncCohere")
    def test_default_model(self, mock_client_cls):
        embedder = CohereEmbedder()
        assert embedder.model == "embed-english-v3.0"
