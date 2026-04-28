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

"""Directed Acyclic Graph (DAG) model for pipeline topology.

:class:`DAG` holds :class:`DAGNode` and :class:`DAGEdge` objects, validates
acyclicity, computes topological sort, and identifies independent execution
levels for parallel scheduling.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError


class FailureStrategy(StrEnum):
    """How the pipeline engine should behave when a node fails.

    Attributes:
        PROPAGATE: Mark the node as failed and continue executing
            downstream nodes (they receive ``None`` inputs).  This is
            the legacy behaviour.
        SKIP_DOWNSTREAM: Mark the node as failed and automatically
            skip all transitive downstream dependents.
        FAIL_PIPELINE: Abort the entire pipeline immediately.
    """

    PROPAGATE = "propagate"
    SKIP_DOWNSTREAM = "skip_downstream"
    FAIL_PIPELINE = "fail_pipeline"


class DAGEdge(BaseModel):
    """Directed edge from *source* to *target* in the DAG.

    Attributes:
        source: ID of the upstream node.
        target: ID of the downstream node.
        output_key: Which output from the source to pass (default ``"output"``).
        input_key: Which input key on the target receives the value (default ``"input"``).
    """

    source: str
    target: str
    output_key: str = "output"
    input_key: str = "input"


class DAGNode(BaseModel):
    """A node in the pipeline DAG.

    Attributes:
        node_id: Unique identifier for this node.
        step: The step executor that does the actual work.
            Stored as ``Any`` because the concrete type is in ``steps.py``.
        condition: Optional predicate ``(context) -> bool`` that gates execution.
        retry_max: Maximum retries for this node (0 = no retries).
        timeout_seconds: Per-node timeout (0 = no timeout).
        failure_strategy: How to handle failure of this node.
        backoff_factor: Multiplier for exponential backoff between retries
            (seconds).  The delay for attempt *n* is
            ``backoff_factor * 2^(n-1)`` plus random jitter.
    """

    model_config = {"arbitrary_types_allowed": True}

    node_id: str
    step: Any  # StepExecutor — kept as Any to avoid circular import
    condition: Callable[..., bool] | None = None
    retry_max: int = 0
    timeout_seconds: float = 0
    failure_strategy: FailureStrategy = FailureStrategy.SKIP_DOWNSTREAM
    backoff_factor: float = 1.0


class DAG:
    """Directed Acyclic Graph container with topological scheduling.

    Parameters:
        name: A human-readable name for the pipeline.
    """

    def __init__(self, name: str = "pipeline") -> None:
        self._name = name
        self._nodes: dict[str, DAGNode] = {}
        self._edges: list[DAGEdge] = []
        # Adjacency and reverse adjacency for topo-sort
        self._adj: dict[str, list[str]] = defaultdict(list)
        self._in_degree: dict[str, int] = defaultdict(int)

    @property
    def name(self) -> str:
        return self._name

    @property
    def nodes(self) -> dict[str, DAGNode]:
        return dict(self._nodes)

    @property
    def edges(self) -> list[DAGEdge]:
        return list(self._edges)

    # -- Mutation ----------------------------------------------------------

    def add_node(self, node: DAGNode) -> None:
        """Register a node in the DAG."""
        if node.node_id in self._nodes:
            raise PipelineError(f"Duplicate node ID '{node.node_id}'")
        self._nodes[node.node_id] = node
        self._in_degree.setdefault(node.node_id, 0)

    def add_edge(self, edge: DAGEdge) -> None:
        """Add a directed edge.  Validates that both endpoints exist."""
        if edge.source not in self._nodes:
            raise PipelineError(f"Edge source '{edge.source}' not found in DAG")
        if edge.target not in self._nodes:
            raise PipelineError(f"Edge target '{edge.target}' not found in DAG")
        self._edges.append(edge)
        self._adj[edge.source].append(edge.target)
        self._in_degree[edge.target] = self._in_degree.get(edge.target, 0) + 1
        # Incremental cycle check
        if self._has_cycle():
            # Rollback
            self._edges.pop()
            self._adj[edge.source].pop()
            self._in_degree[edge.target] -= 1
            raise PipelineError(f"Adding edge {edge.source} -> {edge.target} would create a cycle")

    # -- Query -------------------------------------------------------------

    def topological_sort(self) -> list[str]:
        """Return node IDs in topological order (Kahn's algorithm)."""
        in_deg = dict(self._in_degree)
        for nid in self._nodes:
            in_deg.setdefault(nid, 0)
        queue: deque[str] = deque(nid for nid, d in in_deg.items() if d == 0)
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbour in self._adj.get(node, []):
                in_deg[neighbour] -= 1
                if in_deg[neighbour] == 0:
                    queue.append(neighbour)

        if len(order) != len(self._nodes):
            raise PipelineError("DAG contains a cycle (should not reach here)")
        return order

    def execution_levels(self) -> list[list[str]]:
        """Group nodes into levels for parallel execution.

        Nodes at the same level have no inter-dependencies and can be
        executed concurrently.
        """
        in_deg = dict(self._in_degree)
        for nid in self._nodes:
            in_deg.setdefault(nid, 0)
        queue: deque[str] = deque(nid for nid, d in in_deg.items() if d == 0)
        levels: list[list[str]] = []

        while queue:
            level = list(queue)
            levels.append(level)
            next_queue: deque[str] = deque()
            for node in level:
                for neighbour in self._adj.get(node, []):
                    in_deg[neighbour] -= 1
                    if in_deg[neighbour] == 0:
                        next_queue.append(neighbour)
            queue = next_queue

        return levels

    def predecessors(self, node_id: str) -> list[str]:
        """Return IDs of all direct predecessors of *node_id*."""
        return [e.source for e in self._edges if e.target == node_id]

    def successors(self, node_id: str) -> list[str]:
        """Return IDs of all direct successors of *node_id*."""
        return self._adj.get(node_id, [])

    def incoming_edges(self, node_id: str) -> list[DAGEdge]:
        """Return all edges that point to *node_id*."""
        return [e for e in self._edges if e.target == node_id]

    def terminal_nodes(self) -> list[str]:
        """Return IDs of nodes with no outgoing edges."""
        return [nid for nid in self._nodes if not self._adj.get(nid)]

    # -- Internal ----------------------------------------------------------

    def transitive_successors(self, node_id: str) -> set[str]:
        """Return IDs of all transitive successors of *node_id* (BFS)."""
        visited: set[str] = set()
        queue: deque[str] = deque(self._adj.get(node_id, []))
        while queue:
            nid = queue.popleft()
            if nid not in visited:
                visited.add(nid)
                queue.extend(n for n in self._adj.get(nid, []) if n not in visited)
        return visited

    def _has_cycle(self) -> bool:
        """Detect cycles via topological sort."""
        in_deg = dict(self._in_degree)
        for nid in self._nodes:
            in_deg.setdefault(nid, 0)
        queue: deque[str] = deque(nid for nid, d in in_deg.items() if d == 0)
        count = 0
        while queue:
            node = queue.popleft()
            count += 1
            for neighbour in self._adj.get(node, []):
                in_deg[neighbour] -= 1
                if in_deg[neighbour] == 0:
                    queue.append(neighbour)
        return count != len(self._nodes)

    def __repr__(self) -> str:
        return f"DAG(name={self._name!r}, nodes={len(self._nodes)}, edges={len(self._edges)})"
