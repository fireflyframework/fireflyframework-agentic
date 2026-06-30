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

"""Unit tests for evaluation.embedder.build_embedder."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.embeddings.providers.ollama import OllamaEmbedder
from fireflyframework_agentic.evaluation import build_embedder


def test_build_embedder_ollama_returns_framework_embedder():
    embedder = build_embedder("ollama:nomic-embed-text")
    assert isinstance(embedder, OllamaEmbedder)
    assert embedder.model == "nomic-embed-text"


def test_build_embedder_honours_ollama_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://example:1234")
    embedder = build_embedder("ollama:nomic-embed-text")
    assert embedder._base_url == "http://example:1234"


def test_build_embedder_requires_provider_prefix():
    with pytest.raises(ValueError, match="<provider>:<model>"):
        build_embedder("nomic-embed-text")


def test_build_embedder_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unknown embedding provider"):
        build_embedder("bogus:model")
