"""Tenant/workspace-scoped vector store layer.

The :class:`~fireflyframework_agentic.vectorstores.base.VectorStoreProtocol`
is deliberately single-namespace: a store partitions documents by one opaque
``namespace`` string. Multi-tenant applications need stronger guarantees --
every read and write must be confined to a ``(tenant_id, workspace_id)`` scope,
and forgetting the scope must fail loudly rather than silently leak across
tenants.

This module adds that guarantee *on top of* the existing port, without changing
it:

- :func:`scope_namespace` / :func:`parse_scope_namespace` encode a scope as the
  canonical ``"t/<tenant_id>/w/<workspace_id>"`` namespace string.
- :class:`ScopedVectorStore` is the explicit, fail-loud contract: ``tenant_id``
  and ``workspace_id`` are required keyword-only arguments.
- :class:`TenantScopedVectorStore` wraps **any** ``VectorStoreProtocol`` backend
  (in-memory, pgvector, Qdrant, Chroma, ...) and folds the scope into the
  namespace -- one wrapper makes every backend multi-tenant. Isolation is keyed
  on the namespace, which every backend indexes/filters natively; the scope is
  also stamped onto document metadata as defense-in-depth and for diagnostics.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from fireflyframework_agentic.vectorstores.base import VectorStoreProtocol
from fireflyframework_agentic.vectorstores.types import SearchFilter, SearchResult, VectorDocument

logger = logging.getLogger(__name__)


def scope_namespace(tenant_id: str, workspace_id: str) -> str:
    """Return the canonical ``"t/<tenant_id>/w/<workspace_id>"`` namespace.

    The namespace is the authoritative isolation key: it is unique per scope and
    natively indexed/filtered by every backend, so confining reads and writes to
    it is sufficient for tenant isolation.

    Collision-freedom requires the components to be non-empty and to contain no
    ``/`` (otherwise distinct scopes could encode to the same namespace), so this
    validates them where the namespace is built rather than trusting callers.

    Raises:
        ValueError: If either component is empty or contains ``/``.
    """
    for label, value in (("tenant_id", tenant_id), ("workspace_id", workspace_id)):
        if not value or "/" in value:
            raise ValueError(f"invalid {label} for scope namespace: {value!r} (must be non-empty, no '/')")
    return f"t/{tenant_id}/w/{workspace_id}"


def parse_scope_namespace(namespace: str) -> tuple[str, str]:
    """Inverse of :func:`scope_namespace`.

    Returns:
        The ``(tenant_id, workspace_id)`` tuple encoded in *namespace*.

    Raises:
        ValueError: If *namespace* is not a ``"t/<tenant>/w/<workspace>"`` string
            with non-empty components.
    """
    parts = namespace.split("/")
    if len(parts) != 4 or parts[0] != "t" or parts[2] != "w" or not parts[1] or not parts[3]:
        raise ValueError(f"not a scope namespace: {namespace!r}; expected 't/<tenant_id>/w/<workspace_id>'")
    return parts[1], parts[3]


@runtime_checkable
class ScopedVectorStore(Protocol):
    """Vector store contract with mandatory tenant/workspace isolation.

    ``tenant_id`` and ``workspace_id`` are required keyword-only arguments on
    every data operation, so an implementation that omits them fails at the type
    level and a caller that forgets them fails with ``TypeError`` -- isolation
    can never be lost silently.
    """

    async def upsert(self, documents: list[VectorDocument], *, tenant_id: str, workspace_id: str) -> None: ...

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        *,
        tenant_id: str,
        workspace_id: str,
        filters: list[SearchFilter] | None = None,
    ) -> list[SearchResult]: ...

    async def delete(self, ids: list[str], *, tenant_id: str, workspace_id: str) -> None: ...

    async def initialise(self) -> None: ...

    async def close(self) -> None: ...


class TenantScopedVectorStore:
    """Wrap any :class:`VectorStoreProtocol` with tenant/workspace isolation.

    Folds ``(tenant_id, workspace_id)`` into the canonical scope namespace and
    delegates to the wrapped, namespace-based store. On ``upsert`` it copies each
    document (never mutating the caller's objects), sets the document namespace,
    and stamps ``tenant_id`` / ``workspace_id`` onto its metadata.

    Parameters:
        inner: The backend store to wrap (in-memory, pgvector, Qdrant, ...).
        stamp_metadata: When ``True`` (default), stamp the scope onto each
            document's metadata for defense-in-depth and diagnostics.
    """

    def __init__(self, inner: VectorStoreProtocol, *, stamp_metadata: bool = True) -> None:
        self._inner = inner
        self._stamp_metadata = stamp_metadata

    async def upsert(self, documents: list[VectorDocument], *, tenant_id: str, workspace_id: str) -> None:
        namespace = scope_namespace(tenant_id, workspace_id)
        scoped_docs = [self._scope_document(doc, tenant_id, workspace_id, namespace) for doc in documents]
        await self._inner.upsert(scoped_docs, namespace=namespace)

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        *,
        tenant_id: str,
        workspace_id: str,
        filters: list[SearchFilter] | None = None,
    ) -> list[SearchResult]:
        namespace = scope_namespace(tenant_id, workspace_id)
        return await self._inner.search(
            query_embedding,
            top_k=top_k,
            namespace=namespace,
            filters=filters,
        )

    async def delete(self, ids: list[str], *, tenant_id: str, workspace_id: str) -> None:
        namespace = scope_namespace(tenant_id, workspace_id)
        await self._inner.delete(ids, namespace=namespace)

    async def initialise(self) -> None:
        """Initialise the wrapped store if it exposes a lifecycle hook."""
        init: Any = getattr(self._inner, "initialise", None) or getattr(self._inner, "initialize", None)
        if init is not None:
            await init()

    async def close(self) -> None:
        """Close the wrapped store if it exposes a ``close`` hook."""
        close_fn: Any = getattr(self._inner, "close", None)
        if close_fn is not None:
            await close_fn()

    def _scope_document(self, doc: VectorDocument, tenant_id: str, workspace_id: str, namespace: str) -> VectorDocument:
        metadata = dict(doc.metadata)
        if self._stamp_metadata:
            metadata["tenant_id"] = tenant_id
            metadata["workspace_id"] = workspace_id
        return doc.model_copy(update={"namespace": namespace, "metadata": metadata})
