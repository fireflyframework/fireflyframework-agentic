"""Tests for the Google embedding provider."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

from fireflyframework_agentic.embeddings.providers.google import GoogleEmbedder
from fireflyframework_agentic.embeddings.types import EmbeddingResult


class TestGoogleEmbedder:
    @patch("fireflyframework_agentic.embeddings.providers.google.genai_client")
    @patch("fireflyframework_agentic.embeddings.providers.google.genai")
    async def test_embed_batch(self, mock_genai, mock_genai_client):
        mock_genai.embed_content.return_value = {"embedding": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}

        embedder = GoogleEmbedder()
        result = await embedder.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert result.model == "models/text-embedding-004"

    @patch("fireflyframework_agentic.embeddings.providers.google.genai_client")
    @patch("fireflyframework_agentic.embeddings.providers.google.genai")
    async def test_embed_one(self, mock_genai, mock_genai_client):
        mock_genai.embed_content.return_value = {"embedding": [[0.1, 0.2, 0.3]]}

        embedder = GoogleEmbedder()
        vec = await embedder.embed_one("hello")

        assert isinstance(vec, list)
        assert len(vec) == 3

    @patch("fireflyframework_agentic.embeddings.providers.google.genai_client")
    @patch("fireflyframework_agentic.embeddings.providers.google.genai")
    def test_default_model(self, mock_genai, mock_genai_client):
        embedder = GoogleEmbedder()
        assert embedder.model == "models/text-embedding-004"

    @patch("fireflyframework_agentic.embeddings.providers.google.genai")
    @patch("fireflyframework_agentic.embeddings.providers.google.genai_client")
    def test_configure_with_api_key(self, mock_genai_client, mock_genai):
        GoogleEmbedder(api_key="test-key")
        mock_genai_client.configure.assert_called_once_with(api_key="test-key")


def test_missing_google_extra_import_contract():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
import importlib.abc
import sys

class MissingGoogleExtra(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'google.generativeai' or fullname.startswith('google.generativeai.'):
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, MissingGoogleExtra())
provider = importlib.import_module('fireflyframework_agentic.embeddings.providers.google')
assert provider.genai is None
assert provider.genai_client is None
try:
    provider.GoogleEmbedder(api_key='test-key')
except ImportError as exc:
    assert 'google-generativeai' in str(exc)
else:
    raise AssertionError('Missing optional SDK must reject provider construction')
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
