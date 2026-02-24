"""Tests for the Google embedding provider."""

from __future__ import annotations

from unittest.mock import patch

from fireflyframework_genai.embeddings.providers.google import GoogleEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult


class TestGoogleEmbedder:
    @patch("fireflyframework_genai.embeddings.providers.google.genai")
    async def test_embed_batch(self, mock_genai):
        mock_genai.embed_content.return_value = {"embedding": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}

        embedder = GoogleEmbedder()
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "models/text-embedding-004"

    @patch("fireflyframework_genai.embeddings.providers.google.genai")
    async def test_embed_one(self, mock_genai):
        mock_genai.embed_content.return_value = {"embedding": [[0.1, 0.2, 0.3]]}

        embedder = GoogleEmbedder()
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 3

    @patch("fireflyframework_genai.embeddings.providers.google.genai")
    def test_default_model(self, mock_genai):
        embedder = GoogleEmbedder()
        assert embedder.model == "models/text-embedding-004"

    @patch("fireflyframework_genai.embeddings.providers.google.genai")
    def test_configure_with_api_key(self, mock_genai):
        GoogleEmbedder(api_key="test-key")
        mock_genai.configure.assert_called_once_with(api_key="test-key")
