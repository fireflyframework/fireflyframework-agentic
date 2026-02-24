"""Tests for the AWS Bedrock embedding provider."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

from fireflyframework_genai.embeddings.providers.bedrock import BedrockEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult


class TestBedrockEmbedder:
    @patch("fireflyframework_genai.embeddings.providers.bedrock.boto3")
    async def test_embed_batch(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        # Simulate two invoke_model calls (one per text)
        def make_response(embedding):
            body = io.BytesIO(json.dumps({"embedding": embedding}).encode())
            return {"body": body}

        mock_client.invoke_model.side_effect = [
            make_response([0.1, 0.2, 0.3]),
            make_response([0.4, 0.5, 0.6]),
        ]

        embedder = BedrockEmbedder()
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "amazon.titan-embed-text-v2:0"

    @patch("fireflyframework_genai.embeddings.providers.bedrock.boto3")
    async def test_embed_one(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        body = io.BytesIO(json.dumps({"embedding": [0.1, 0.2, 0.3]}).encode())
        mock_client.invoke_model.return_value = {"body": body}

        embedder = BedrockEmbedder()
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 3

    @patch("fireflyframework_genai.embeddings.providers.bedrock.boto3")
    def test_default_model(self, mock_boto3):
        embedder = BedrockEmbedder()
        assert embedder.model == "amazon.titan-embed-text-v2:0"
