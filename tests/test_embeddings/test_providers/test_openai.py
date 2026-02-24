"""Tests for the OpenAI embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_genai.embeddings.providers.openai import OpenAIEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult


class TestOpenAIEmbedder:
    @patch("fireflyframework_genai.embeddings.providers.openai.AsyncOpenAI")
    async def test_embed_batch(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1, 0.2, 0.3], index=0),
            MagicMock(embedding=[0.4, 0.5, 0.6], index=1),
        ]
        mock_response.usage = MagicMock(total_tokens=10)
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedder = OpenAIEmbedder(model="text-embedding-3-small")
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "text-embedding-3-small"

    @patch("fireflyframework_genai.embeddings.providers.openai.AsyncOpenAI")
    async def test_embed_one(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2], index=0)]
        mock_response.usage = MagicMock(total_tokens=5)
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedder = OpenAIEmbedder(model="text-embedding-3-small")
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 2

    @patch("fireflyframework_genai.embeddings.providers.openai.AsyncOpenAI")
    def test_default_model(self, mock_client_cls):
        embedder = OpenAIEmbedder()
        assert embedder.model == "text-embedding-3-small"
