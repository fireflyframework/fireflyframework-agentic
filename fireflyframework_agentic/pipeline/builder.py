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

"""Fluent builder API for constructing pipeline DAGs.

Two modes:

1. **Port-based** (legacy, parallel-friendly): nodes are added by string id,
   data flows over edge ports, executed by :class:`PipelineEngine`. Use this
   for ETL-shaped DAGs with independent parallel steps::

       pipeline = (
           PipelineBuilder("idp")
           .add_node("split", splitter)
           .add_node("classify", classifier)
           .add_edge("split", "classify")
           .build()
       )

2. **State-based**: configure ``state=SomeModel`` and nodes become
   ``async (state) -> dict`` functions over a typed shared state. Branching
   is one ``.branch(source, router)`` call. Function references can be used
   as node ids. Optional checkpointing supports resume after failure and
   mid-pipeline start. Produces a :class:`StatePipeline`::

       pipeline = (
           PipelineBuilder("agent", state=AgentState, checkpointer=FileCheckpointer("./ckpt"))
           .add_node(classify)
           .add_node(answer)
           .add_node(escalate)
           .branch(classify, route)
           .build()
       )
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.checkpoint import Checkpointer
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode, FailureStrategy
from fireflyframework_agentic.pipeline.engine import PipelineEngine
from fireflyframework_agentic.pipeline.state_pipeline import (
    BranchSpec,
    RouterFn,
    Send,  # noqa: F401  re-exported via pipeline/__init__.py
    StateNodeFn,
    StatePipeline,
    coerce_state_node_fn,
)
from fireflyframework_agentic.pipeline.steps import AgentStep, CallableStep, StepExecutor


class PipelineBuilder:
    """Fluent builder for pipelines.

    Parameters:
        name: Human-readable name for the pipeline.
        state: Optional Pydantic model class for typed shared state.
            When set, the builder produces a :class:`StatePipeline` and nodes
            are expected to be ``async (state) -> dict | None``.
        checkpointer: Optional :class:`Checkpointer` for state-based pipelines.
            Ignored when ``state`` is not set.
    """

    def __init__(
        self,
        name: str = "pipeline",
        *,
        state: type[BaseModel] | None = None,
        checkpointer: Checkpointer | None = None,
        recursion_limit: int = 25,
    ) -> None:
        # State pipelines may use cyclic graphs (ReAct loops, retry-with-critique).
        # The legacy port-based path keeps acyclicity as an invariant.
        self._dag = DAG(name=name, allow_cycles=state is not None)
        self._name = name
        self._state_schema = state
        self._checkpointer = checkpointer
        self._recursion_limit = recursion_limit
        self._pending_nodes: list[DAGNode] = []
        self._pending_edges: list[DAGEdge] = []
        # State-based mode bookkeeping. Keyed by node id.
        self._state_node_fns: dict[str, StateNodeFn] = {}
        self._branches: dict[str, BranchSpec] = {}

    def add_node(
        self,
        node_id_or_fn: str | Callable[..., Any],
        step: Any = None,
        *,
        condition: Callable[..., bool] | None = None,
        retry_max: int = 0,
        timeout_seconds: float = 0,
        failure_strategy: FailureStrategy = FailureStrategy.SKIP_DOWNSTREAM,
    ) -> PipelineBuilder:
        """Add a node.

        Two signatures:

        * ``add_node(fn)`` — state-based mode. ``fn`` is a callable; the node
          id is taken from ``fn.__name__``. Requires the builder was constructed
          with ``state=...``.
        * ``add_node(node_id, step)`` — legacy port-based mode. ``step`` is a
          :class:`StepExecutor`, an agent-like, or an async callable.
        """
        if step is None and callable(node_id_or_fn) and not isinstance(node_id_or_fn, str):
            # State-based: derive id from function name.
            if self._state_schema is None:
                raise PipelineError(
                    "Function-reference add_node(fn) requires PipelineBuilder(state=...). "
                    "Use add_node('id', step) for port-based pipelines."
                )
            fn = node_id_or_fn
            node_id = getattr(fn, "__name__", None) or repr(fn)
            self._state_node_fns[node_id] = coerce_state_node_fn(fn)
            self._pending_nodes.append(
                DAGNode(
                    node_id=node_id,
                    step=_StateNodePlaceholder(),  # never executed; engine path is unused for state pipelines
                    condition=condition,
                    retry_max=retry_max,
                    timeout_seconds=timeout_seconds,
                    failure_strategy=failure_strategy,
                )
            )
            return self

        if not isinstance(node_id_or_fn, str):
            raise PipelineError("add_node(node_id, step) expects a string node id when a step is provided.")
        node_id = node_id_or_fn

        if self._state_schema is not None and step is not None:
            # State-based pipeline: accept a callable, or an agent-like object
            # exposing async ``run(state)``. ``coerce_state_node_fn`` handles both.
            run_method = getattr(step, "run", None)
            if not callable(step) and not callable(run_method):
                raise PipelineError(
                    f"State pipeline node '{node_id}' must be a callable or expose async run(state); "
                    f"got {type(step).__name__}"
                )
            self._state_node_fns[node_id] = coerce_state_node_fn(step)
            self._pending_nodes.append(
                DAGNode(
                    node_id=node_id,
                    step=_StateNodePlaceholder(),
                    condition=condition,
                    retry_max=retry_max,
                    timeout_seconds=timeout_seconds,
                    failure_strategy=failure_strategy,
                )
            )
            return self

        if step is None:
            raise PipelineError(f"add_node('{node_id}', step=...) requires a step.")

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
        source: str | Callable[..., Any],
        target: str | Callable[..., Any],
        *,
        output_key: str = "output",
        input_key: str = "input",
    ) -> PipelineBuilder:
        """Add a directed edge from *source* to *target*.

        Both endpoints may be node ids (str) or function references (in which
        case ``fn.__name__`` is used).
        """
        self._pending_edges.append(
            DAGEdge(
                source=_id(source),
                target=_id(target),
                output_key=output_key,
                input_key=input_key,
            )
        )
        return self

    def chain(self, *nodes: str | Callable[..., Any]) -> PipelineBuilder:
        """Connect nodes in sequence: A -> B -> C -> ..."""
        ids = [_id(n) for n in nodes]
        for i in range(len(ids) - 1):
            self.add_edge(ids[i], ids[i + 1])
        return self

    def branch(
        self,
        source: str | Callable[..., Any],
        router: RouterFn,
        mapping: dict[str, str | Callable[..., Any]] | None = None,
    ) -> PipelineBuilder:
        """Register a router on ``source``.

        ``router`` is a synchronous ``(state) -> str`` callable. Behaviour:

        * If ``mapping`` is None, the router must return the **id of an
          existing node** that will run next.
        * If ``mapping`` is provided, the router returns an abstract label
          that is looked up in ``mapping`` to find the target node id.

        State-based pipelines only.
        """
        if self._state_schema is None:
            raise PipelineError(".branch(...) requires PipelineBuilder(state=...)")
        source_id = _id(source)
        resolved_mapping: dict[str, str] | None = None
        if mapping is not None:
            resolved_mapping = {label: _id(target) for label, target in mapping.items()}
            # Materialize each label's edge into the DAG so topology is inspectable.
            for target_id in resolved_mapping.values():
                self._pending_edges.append(DAGEdge(source=source_id, target=target_id))
        else:
            # No mapping: we don't know targets at build time; edges will
            # be missing from the DAG. That's fine for the StatePipeline
            # executor (it consults the router), but visualisation will be
            # incomplete. Materialize edges lazily when the router fires.
            pass
        self._branches[source_id] = BranchSpec(source=source_id, router=router, mapping=resolved_mapping)
        return self

    def build(self) -> PipelineEngine | StatePipeline:
        """Build the DAG and return either a :class:`PipelineEngine`
        (legacy port-based) or :class:`StatePipeline` (when ``state=`` is set).
        """
        for node in self._pending_nodes:
            self._dag.add_node(node)
        for edge in self._pending_edges:
            self._dag.add_edge(edge)

        if self._state_schema is not None:
            return StatePipeline(
                name=self._name,
                dag=self._dag,
                state_schema=self._state_schema,
                node_fns=self._state_node_fns,
                branches=self._branches,
                checkpointer=self._checkpointer,
                recursion_limit=self._recursion_limit,
            )

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
        if hasattr(step, "run") and callable(step.run):
            return AgentStep(step)
        if callable(step) and inspect.iscoroutinefunction(step):
            return CallableStep(step)
        raise TypeError(
            f"Cannot resolve {type(step).__name__} as a pipeline step. "
            f"Must be StepExecutor, agent-like, or async callable."
        )


def _id(ref: str | Callable[..., Any]) -> str:
    """Coerce a string id or function reference into a node id string."""
    if isinstance(ref, str):
        return ref
    name = getattr(ref, "__name__", None)
    if not name:
        raise PipelineError(f"Cannot derive node id from {ref!r}")
    return name


class _StateNodePlaceholder:
    """Sentinel step kept in the DAG so topology is intact. Never executed —
    state pipelines bypass :class:`PipelineEngine` entirely."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise PipelineError("_StateNodePlaceholder.execute called — state pipelines should not use PipelineEngine.")
