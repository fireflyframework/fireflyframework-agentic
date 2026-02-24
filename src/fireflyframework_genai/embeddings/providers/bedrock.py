"""AWS Bedrock embedding provider."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore[assignment]

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.exceptions import EmbeddingProviderError

logger = logging.getLogger(__name__)


class BedrockEmbedder(BaseEmbedder):
    """AWS Bedrock embedding provider.

    Parameters:
        model: Bedrock model ID. Defaults to ``"amazon.titan-embed-text-v2:0"``.
        region: AWS region. Defaults to ``"us-east-1"``.
    """

    def __init__(
        self,
        model: str = "amazon.titan-embed-text-v2:0",
        dimensions: int | None = None,
        *,
        region: str = "us-east-1",
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions, **kwargs)
        if boto3 is None:
            raise ImportError("The 'boto3' package is required for BedrockEmbedder. Install it with: pip install boto3")
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a single batch of texts via the AWS Bedrock API."""
        try:
            embeddings = []
            for text in texts:
                body = json.dumps({"inputText": text})
                response = await asyncio.to_thread(
                    self._client.invoke_model,
                    modelId=self._model,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                result = json.loads(response["body"].read())
                embeddings.append(list(result["embedding"]))
            return embeddings
        except Exception as exc:
            raise EmbeddingProviderError(f"Bedrock embedding failed: {exc}") from exc
