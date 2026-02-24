"""Tests for the Azure OpenAI embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_genai.embeddings.providers.azure import AzureEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult


class TestAzureEmbedder:
    @patch("fireflyframework_genai.embeddings.providers.azure.AsyncAzureOpenAI")
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

        embedder = AzureEmbedder(
            model="text-embedding-ada-002",
            azure_endpoint="https://test.openai.azure.com",
            api_key="test-key",
        )
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "text-embedding-ada-002"

    @patch("fireflyframework_genai.embeddings.providers.azure.AsyncAzureOpenAI")
    async def test_embed_one(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2], index=0)]
        mock_response.usage = MagicMock(total_tokens=5)
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedder = AzureEmbedder(
            model="text-embedding-ada-002",
            azure_endpoint="https://test.openai.azure.com",
            api_key="test-key",
        )
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 2

    @patch("fireflyframework_genai.embeddings.providers.azure.AsyncAzureOpenAI")
    def test_model_name(self, mock_client_cls):
        embedder = AzureEmbedder(
            model="text-embedding-ada-002",
            azure_endpoint="https://test.openai.azure.com",
            api_key="test-key",
        )
        assert embedder.model == "text-embedding-ada-002"
