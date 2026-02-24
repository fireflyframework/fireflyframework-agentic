"""Registry for vector store instances."""

from __future__ import annotations

from fireflyframework_genai.vectorstores.base import VectorStoreProtocol


class VectorStoreRegistry:
    """Registry for named vector store instances."""

    def __init__(self) -> None:
        self._stores: dict[str, VectorStoreProtocol] = {}

    def register(self, name: str, store: VectorStoreProtocol) -> None:
        """Register a vector store under the given name."""
        self._stores[name] = store

    def get(self, name: str) -> VectorStoreProtocol:
        """Retrieve a registered vector store by name.

        Raises:
            KeyError: If no store is registered under the given name.
        """
        if name not in self._stores:
            raise KeyError(f"Vector store not found: {name!r}")
        return self._stores[name]

    def unregister(self, name: str) -> None:
        """Remove a vector store from the registry (no-op if not found)."""
        self._stores.pop(name, None)

    def list_names(self) -> list[str]:
        """Return all registered store names."""
        return list(self._stores.keys())
