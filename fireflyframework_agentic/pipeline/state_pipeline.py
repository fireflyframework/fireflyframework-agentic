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

"""State-based pipeline: a sequential executor over a typed shared-state object.

Layered on top of :class:`DAG` for topology, but uses its own simple executor
rather than :class:`PipelineEngine`. The trade-off: no within-level parallelism,
but in exchange we get clean semantics for typed state, reducers, branching,
checkpointing, and mid-pipeline resume — which are the things this API exists
to provide. Port-based parallel DAGs continue to use :class:`PipelineEngine`.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, get_type_hints

from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.checkpoint import Checkpointer, CheckpointRecord
from fireflyframework_agentic.pipeline.dag import DAG, _mermaid_id
from fireflyframework_agentic.pipeline.reducers import Reducer, replace

logger = logging.getLogger(__name__)

StateNodeFn = Callable[[Any], Awaitable[dict[str, Any] | None]]
# A router may return: a node id (str), a Send, or a list[Send] for fan-out.
RouterFn = Callable[[Any], "str | Send | list[Send]"]


@dataclass
class Send:
    """Runtime fan-out dispatch: run ``target`` with ``payload`` merged into state.

    Routers can return a single ``Send`` or a list of ``Send`` to dispatch multiple
    target invocations concurrently. Each Send's payload is applied to a *copy*
    of the current state before its target runs; the target's return is then
    merged back into shared state via reducers.

    Replaces the legacy ``FanOutStep`` pattern with a first-class primitive.
    """

    target: str
    payload: dict[str, Any]


class RecursionLimitError(Exception):
    """Raised when a node is visited more times than ``recursion_limit`` permits."""


@dataclass
class BranchSpec:
    """Internal: registered branch from one source node."""

    source: str
    router: RouterFn
    mapping: dict[str, str] | None  # label -> target node_id. None = router returns target directly.


@dataclass
class StatePipelineResult:
    """Outcome of a single ``invoke`` call.

    Attributes:
        state: Final state object.
        run_id: ID of this run (use to resume later via ``invoke(run_id=...)``).
        completed_nodes: Node IDs that ran successfully this invocation, in order.
        success: True iff all attempted nodes completed without error.
        error: Last error message if ``success`` is False.
        failed_node: Node ID that failed, if any.
    """

    state: Any
    run_id: str
    completed_nodes: list[str]
    success: bool
    error: str | None = None
    failed_node: str | None = None


def discover_reducers(state_schema: type) -> dict[str, Reducer]:
    """Inspect ``Annotated[T, reducer_fn]`` annotations on the schema.

    Only ``Annotated[...]`` metadata is consulted — not generic origins like
    ``list[...]`` or unions. Fields without an annotated reducer are absent
    from the returned dict; callers should treat absence as :func:`replace`.
    """
    out: dict[str, Reducer] = {}
    try:
        hints = get_type_hints(state_schema, include_extras=True)
    except Exception:
        return out
    for field_name, hint in hints.items():
        # Annotated[...] is the only metadata-bearing form we care about.
        metadata = getattr(hint, "__metadata__", None)
        if not metadata:
            continue
        for meta in metadata:
            if callable(meta):
                out[field_name] = meta
                break
    return out


def apply_update(state: BaseModel, update: dict[str, Any], reducers: dict[str, Reducer]) -> BaseModel:
    """Return a new state object with ``update`` merged into ``state`` via reducers."""
    if not update:
        return state
    new_values = state.model_dump()
    for key, value in update.items():
        if key not in new_values:
            # Tolerate unknown keys with a warning rather than failing —
            # makes incremental schema evolution painless.
            logger.warning("State update key '%s' not in schema %s; ignored.", key, type(state).__name__)
            continue
        reducer = reducers.get(key, replace)
        new_values[key] = reducer(new_values[key], value)
    return type(state).model_validate(new_values)


class StatePipeline:
    """Compiled state-based pipeline. Returned by ``PipelineBuilder.build()``
    when a ``state=`` schema is configured.
    """

    def __init__(
        self,
        *,
        name: str,
        dag: DAG,
        state_schema: type[BaseModel],
        node_fns: dict[str, StateNodeFn],
        branches: dict[str, BranchSpec],
        checkpointer: Checkpointer | None = None,
        recursion_limit: int = 25,
    ) -> None:
        self._name = name
        self._dag = dag
        self._state_schema = state_schema
        self._node_fns = node_fns
        self._branches = branches
        self._checkpointer = checkpointer
        self._recursion_limit = recursion_limit
        self._reducers = discover_reducers(state_schema)
        self._validate()

    @property
    def name(self) -> str:
        return self._name

    @property
    def dag(self) -> DAG:
        return self._dag

    def to_mermaid(self) -> str:
        """Render the pipeline as a Mermaid flowchart, including branch edges.

        Branches that omit an explicit mapping are rendered as a dashed edge
        labelled ``router`` because the targets are decided at runtime.
        """
        lines = ["flowchart TD"]
        for node_id in self._dag.nodes:
            lines.append(f"    {_mermaid_id(node_id)}[{node_id}]")
        # Explicit edges (including branch mappings, which were materialized).
        rendered: set[tuple[str, str]] = set()
        for edge in self._dag.edges:
            key = (edge.source, edge.target)
            rendered.add(key)
            label = None
            spec = self._branches.get(edge.source)
            if spec and spec.mapping:
                for lbl, tgt in spec.mapping.items():
                    if tgt == edge.target:
                        label = lbl
                        break
            arrow = f"-->|{label}|" if label else "-->"
            lines.append(f"    {_mermaid_id(edge.source)} {arrow} {_mermaid_id(edge.target)}")
        # Dynamic branches (no mapping): show as a dashed self-edge stub.
        for source, spec in self._branches.items():
            if spec.mapping is None and not self._dag.successors(source):
                lines.append(f"    {_mermaid_id(source)} -.->|router| {_mermaid_id(source)}_router((dynamic))")
        return "\n".join(lines)

    def _validate(self) -> None:
        # Every node must have a registered fn.
        for node_id in self._dag.nodes:
            if node_id not in self._node_fns:
                raise PipelineError(f"Node '{node_id}' has no registered function")
        # Every branch source/target must exist.
        for source, spec in self._branches.items():
            if source not in self._dag.nodes:
                raise PipelineError(f"Branch source '{source}' not in DAG")
            if spec.mapping:
                for label, target in spec.mapping.items():
                    if target not in self._dag.nodes:
                        raise PipelineError(f"Branch target '{target}' (label '{label}') not in DAG")

    def _entry_node(self) -> str:
        """Default entry: the first node added.

        Override with ``invoke(state, start_at=...)``. Picking insertion-order
        rather than the topological root keeps things predictable in the
        common case where a ``.branch(...)`` without an explicit mapping
        leaves multiple nodes with no inbound edges.
        """
        order = list(self._dag.nodes)
        if not order:
            raise PipelineError("Pipeline has no nodes")
        return order[0]

    def _next_step(self, current: str, state: BaseModel) -> str | list[Send] | None:
        """Decide what runs next given the current state.

        Returns:
            * A node id (str) for a single deterministic step.
            * A list of :class:`Send` for runtime fan-out — workers run concurrently.
            * ``None`` when the pipeline reaches a terminus.
        """
        if current in self._branches:
            decision = self._branches[current].router(state)
            return self._resolve_router_decision(current, decision)

        successors = self._dag.successors(current)
        if not successors:
            return None
        if len(successors) > 1:
            raise PipelineError(
                f"Node '{current}' has multiple successors {successors} but no .branch(...) registered. "
                f"Register a branch router or remove the extra edges."
            )
        return successors[0]

    def _resolve_router_decision(self, current: str, decision: str | Send | list[Send]) -> str | list[Send] | None:
        """Translate a router's return value into a concrete next-step instruction."""
        # Fan-out: list of Send dispatches.
        if isinstance(decision, list):
            if not decision:
                return None
            for s in decision:
                if not isinstance(s, Send):
                    raise PipelineError(
                        f"Router for '{current}' returned a list containing non-Send "
                        f"element {s!r}; expected list[Send]."
                    )
                if s.target not in self._dag.nodes:
                    raise PipelineError(f"Router for '{current}' fans out to unknown target '{s.target}'")
            return decision

        if isinstance(decision, Send):
            if decision.target not in self._dag.nodes:
                raise PipelineError(f"Router for '{current}' dispatched to unknown target '{decision.target}'")
            return [decision]

        # String label.
        spec = self._branches[current]
        if spec.mapping is not None:
            if decision not in spec.mapping:
                raise PipelineError(
                    f"Router for '{current}' returned label '{decision}' not in mapping {list(spec.mapping)}"
                )
            return spec.mapping[decision]
        if decision not in self._dag.nodes:
            raise PipelineError(
                f"Router for '{current}' returned '{decision}' "
                f"which is not a registered node id; pass an explicit mapping if you want labels."
            )
        return decision

    def _common_successor(self, node_ids: list[str]) -> str | None:
        """Return the node all ``node_ids`` share as their unique successor, or None."""
        successor_sets = [set(self._dag.successors(nid)) for nid in node_ids]
        if not successor_sets or any(len(s) != 1 for s in successor_sets):
            return None
        common = successor_sets[0]
        for s in successor_sets[1:]:
            common = common & s
        return next(iter(common)) if len(common) == 1 else None

    async def invoke(
        self,
        state: BaseModel | None = None,
        *,
        run_id: str | None = None,
        start_at: str | Callable[..., Any] | None = None,
    ) -> StatePipelineResult:
        """Run the pipeline.

        Modes:
            * Fresh run: ``invoke(state)`` — generates a new ``run_id``.
            * Resume: ``invoke(run_id="abc")`` — loads latest checkpoint and continues.
            * Mid-pipeline start: ``invoke(state=..., start_at=node)`` —
              starts execution at ``node`` with the provided state.
        """
        resumed_completed: list[str] = []

        # Resume mode: load checkpoint, derive starting node from it.
        if run_id is not None and state is None and start_at is None:
            if self._checkpointer is None:
                raise PipelineError("Cannot resume: pipeline has no checkpointer")
            record = self._checkpointer.load_latest(self._name, run_id)
            if record is None:
                raise PipelineError(f"No checkpoint found for run_id='{run_id}'")
            state = self._state_schema.model_validate(record.state)
            resumed_completed = list(record.completed_nodes)
            # Resume at the successor of the last completed node.
            last = record.node_id
            next_node = self._next_step(last, state)
            # Resume can't seamlessly continue mid-fan-out yet; treat fan-out as terminal here.
            if isinstance(next_node, list):
                raise PipelineError(
                    "Resume across a fan-out (Send) is not supported in Phase 2; "
                    "the run finished by reaching a fan-out node."
                )
            if next_node is None:
                return StatePipelineResult(
                    state=state,
                    run_id=run_id,
                    completed_nodes=resumed_completed,
                    success=True,
                )
            current_node: str | None = next_node
        else:
            if state is None:
                raise PipelineError("invoke() requires a state argument (or a run_id to resume)")
            if not isinstance(state, self._state_schema):
                # Be helpful if caller passed a dict or a different model.
                try:
                    state = self._state_schema.model_validate(state)
                except Exception as exc:
                    raise PipelineError(f"state argument is not a {self._state_schema.__name__}: {exc}") from exc
            if start_at is not None:
                current_node = _resolve_node_id(start_at)
                if current_node not in self._dag.nodes:
                    raise PipelineError(f"start_at='{current_node}' not in DAG")
            else:
                current_node = self._entry_node()

        if run_id is None:
            run_id = uuid.uuid4().hex[:12]

        assert state is not None  # narrowed by the branches above
        completed: list[str] = list(resumed_completed)
        sequence = len(completed)
        visit_counts: dict[str, int] = {}

        next_step: str | list[Send] | None = current_node
        last_node_id: str | None = current_node

        while next_step is not None:
            # --- fan-out branch (list[Send]) ---------------------------------
            if isinstance(next_step, list):
                try:
                    state, sequence = await self._run_fanout(
                        sends=next_step,
                        state=state,
                        completed=completed,
                        run_id=run_id,
                        sequence=sequence,
                        visit_counts=visit_counts,
                    )
                except _NodeFailureError as fail:
                    return StatePipelineResult(
                        state=state,
                        run_id=run_id,
                        completed_nodes=completed,
                        success=False,
                        error=fail.message,
                        failed_node=fail.node_id,
                    )
                last_node_id = next_step[-1].target
                # After fan-out, continue from the workers' shared successor (if any).
                worker_ids = [s.target for s in next_step]
                shared = self._common_successor(worker_ids)
                next_step = shared
                continue

            # --- single-node step --------------------------------------------
            node_id = next_step
            visit_counts[node_id] = visit_counts.get(node_id, 0) + 1
            if visit_counts[node_id] > self._recursion_limit:
                msg = (
                    f"Recursion limit ({self._recursion_limit}) exceeded at node '{node_id}'. "
                    f"Raise recursion_limit= or fix the routing logic."
                )
                logger.error(msg)
                return StatePipelineResult(
                    state=state,
                    run_id=run_id,
                    completed_nodes=completed,
                    success=False,
                    error=msg,
                    failed_node=node_id,
                )

            fn = self._node_fns[node_id]
            t0 = time.perf_counter()
            try:
                update = await fn(state)
            except Exception as exc:
                logger.exception(
                    "State pipeline '%s' run '%s' failed at node '%s'",
                    self._name,
                    run_id,
                    node_id,
                )
                return StatePipelineResult(
                    state=state,
                    run_id=run_id,
                    completed_nodes=completed,
                    success=False,
                    error=str(exc),
                    failed_node=node_id,
                )
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug("Pipeline '%s' node '%s' completed in %.1fms", self._name, node_id, elapsed)

            if update:
                state = apply_update(state, update, self._reducers)

            completed.append(node_id)
            sequence += 1
            self._save_checkpoint(run_id, node_id, sequence, state, completed)
            last_node_id = node_id

            try:
                next_step = self._next_step(node_id, state)
            except PipelineError as exc:
                return StatePipelineResult(
                    state=state,
                    run_id=run_id,
                    completed_nodes=completed,
                    success=False,
                    error=str(exc),
                    failed_node=last_node_id,
                )

        return StatePipelineResult(
            state=state,
            run_id=run_id,
            completed_nodes=completed,
            success=True,
        )

    async def _run_fanout(
        self,
        *,
        sends: list[Send],
        state: BaseModel,
        completed: list[str],
        run_id: str,
        sequence: int,
        visit_counts: dict[str, int],
    ) -> tuple[BaseModel, int]:
        """Run all ``Send`` dispatches concurrently. Each task gets its own state
        copy with the Send's payload merged in; results are reduced into shared state.
        """
        for send in sends:
            visit_counts[send.target] = visit_counts.get(send.target, 0) + 1
            if visit_counts[send.target] > self._recursion_limit:
                raise _NodeFailureError(
                    node_id=send.target,
                    message=(
                        f"Recursion limit ({self._recursion_limit}) exceeded at node '{send.target}' during fan-out."
                    ),
                )

        async def _run_one(send: Send) -> tuple[Send, dict[str, Any] | None]:
            task_state = apply_update(state, send.payload, self._reducers)
            fn = self._node_fns[send.target]
            return send, await fn(task_state)

        try:
            results = await asyncio.gather(*(_run_one(s) for s in sends))
        except Exception as exc:
            # Best-effort: report the first failing target as the failure point.
            raise _NodeFailureError(
                node_id=sends[0].target,
                message=f"Fan-out failure: {exc}",
            ) from exc

        new_state = state
        for send, update in results:
            if update:
                new_state = apply_update(new_state, update, self._reducers)
            completed.append(send.target)
            sequence += 1
            self._save_checkpoint(run_id, send.target, sequence, new_state, completed)

        return new_state, sequence

    def _save_checkpoint(
        self,
        run_id: str,
        node_id: str,
        sequence: int,
        state: BaseModel,
        completed: list[str],
    ) -> None:
        """Persist state via the configured checkpointer (no-op if absent)."""
        if self._checkpointer is None:
            return
        try:
            self._checkpointer.save(
                CheckpointRecord(
                    pipeline_name=self._name,
                    run_id=run_id,
                    node_id=node_id,
                    sequence=sequence,
                    state=state.model_dump(),
                    completed_nodes=list(completed),
                )
            )
        except Exception:
            logger.exception("Checkpoint save failed for run '%s' at '%s'", run_id, node_id)


@dataclass
class _NodeFailureError(Exception):
    """Internal sentinel used to bubble fan-out failures out to the main loop."""

    node_id: str
    message: str

    def __str__(self) -> str:
        return self.message


def _resolve_node_id(ref: str | Callable[..., Any]) -> str:
    """Turn either a string id or a function reference into a node id."""
    if isinstance(ref, str):
        return ref
    name = getattr(ref, "__name__", None)
    if not name:
        raise PipelineError(f"Cannot derive node id from {ref!r}")
    return name


def coerce_state_node_fn(fn: Callable[..., Any]) -> StateNodeFn:
    """Adapt a user-supplied callable into the ``async (state) -> dict | None`` shape.

    Accepted forms:
        * ``async def f(state) -> dict | None`` — used as-is.
        * ``def f(state) -> dict | None`` — wrapped to run in a thread.
        * Object with ``async run(state)`` (e.g. a FireflyAgent-like) — adapter calls ``.run(state)``.
    """
    if inspect.iscoroutinefunction(fn):
        return fn  # type: ignore[return-value]

    # Object with .run(state) — e.g. a FireflyAgent. Check before the generic
    # callable branch so agent-shaped objects don't get treated as plain callables.
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
