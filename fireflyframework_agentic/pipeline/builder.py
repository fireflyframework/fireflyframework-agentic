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

Two modes, both backed by the same :class:`PipelineEngine`:

1. **Port-based** (parallel-friendly): nodes are added by string id, data
   flows over edge ports::

       pipeline = (
           PipelineBuilder("idp")
           .add_node("split", splitter)
           .add_node("classify", classifier)
           .add_edge("split", "classify")
           .build()
       )

2. **State-based**: configure ``state=SomeModel`` and nodes become
   ``async (state) -> dict | None | Pause | Send | list[Send]``. Branching
   is one ``.branch(source, router)`` call; function references work as
   node ids. Optional checkpointing supports resume after failure and
   mid-pipeline start::

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

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.audit import AuditLog
from fireflyframework_agentic.pipeline.checkpoint import Checkpointer
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode, FailureStrategy
from fireflyframework_agentic.pipeline.engine import (
    EventHandler,
    PipelineEngine,
    PipelineEventHandler,
    RouterFn,
    Send,  # noqa: F401  re-exported via pipeline/__init__.py
)
from fireflyframework_agentic.pipeline.steps import AgentStep, CallableStep, StepExecutor

StateNodeFn = Callable[[Any], Awaitable[Any]]
"""Signature for a state-mode node: ``async (state) -> dict | None | Pause | Send | list[Send]``."""


class _StateStepAdapter:
    """Adapts a state-mode node fn into the :class:`StepExecutor` shape so it
    can ride through :meth:`PipelineEngine._execute_node`.

    State-mode functions take ``(state)`` and return a state update (or one
    of the control sentinels :class:`Pause` / :class:`Send`). The engine
    calls ``step.execute(context, inputs)``; this adapter forwards
    ``context.state`` to the wrapped fn and returns its value verbatim so
    PipelineEngine's existing dict/Pause/Send handling fires.
    """

    def __init__(self, fn: Callable[..., Any]) -> None:
        self._fn = _coerce_state_node_fn(fn)

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:  # noqa: ARG002
        return await self._fn(context.state)


def _coerce_state_node_fn(fn: Callable[..., Any]) -> StateNodeFn:
    """Turn user-supplied state-mode callables into the standard ``async (state) -> Any`` shape.

    Accepts:
    * ``async def f(state)`` — used as-is.
    * ``def f(state)`` — wrapped to run on a worker thread.
    * Object with ``async run(state)`` (e.g. a FireflyAgent) — adapter calls ``.run(state)``.
    """
    if inspect.iscoroutinefunction(fn):
        return fn  # type: ignore[return-value]

    run = getattr(fn, "run", None)
    if not callable(fn) and run is not None and callable(run):

        async def _agent_wrap(state: Any) -> Any:
            if inspect.iscoroutinefunction(run):
                return await run(state)
            return await asyncio.get_running_loop().run_in_executor(None, run, state)

        return _agent_wrap

    if callable(fn):

        async def _async_wrap(state: Any) -> Any:
            return await asyncio.get_running_loop().run_in_executor(None, fn, state)

        return _async_wrap

    raise PipelineError(f"Cannot adapt {fn!r} as a state node function")


class PipelineBuilder:
    """Fluent builder for pipelines.

    Parameters:
        name: Human-readable name for the pipeline.
        state: Optional Pydantic model class for typed shared state.
            When set, the builder produces a state-aware
            :class:`PipelineEngine` and nodes are expected to be
            ``async (state) -> dict | None | Pause | Send | list[Send]``.
        checkpointer: Optional :class:`Checkpointer` for resume.
        recursion_limit: Max visits per node in cycle-aware runs.
        event_handler: Optional :class:`EventHandler` (or legacy
            :class:`PipelineEventHandler`).
        audit_log: Optional :class:`AuditLog`.
    """

    def __init__(
        self,
        name: str = "pipeline",
        *,
        state: type[BaseModel] | None = None,
        checkpointer: Checkpointer | None = None,
        recursion_limit: int = 25,
        event_handler: EventHandler | PipelineEventHandler | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        # State-aware pipelines may have cycles (ReAct loops, retry-with-critique).
        self._dag = DAG(name=name, allow_cycles=state is not None)
        self._name = name
        self._state_schema = state
        self._checkpointer = checkpointer
        self._recursion_limit = recursion_limit
        self._event_handler = event_handler
        self._audit_log = audit_log
        self._pending_nodes: list[DAGNode] = []
        self._pending_edges: list[DAGEdge] = []
        # Routers + mappings drive the cyclic scheduler's next-step pick.
        self._routers: dict[str, RouterFn] = {}
        self._router_mappings: dict[str, dict[str, str]] = {}

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
        * ``add_node(node_id, step)`` — port-based mode. ``step`` is a
          :class:`StepExecutor`, an agent-like, or an async callable.
        """
        if step is None and callable(node_id_or_fn) and not isinstance(node_id_or_fn, str):
            if self._state_schema is None:
                raise PipelineError(
                    "Function-reference add_node(fn) requires PipelineBuilder(state=...). "
                    "Use add_node('id', step) for port-based pipelines."
                )
            fn = node_id_or_fn
            node_id = getattr(fn, "__name__", None) or repr(fn)
            self._pending_nodes.append(
                DAGNode(
                    node_id=node_id,
                    step=_StateStepAdapter(fn),
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
            run_method = getattr(step, "run", None)
            if not callable(step) and not callable(run_method):
                raise PipelineError(
                    f"State pipeline node '{node_id}' must be a callable or expose async run(state); "
                    f"got {type(step).__name__}"
                )
            self._pending_nodes.append(
                DAGNode(
                    node_id=node_id,
                    step=_StateStepAdapter(step),
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
        """Register a runtime router on ``source``.

        ``router`` is a synchronous ``(state) -> str | Send | list[Send]``
        callable. Behaviour:

        * If ``mapping`` is None, the router must return the **id of an
          existing node** that will run next.
        * If ``mapping`` is provided, the router returns an abstract label
          that is looked up in ``mapping`` to find the target node id.

        State-aware pipelines only.
        """
        if self._state_schema is None:
            raise PipelineError(".branch(...) requires PipelineBuilder(state=...)")
        source_id = _id(source)
        if mapping is not None:
            resolved_mapping = {label: _id(target) for label, target in mapping.items()}
            self._router_mappings[source_id] = resolved_mapping
            # Materialize each label's edge so topology stays inspectable.
            for target_id in resolved_mapping.values():
                self._pending_edges.append(DAGEdge(source=source_id, target=target_id))
        self._routers[source_id] = router
        return self

    def build(self) -> PipelineEngine:
        """Build the DAG and return a :class:`PipelineEngine`."""
        for node in self._pending_nodes:
            self._dag.add_node(node)
        for edge in self._pending_edges:
            self._dag.add_edge(edge)

        return PipelineEngine(
            self._dag,
            event_handler=self._event_handler,
            checkpointer=self._checkpointer,
            audit_log=self._audit_log,
            state_schema=self._state_schema,
            recursion_limit=self._recursion_limit,
            routers=self._routers,
            router_mappings=self._router_mappings,
        )

    def build_dag(self) -> DAG:
        """Build and return just the :class:`DAG` (for inspection)."""
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
