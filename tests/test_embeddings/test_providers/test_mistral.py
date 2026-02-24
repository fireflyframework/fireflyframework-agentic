"""Tests for the Mistral embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_genai.embeddings.providers.mistral import MistralEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult


class TestMistralEmbedder:
    @patch("fireflyframework_genai.embeddings.providers.mistral.Mistral")
    async def test_embed_batch(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1, 0.2, 0.3]),
            MagicMock(embedding=[0.4, 0.5, 0.6]),
        ]
        mock_client.embeddings.create_async = AsyncMock(return_value=mock_response)

        embedder = MistralEmbedder()
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "mistral-embed"

    @patch("fireflyframework_genai.embeddings.providers.mistral.Mistral")
    async def test_embed_one(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        mock_client.embeddings.create_async = AsyncMock(return_value=mock_response)

        embedder = MistralEmbedder()
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 3

    @patch("fireflyframework_genai.embeddings.providers.mistral.Mistral")
    def test_default_model(self, mock_client_cls):
        embedder = MistralEmbedder()
        assert embedder.model == "mistral-embed"
