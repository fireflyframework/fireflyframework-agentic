"""Tests for the tenant/workspace-scoped vector store layer."""

from __future__ import annotations

from typing import Any

import pytest

from fireflyframework_agentic.vectorstores.scoped import (
    ScopedVectorStore,
    TenantScopedVectorStore,
    parse_scope_namespace,
    scope_namespace,
)
from fireflyframework_agentic.vectorstores.types import SearchFilter, SearchResult, VectorDocument


class _FakeStore:
    """Minimal ``VectorStoreProtocol`` fake: a namespace-partitioned dict.

    Records the namespace seen by every call so tests can assert that the
    scoped wrapper folds ``(tenant_id, workspace_id)`` into the namespace.
    """

    def __init__(self) -> None:
        self.data: dict[str, dict[str, VectorDocument]] = {}
        self.calls: list[tuple[str, str, Any]] = []

    async def upsert(self, documents: list[VectorDocument], namespace: str = "default") -> None:
        self.calls.append(("upsert", namespace, None))
        self.data.setdefault(namespace, {})
        for d in documents:
            self.data[namespace][d.id] = d

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        namespace: str = "default",
        filters: list[SearchFilter] | None = None,
    ) -> list[SearchResult]:
        self.calls.append(("search", namespace, filters))
        docs = list(self.data.get(namespace, {}).values())[:top_k]
        return [SearchResult(document=d, score=1.0) for d in docs]

    async def search_text(
        self,
        query: str,
        top_k: int = 5,
        namespace: str = "default",
        filters: list[SearchFilter] | None = None,
    ) -> list[SearchResult]:
        raise NotImplementedError

    async def delete(self, ids: list[str], namespace: str = "default") -> None:
        self.calls.append(("delete", namespace, None))
        ns = self.data.get(namespace, {})
        for i in ids:
            ns.pop(i, None)


def test_scope_namespace_format() -> None:
    assert scope_namespace("acme", "main") == "t/acme/w/main"


@pytest.mark.parametrize(
    ("tenant", "workspace"),
    [("a/b", "main"), ("acme", "w/x"), ("", "main"), ("acme", ""), ("t/x", "w/y")],
)
def test_scope_namespace_rejects_unsafe_components(tenant: str, workspace: str) -> None:
    # Collision-freedom of the namespace depends on components never containing
    # '/' (and never being empty); enforce it where the namespace is built.
    with pytest.raises(ValueError):
        scope_namespace(tenant, workspace)


def test_parse_scope_namespace_roundtrip() -> None:
    assert parse_scope_namespace("t/acme/w/main") == ("acme", "main")
    tenant, workspace = "acme", "main"
    assert parse_scope_namespace(scope_namespace(tenant, workspace)) == (tenant, workspace)


@pytest.mark.parametrize("bad", ["not-a-scope", "t/acme", "w/main", "", "t//w/main"])
def test_parse_scope_namespace_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_scope_namespace(bad)


class TestTenantScopedVectorStore:
    async def test_upsert_requires_scope(self) -> None:
        store = TenantScopedVectorStore(_FakeStore())
        with pytest.raises(TypeError):
            await store.upsert([VectorDocument(id="1", text="x", embedding=[1.0])])  # type: ignore[call-arg]

    async def test_search_requires_scope(self) -> None:
        store = TenantScopedVectorStore(_FakeStore())
        with pytest.raises(TypeError):
            await store.search([1.0])  # type: ignore[call-arg]

    async def test_upsert_folds_scope_into_namespace_and_metadata(self) -> None:
        inner = _FakeStore()
        store = TenantScopedVectorStore(inner)
        await store.upsert(
            [VectorDocument(id="1", text="x", embedding=[1.0])],
            tenant_id="acme",
            workspace_id="main",
        )
        ns = scope_namespace("acme", "main")
        assert ns in inner.data
        doc = inner.data[ns]["1"]
        assert doc.namespace == ns
        assert doc.metadata["tenant_id"] == "acme"
        assert doc.metadata["workspace_id"] == "main"

    async def test_upsert_does_not_mutate_caller_documents(self) -> None:
        inner = _FakeStore()
        store = TenantScopedVectorStore(inner)
        original = VectorDocument(id="1", text="x", embedding=[1.0])
        await store.upsert([original], tenant_id="acme", workspace_id="main")
        assert original.namespace == "default"
        assert "tenant_id" not in original.metadata

    async def test_search_is_scope_isolated(self) -> None:
        inner = _FakeStore()
        store = TenantScopedVectorStore(inner)
        await store.upsert([VectorDocument(id="1", text="a", embedding=[1.0])], tenant_id="acme", workspace_id="main")
        await store.upsert([VectorDocument(id="2", text="b", embedding=[1.0])], tenant_id="other", workspace_id="main")
        mine = await store.search([1.0], tenant_id="acme", workspace_id="main")
        assert [r.document.id for r in mine] == ["1"]
        foreign = await store.search([1.0], tenant_id="nobody", workspace_id="main")
        assert foreign == []

    async def test_delete_is_scoped(self) -> None:
        inner = _FakeStore()
        store = TenantScopedVectorStore(inner)
        await store.upsert([VectorDocument(id="1", text="a", embedding=[1.0])], tenant_id="acme", workspace_id="main")
        await store.delete(["1"], tenant_id="acme", workspace_id="main")
        assert await store.search([1.0], tenant_id="acme", workspace_id="main") == []

    async def test_search_forwards_caller_filters(self) -> None:
        inner = _FakeStore()
        store = TenantScopedVectorStore(inner)
        flt = [SearchFilter(field="source_id", operator="eq", value="s1")]
        await store.search([1.0], tenant_id="acme", workspace_id="main", filters=flt)
        assert inner.calls[-1] == ("search", "t/acme/w/main", flt)

    async def test_initialise_and_close_delegate(self) -> None:
        class _LifecycleStore(_FakeStore):
            def __init__(self) -> None:
                super().__init__()
                self.initialised = False
                self.closed = False

            async def initialise(self) -> None:
                self.initialised = True

            async def close(self) -> None:
                self.closed = True

        inner = _LifecycleStore()
        store = TenantScopedVectorStore(inner)
        await store.initialise()
        await store.close()
        assert inner.initialised and inner.closed

    def test_satisfies_scoped_protocol(self) -> None:
        store = TenantScopedVectorStore(_FakeStore())
        assert isinstance(store, ScopedVectorStore)
