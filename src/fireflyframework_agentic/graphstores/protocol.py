# Copyright 2026 Firefly Software Solutions Inc
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

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from fireflyframework_agentic.graphstores.types import Edge, Node


@runtime_checkable
class GraphStoreProtocol(Protocol):
    """Async protocol for property-graph storage.

    Backends must accept upserts of Nodes and Edges, support cascading
    delete-by-document, expose an SQL (or Cypher-ish DSL) query surface,
    and clean up cleanly on close.
    """

    async def upsert_nodes(self, nodes: Sequence[Node]) -> None: ...

    async def upsert_edges(self, edges: Sequence[Edge]) -> None: ...

    async def delete_by_doc_id(self, doc_id: str) -> int:
        """Delete every node, edge, and provenance record carrying this
        ``source_doc_id``. Returns the total rows affected (sum across
        nodes + edges; junction rows excluded).
        """
        ...

    async def query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    async def close(self) -> None: ...
