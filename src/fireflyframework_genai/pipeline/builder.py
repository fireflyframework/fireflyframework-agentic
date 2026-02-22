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

"""Fluent builder API for constructing pipeline DAGs.

Usage example::

    pipeline = (
        PipelineBuilder("idp-pipeline")
        .add_node("split", splitter_step)
        .add_node("classify", classifier_step)
        .add_node("extract", extractor_step)
        .add_edge("split", "classify")
        .add_edge("classify", "extract")
        .build()
    )
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fireflyframework_genai.pipeline.dag import DAG, DAGEdge, DAGNode, FailureStrategy
from fireflyframework_genai.pipeline.engine import PipelineEngine
from fireflyframework_genai.pipeline.steps import AgentStep, CallableStep, StepExecutor


class PipelineBuilder:
    """Fluent builder for constructing a :class:`DAG` and :class:`PipelineEngine`.

    Parameters:
        name: Human-readable name for the pipeline.
    """

    def __init__(self, name: str = "pipeline") -> None:
        self._dag = DAG(name=name)
        self._pending_nodes: list[DAGNode] = []
        self._pending_edges: list[DAGEdge] = []

    def add_node(
        self,
        node_id: str,
        step: Any,
        *,
        condition: Callable[..., bool] | None = None,
        retry_max: int = 0,
        timeout_seconds: float = 0,
        failure_strategy: FailureStrategy = FailureStrategy.SKIP_DOWNSTREAM,
    ) -> PipelineBuilder:
        """Add a node to the pipeline.

        *step* can be:
        - A :class:`StepExecutor` (AgentStep, CallableStep, etc.)
        - A :class:`FireflyAgent` (auto-wrapped in :class:`AgentStep`)
        - An async callable (auto-wrapped in :class:`CallableStep`)

        Returns *self* for chaining.
        """
        executor = self._resolve_step(step)
        self._pending_nodes.append(
            DAGNode(
                node_id=node_id,
                step=executor,
                condition=condition,
                retry_max=retry_max,
                timeout_seconds=timeout_seconds,
                failure_strategy=failure_strategy,
            )
        )
        return self

    def add_edge(
        self,
        source: str,
        target: str,
        *,
        output_key: str = "output",
        input_key: str = "input",
    ) -> PipelineBuilder:
        """Add a directed edge from *source* to *target*.

        Returns *self* for chaining.
        """
        self._pending_edges.append(
            DAGEdge(
                source=source,
                target=target,
                output_key=output_key,
                input_key=input_key,
            )
        )
        return self

    def chain(self, *node_ids: str) -> PipelineBuilder:
        """Connect nodes in sequence: A -> B -> C -> ...

        All referenced nodes must already have been added via :meth:`add_node`.
        Returns *self* for chaining.
        """
        for i in range(len(node_ids) - 1):
            self.add_edge(node_ids[i], node_ids[i + 1])
        return self

    def build(self) -> PipelineEngine:
        """Build the DAG, validate it, and return a :class:`PipelineEngine`.

        Raises:
            PipelineError: If the graph is invalid (cycles, missing nodes).
        """
        for node in self._pending_nodes:
            self._dag.add_node(node)
        for edge in self._pending_edges:
            self._dag.add_edge(edge)
        return PipelineEngine(self._dag)

    def build_dag(self) -> DAG:
        """Build and return just the :class:`DAG` (for inspection or custom engines)."""
        for node in self._pending_nodes:
            self._dag.add_node(node)
        for edge in self._pending_edges:
            self._dag.add_edge(edge)
        return self._dag

    @staticmethod
    def _resolve_step(step: Any) -> Any:
        """Wrap non-executor objects in the appropriate step type."""
        if isinstance(step, StepExecutor):
            return step
        # Duck-type check for agent-like objects
        if hasattr(step, "run") and callable(step.run):
            return AgentStep(step)
        # Async callable
        if callable(step):
            import asyncio

            if asyncio.iscoroutinefunction(step):
                return CallableStep(step)
        raise TypeError(
            f"Cannot resolve {type(step).__name__} as a pipeline step. Must be StepExecutor, agent-like, or async callable."
        )
