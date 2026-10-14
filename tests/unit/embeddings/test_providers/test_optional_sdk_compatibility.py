"""Provider SDK parsing with only the outbound request replaced."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("texts", [["first"], ["first", "second"]])
async def test_google_real_sdk_returns_one_vector_per_text(monkeypatch, texts):
    pytest.importorskip("google.generativeai")
    from google.generativeai import protos

    from fireflyframework_agentic.embeddings.providers.google import GoogleEmbedder

    sdk_embedding = importlib.import_module("google.generativeai.embedding")

    class LocalClient:
        def batch_embed_contents(self, request, **kwargs):
            assert [item.content.parts[0].text for item in request.requests] == texts
            assert request.model == "models/text-embedding-004"
            return protos.BatchEmbedContentsResponse(
                embeddings=[protos.ContentEmbedding(values=[float(i), 1.0]) for i in range(len(texts))]
            )

    monkeypatch.setattr(sdk_embedding, "get_default_generative_client", lambda: LocalClient())
    result = await GoogleEmbedder().embed(texts)
    assert result.embeddings == ([[0.0, 1.0]] if len(texts) == 1 else [[0.0, 1.0], [1.0, 1.0]])


async def test_voyage_real_client_parses_embeddings_without_network(monkeypatch):
    voyageai = pytest.importorskip("voyageai")
    from voyageai.api_resources.response import VoyageResponse

    from fireflyframework_agentic.embeddings.providers.voyage import VoyageEmbedder

    async def local_response(**kwargs):
        assert kwargs["input"] == ["first", "second"]
        assert kwargs["model"] == "voyage-3"
        return VoyageResponse.construct_from(
            {"data": [{"embedding": [0.0, 1.0]}, {"embedding": [1.0, 0.0]}], "usage": {"total_tokens": 2}}
        )

    monkeypatch.setattr(voyageai.Embedding, "acreate", local_response)
    result = await VoyageEmbedder(api_key="test-key").embed(["first", "second"])
    assert result.embeddings == [[0.0, 1.0], [1.0, 0.0]]
