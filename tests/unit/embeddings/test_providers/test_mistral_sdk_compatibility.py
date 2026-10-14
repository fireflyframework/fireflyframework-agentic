"""Mistral embeddings through the installed SDK and a local HTTP server."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from fireflyframework_agentic.exceptions import EmbeddingProviderError


@pytest.fixture
def mistral_endpoint():
    requests = []
    status = {"code": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), payload))
            body = (
                {
                    "id": "local-embedding",
                    "object": "list",
                    "model": "mistral-embed",
                    "usage": {"prompt_tokens": 2, "total_tokens": 2},
                    "data": [
                        {"object": "embedding", "index": i, "embedding": [float(i), 1.0]}
                        for i in range(len(payload["input"]))
                    ],
                }
                if status["code"] == 200
                else {"message": "invalid input", "type": "invalid_request_error"}
            )
            encoded = json.dumps(body).encode()
            self.send_response(status["code"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, status
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("texts", [["hello"], ["hello", "world"]])
async def test_installed_mistral_sdk_embedding_round_trip(mistral_endpoint, texts):
    pytest.importorskip("mistralai")
    from fireflyframework_agentic.embeddings.providers.mistral import MistralEmbedder

    url, requests, _ = mistral_endpoint
    embedder = MistralEmbedder(api_key="test-local-key")
    embedder._client.sdk_configuration.server_url = url
    try:
        result = await embedder.embed(texts)
        assert result.embeddings == ([[0.0, 1.0]] if len(texts) == 1 else [[0.0, 1.0], [1.0, 1.0]])
        assert result.model == "mistral-embed"
        assert result.dimensions == 2
        assert requests == [("/v1/embeddings", "Bearer test-local-key", {"model": "mistral-embed", "input": texts})]
    finally:
        await embedder._client.sdk_configuration.async_client.aclose()
        embedder._client.sdk_configuration.client.close()


async def test_installed_mistral_sdk_error_is_wrapped(mistral_endpoint):
    pytest.importorskip("mistralai")
    from fireflyframework_agentic.embeddings.providers.mistral import MistralEmbedder

    url, requests, status = mistral_endpoint
    status["code"] = 400
    embedder = MistralEmbedder(api_key="test-local-key")
    embedder._client.sdk_configuration.server_url = url
    try:
        with pytest.raises(EmbeddingProviderError, match="Mistral embedding failed") as error:
            await embedder.embed(["hello"])
        assert error.value.__cause__ is not None
        assert len(requests) == 1
    finally:
        await embedder._client.sdk_configuration.async_client.aclose()
        embedder._client.sdk_configuration.client.close()
