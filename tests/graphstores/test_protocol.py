from __future__ import annotations

from typing import Any
from collections.abc import Sequence

from fireflyframework_agentic.graphstores import Edge, GraphStoreProtocol, Node


class _Stub:
    """Minimal protocol-conforming class for runtime check."""

    async def upsert_nodes(self, nodes: Sequence[Node]) -> None: ...
    async def upsert_edges(self, edges: Sequence[Edge]) -> None: ...
    async def delete_by_doc_id(self, doc_id: str) -> int: return 0
    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: return []
    async def close(self) -> None: ...


def test_stub_satisfies_protocol():
    assert isinstance(_Stub(), GraphStoreProtocol)
