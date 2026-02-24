"""Registry for embedder instances."""

from __future__ import annotations

from fireflyframework_genai.embeddings.base import EmbeddingProtocol


class EmbedderRegistry:
    """Registry for named embedder instances."""

    def __init__(self) -> None:
        self._embedders: dict[str, EmbeddingProtocol] = {}

    def register(self, name: str, embedder: EmbeddingProtocol) -> None:
        self._embedders[name] = embedder

    def get(self, name: str) -> EmbeddingProtocol:
        if name not in self._embedders:
            raise KeyError(f"Embedder not found: {name!r}")
        return self._embedders[name]

    def unregister(self, name: str) -> None:
        self._embedders.pop(name, None)

    def list_names(self) -> list[str]:
        return list(self._embedders.keys())
