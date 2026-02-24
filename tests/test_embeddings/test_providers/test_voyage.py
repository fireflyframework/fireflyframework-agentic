"""Tests for the Voyage AI embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_genai.embeddings.providers.voyage import VoyageEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult


class TestVoyageEmbedder:
    @patch("fireflyframework_genai.embeddings.providers.voyage.voyageai")
    async def test_embed_batch(self, mock_voyageai):
        mock_client = MagicMock()
        mock_voyageai.AsyncClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.embed = AsyncMock(return_value=mock_response)

        embedder = VoyageEmbedder()
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "voyage-3"

    @patch("fireflyframework_genai.embeddings.providers.voyage.voyageai")
    async def test_embed_one(self, mock_voyageai):
        mock_client = MagicMock()
        mock_voyageai.AsyncClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.embeddings = [[0.1, 0.2, 0.3]]
        mock_client.embed = AsyncMock(return_value=mock_response)

        embedder = VoyageEmbedder()
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 3

    @patch("fireflyframework_genai.embeddings.providers.voyage.voyageai")
    def test_default_model(self, mock_voyageai):
        embedder = VoyageEmbedder()
        assert embedder.model == "voyage-3"
