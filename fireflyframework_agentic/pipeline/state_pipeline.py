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
import contextlib
import inspect
import logging
import time
import uuid
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.audit import AuditEntry, AuditLog, AuditStatus
from fireflyframework_agentic.pipeline.checkpoint import Checkpointer, CheckpointRecord
from fireflyframework_agentic.pipeline.dag import DAG, _mermaid_id
from fireflyframework_agentic.pipeline.engine import Pause, Send, start_otel_span
from fireflyframework_agentic.pipeline.reducers import apply_update, discover_reducers

if TYPE_CHECKING:
    from fireflyframework_agentic.pipeline.engine import StatePipelineEventHandler

logger = logging.getLogger(__name__)

StateNodeFn = Callable[[Any], Awaitable[dict[str, Any] | None]]
# A router may return: a node id (str), a Send, or a list[Send] for fan-out.
RouterFn = Callable[[Any], "str | Send | list[Send]"]


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
        paused: True if the run halted on a :class:`Pause` sentinel; resume
            via ``invoke(run_id=..., approve_pause=True)``.
        paused_node: Node that returned ``Pause`` if ``paused`` is True.
        pause_reason: Reason string the paused node passed to ``Pause(...)``.
    """

    state: Any
    run_id: str
    completed_nodes: list[str]
    success: bool
    error: str | None = None
    failed_node: str | None = None
    paused: bool = False
    paused_node: str | None = None
    pause_reason: str | None = None


class StatePipeline:
    """Compiled state-based pipeline. Returned by ``PipelineBuilder.build()``
    when a ``state=`` schema is configured.

    .. deprecated::
        :class:`StatePipeline` is being subsumed by
        :class:`fireflyframework_agentic.pipeline.engine.PipelineEngine`
        configured with ``state_schema=``. The unified engine supports
        the same features (state overlay, reducers, Pause, Send, cycles,
        recursion_limit, checkpointing, audit, resume, start_at) and adds
        true parallelism for state-aware pipelines via the topological
        scheduler. New code should prefer ``PipelineEngine`` directly:

        .. code-block:: python

            engine = PipelineEngine(
                dag,
                state_schema=MyState,
                checkpointer=cp,
                audit_log=al,
                recursion_limit=10,
            )
            result = await engine.run(state=MyState(...))

        See issue #245 for the full migration plan. The next layer of
        unification removes :class:`StatePipeline` after a deprecation
        cycle.
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
        event_handler: StatePipelineEventHandler | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        warnings.warn(
            "StatePipeline is deprecated; use PipelineEngine(state_schema=...) "
            "for the unified API. The unified engine supports the same features "
            "and adds parallel state-aware execution. See issue #245.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._name = name
        self._dag = dag
        self._state_schema = state_schema
        self._node_fns = node_fns
        self._branches = branches
        self._checkpointer = checkpointer
        self._recursion_limit = recursion_limit
        self._event_handler = event_handler
        self._audit_log = audit_log
        self._reducers = discover_reducers(state_schema)
        self._validate()

    def _audit(
        self,
        *,
        run_id: str,
        node_id: str,
        sequence: int,
        visit: int,
        started_at: datetime,
        completed_at: datetime,
        latency_ms: float,
        status: AuditStatus,
        inputs_snapshot: dict[str, Any],
        outputs_snapshot: dict[str, Any],
        error_message: str | None = None,
        pause_reason: str | None = None,
    ) -> None:
        """Construct and write an :class:`AuditEntry`. No-op if no audit log is configured.

        Audit-write failures are non-fatal — logged and swallowed.
        """
        if self._audit_log is None:
            return
        entry = AuditEntry(
            pipeline_name=self._name,
            run_id=run_id,
            node_id=node_id,
            sequence=sequence,
            visit=visit,
            started_at=started_at,
            completed_at=completed_at,
            latency_ms=latency_ms,
            status=status,
            inputs_snapshot=inputs_snapshot,
            outputs_snapshot=outputs_snapshot,
            error_message=error_message,
            pause_reason=pause_reason,
        )
        try:
            self._audit_log.record(entry)
        except Exception:
            logger.exception("Audit log write failed for run '%s' at '%s'", run_id, node_id)

    async def _emit(self, method: str, *args: Any) -> None:
        """Invoke ``method`` on the configured event handler if it exists.

        Missing methods are no-ops; raised exceptions are swallowed so
        observability never breaks business logic.
        """
        if self._event_handler is None:
            return
        fn = getattr(self._event_handler, method, None)
        if fn is None:
            return
        with contextlib.suppress(Exception):
            await fn(*args)

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
        for edge in self._dag.edges:
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
        successors = [self._dag.successors(nid) for nid in node_ids]
        if not successors or any(len(s) != 1 for s in successors):
            return None
        first = successors[0][0]
        return first if all(s[0] == first for s in successors[1:]) else None

    async def invoke(
        self,
        state: BaseModel | None = None,
        *,
        run_id: str | None = None,
        start_at: str | Callable[..., Any] | None = None,
        approve_pause: bool = False,
    ) -> StatePipelineResult:
        """Run the pipeline.

        Modes:
            * Fresh run: ``invoke(state)`` — generates a new ``run_id``.
            * Resume: ``invoke(run_id="abc")`` — loads latest checkpoint and continues.
            * Mid-pipeline start: ``invoke(state=..., start_at=node)`` —
              starts execution at ``node`` with the provided state.
        """
        completed: list[str] = []

        # Resume mode: load checkpoint, derive starting node from it.
        if run_id is not None and state is None and start_at is None:
            if self._checkpointer is None:
                raise PipelineError("Cannot resume: pipeline has no checkpointer")
            record = self._checkpointer.load_latest(self._name, run_id)
            if record is None:
                raise PipelineError(f"No checkpoint found for run_id='{run_id}'")
            # A paused run requires explicit approval before continuing.
            if record.paused and not approve_pause:
                raise PipelineError(
                    f"Run '{run_id}' is paused at node '{record.node_id}' "
                    f"(reason: {record.pause_reason!r}). Pass approve_pause=True to resume."
                )
            state = self._state_schema.model_validate(record.state)
            completed = list(record.completed_nodes)
            # Resume at the successor of the last completed (or paused) node.
            next_node = self._next_step(record.node_id, state)
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
                    completed_nodes=completed,
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
        visit_counts: dict[str, int] = {}

        next_step: str | list[Send] | None = current_node

        # ---- pipeline-level observability boundary -------------------------
        pipeline_start_time = time.perf_counter()
        pipeline_span = start_otel_span(f"pipeline.state.{self._name}", pipeline=self._name, run_id=run_id)
        await self._emit("on_pipeline_start", self._name, run_id)

        result: StatePipelineResult | None = None
        try:
            while next_step is not None:
                # --- fan-out branch (list[Send]) ---------------------------------
                if isinstance(next_step, list):
                    try:
                        state = await self._run_fanout(
                            sends=next_step,
                            state=state,
                            completed=completed,
                            run_id=run_id,
                            visit_counts=visit_counts,
                        )
                    except _NodeFailureError as fail:
                        result = StatePipelineResult(
                            state=state,
                            run_id=run_id,
                            completed_nodes=completed,
                            success=False,
                            error=fail.message,
                            failed_node=fail.node_id,
                        )
                        break
                    # After fan-out, continue from the workers' shared successor (if any).
                    next_step = self._common_successor([s.target for s in next_step])
                    continue

                # --- single-node step --------------------------------------------
                node_id = next_step
                visit_counts[node_id] = visit_counts.get(node_id, 0) + 1
                visit_n = visit_counts[node_id]
                if visit_n > self._recursion_limit:
                    msg = (
                        f"Recursion limit ({self._recursion_limit}) exceeded at node '{node_id}'. "
                        f"Raise recursion_limit= or fix the routing logic."
                    )
                    logger.error(msg)
                    result = StatePipelineResult(
                        state=state,
                        run_id=run_id,
                        completed_nodes=completed,
                        success=False,
                        error=msg,
                        failed_node=node_id,
                    )
                    break

                fn = self._node_fns[node_id]
                node_span = start_otel_span(f"pipeline.state.node.{node_id}", node=node_id, visit=visit_n)
                await self._emit("on_node_start", self._name, run_id, node_id, visit_n)
                inputs_snapshot = state.model_dump(mode="json")
                started_at = datetime.now(UTC)
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
                    await self._emit("on_node_error", self._name, run_id, node_id, str(exc))
                    if node_span is not None:
                        with contextlib.suppress(Exception):
                            node_span.end()
                    self._audit(
                        run_id=run_id,
                        node_id=node_id,
                        sequence=len(completed) + 1,
                        visit=visit_n,
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        latency_ms=(time.perf_counter() - t0) * 1000,
                        status="error",
                        inputs_snapshot=inputs_snapshot,
                        outputs_snapshot={},
                        error_message=str(exc),
                    )
                    result = StatePipelineResult(
                        state=state,
                        run_id=run_id,
                        completed_nodes=completed,
                        success=False,
                        error=str(exc),
                        failed_node=node_id,
                    )
                    break
                elapsed = (time.perf_counter() - t0) * 1000
                completed_at = datetime.now(UTC)
                if node_span is not None:
                    with contextlib.suppress(Exception):
                        node_span.end()

                # HITL: a node returning Pause halts the pipeline and writes a
                # paused checkpoint. Approval comes via invoke(approve_pause=True).
                if isinstance(update, Pause):
                    pause_reason = update.reason
                    await self._emit("on_node_pause", self._name, run_id, node_id, pause_reason)
                    completed.append(node_id)
                    self._save_checkpoint(
                        run_id,
                        node_id,
                        len(completed),
                        state,
                        completed,
                        paused=True,
                        pause_reason=pause_reason,
                    )
                    self._audit(
                        run_id=run_id,
                        node_id=node_id,
                        sequence=len(completed),
                        visit=visit_n,
                        started_at=started_at,
                        completed_at=completed_at,
                        latency_ms=elapsed,
                        status="paused",
                        inputs_snapshot=inputs_snapshot,
                        outputs_snapshot=state.model_dump(mode="json"),
                        pause_reason=pause_reason,
                    )
                    logger.info("Pipeline '%s' paused at node '%s': %s", self._name, node_id, pause_reason)
                    result = StatePipelineResult(
                        state=state,
                        run_id=run_id,
                        completed_nodes=completed,
                        success=False,
                        paused=True,
                        paused_node=node_id,
                        pause_reason=pause_reason,
                    )
                    break

                await self._emit("on_node_complete", self._name, run_id, node_id, elapsed)
                logger.debug("Pipeline '%s' node '%s' completed in %.1fms", self._name, node_id, elapsed)

                if update:
                    state = apply_update(state, update, self._reducers)

                completed.append(node_id)
                self._save_checkpoint(run_id, node_id, len(completed), state, completed)
                self._audit(
                    run_id=run_id,
                    node_id=node_id,
                    sequence=len(completed),
                    visit=visit_n,
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=elapsed,
                    status="success",
                    inputs_snapshot=inputs_snapshot,
                    outputs_snapshot=state.model_dump(mode="json"),
                )

                try:
                    next_step = self._next_step(node_id, state)
                except PipelineError as exc:
                    result = StatePipelineResult(
                        state=state,
                        run_id=run_id,
                        completed_nodes=completed,
                        success=False,
                        error=str(exc),
                        failed_node=node_id,
                    )
                    break

            if result is None:
                result = StatePipelineResult(
                    state=state,
                    run_id=run_id,
                    completed_nodes=completed,
                    success=True,
                )
        finally:
            if pipeline_span is not None:
                with contextlib.suppress(Exception):
                    pipeline_span.end()
            duration_ms = (time.perf_counter() - pipeline_start_time) * 1000
            success = result.success if result is not None else False
            await self._emit("on_pipeline_complete", self._name, run_id, success, duration_ms)

        assert result is not None  # set in try-block before reaching here
        return result

    async def _run_fanout(
        self,
        *,
        sends: list[Send],
        state: BaseModel,
        completed: list[str],
        run_id: str,
        visit_counts: dict[str, int],
    ) -> BaseModel:
        """Run all ``Send`` dispatches concurrently. Each task gets its own state
        copy with the Send's payload merged in; results are reduced into shared state.
        """
        # Snapshot each Send's visit number BEFORE dispatch so the worker's
        # closure captures its own visit, not the final post-increment value.
        sends_with_visits: list[tuple[Send, int]] = []
        for send in sends:
            visit_counts[send.target] = visit_counts.get(send.target, 0) + 1
            sends_with_visits.append((send, visit_counts[send.target]))
            if visit_counts[send.target] > self._recursion_limit:
                raise _NodeFailureError(
                    node_id=send.target,
                    message=(
                        f"Recursion limit ({self._recursion_limit}) exceeded at node '{send.target}' during fan-out."
                    ),
                )

        async def _run_one(send: Send, visit_n: int) -> tuple[Send, dict[str, Any] | None]:
            await self._emit("on_node_start", self._name, run_id, send.target, visit_n)
            node_span = start_otel_span(f"pipeline.state.node.{send.target}", node=send.target, visit=visit_n)
            task_state = apply_update(state, send.payload, self._reducers)
            fn = self._node_fns[send.target]
            t0 = time.perf_counter()
            try:
                update = await fn(task_state)
            except Exception as exc:
                await self._emit("on_node_error", self._name, run_id, send.target, str(exc))
                if node_span is not None:
                    with contextlib.suppress(Exception):
                        node_span.end()
                raise
            elapsed = (time.perf_counter() - t0) * 1000
            if node_span is not None:
                with contextlib.suppress(Exception):
                    node_span.end()
            await self._emit("on_node_complete", self._name, run_id, send.target, elapsed)
            return send, update

        try:
            results = await asyncio.gather(*(_run_one(s, v) for s, v in sends_with_visits))
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
            self._save_checkpoint(run_id, send.target, len(completed), new_state, completed)

        return new_state

    def _save_checkpoint(
        self,
        run_id: str,
        node_id: str,
        sequence: int,
        state: BaseModel,
        completed: list[str],
        *,
        paused: bool = False,
        pause_reason: str | None = None,
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
                    paused=paused,
                    pause_reason=pause_reason,
                )
            )
        except Exception:
            logger.exception("Checkpoint save failed for run '%s' at '%s'", run_id, node_id)


class _NodeFailureError(Exception):
    """Internal sentinel used to bubble fan-out failures out to the main loop."""

    def __init__(self, node_id: str, message: str) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.message = message


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
