# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Resolve a ``<provider>:<model>`` spec to a framework embedder.

Mirrors flycanon's ``embedding_service._build_embedder``: one branch per
provider shipped by ``fireflyframework_agentic.embeddings``. Per-provider
imports are deferred so a spec that never touches a given provider doesn't
require its SDK to be installed.
"""

from __future__ import annotations

import os

from fireflyframework_agentic.embeddings.base import BaseEmbedder


def build_embedder(spec: str, *, dimensions: int | None = None, batch_size: int = 64) -> BaseEmbedder:
    """Build a framework embedder from a ``"<provider>:<model>"`` spec.

    Supported providers: openai, azure, cohere, google, mistral, voyage,
    bedrock, ollama. Raises ``ValueError`` on a malformed spec or unknown
    provider.
    """
    if ":" not in spec:
        raise ValueError(f"embedder spec must be '<provider>:<model>' (got {spec!r})")
    provider, _, model = spec.partition(":")
    p = provider.strip().lower()
    if p == "openai":
        from fireflyframework_agentic.embeddings.providers.openai import OpenAIEmbedder  # noqa: PLC0415

        return OpenAIEmbedder(model=model, dimensions=dimensions, batch_size=batch_size)
    if p in ("azure", "azure-openai"):
        from fireflyframework_agentic.embeddings.providers.azure import AzureEmbedder  # noqa: PLC0415

        return AzureEmbedder(
            model=model,
            dimensions=dimensions,
            batch_size=batch_size,
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        )
    if p == "cohere":
        from fireflyframework_agentic.embeddings.providers.cohere import CohereEmbedder  # noqa: PLC0415

        return CohereEmbedder(model=model, dimensions=dimensions, batch_size=batch_size)
    if p in ("google", "gemini"):
        from fireflyframework_agentic.embeddings.providers.google import GoogleEmbedder  # noqa: PLC0415

        return GoogleEmbedder(model=model, dimensions=dimensions, batch_size=batch_size)
    if p == "mistral":
        from fireflyframework_agentic.embeddings.providers.mistral import MistralEmbedder  # noqa: PLC0415

        return MistralEmbedder(model=model, dimensions=dimensions, batch_size=batch_size)
    if p == "voyage":
        from fireflyframework_agentic.embeddings.providers.voyage import VoyageEmbedder  # noqa: PLC0415

        return VoyageEmbedder(model=model, dimensions=dimensions, batch_size=batch_size)
    if p == "bedrock":
        from fireflyframework_agentic.embeddings.providers.bedrock import BedrockEmbedder  # noqa: PLC0415

        return BedrockEmbedder(model=model, dimensions=dimensions, batch_size=batch_size)
    if p == "ollama":
        from fireflyframework_agentic.embeddings.providers.ollama import OllamaEmbedder  # noqa: PLC0415

        base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return OllamaEmbedder(model=model, dimensions=dimensions, base_url=base_url, batch_size=batch_size)
    raise ValueError(
        f"unknown embedding provider {provider!r}; supported: "
        "openai, azure, cohere, google, mistral, voyage, bedrock, ollama"
    )
