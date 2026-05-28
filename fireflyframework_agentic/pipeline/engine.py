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

"""Pipeline execution engine: runs DAGs level-by-level with concurrency."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

try:
    from opentelemetry import trace as otel_trace
except ImportError:  # pragma: no cover - optional dep
    otel_trace = None  # type: ignore[assignment]

from pydantic import BaseModel

from fireflyframework_agentic.config import get_config
from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.observability.usage import default_usage_tracker
from fireflyframework_agentic.pipeline.audit import AuditEntry, AuditLog, AuditStatus
from fireflyframework_agentic.pipeline.checkpoint import Checkpointer, CheckpointRecord
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.dag import DAG, FailureStrategy
from fireflyframework_agentic.pipeline.reducers import Reducer, apply_update, discover_reducers
from fireflyframework_agentic.pipeline.result import (
    ExecutionTraceEntry,
    NodeResult,
    PipelineResult,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class EventHandler(Protocol):
    """Unified pipeline event handler. Used by :class:`PipelineEngine` and
    :class:`fireflyframework_agentic.pipeline.state_pipeline.StatePipeline`.

    Implement any subset of these methods; missing ones are no-ops. Exceptions
    raised in callbacks are swallowed by the engine so observability never
    breaks business logic.

    The engine dispatches events by parameter name. If your method signature
    omits a parameter — e.g. legacy implementations that don't accept
    ``run_id`` or ``visit`` — the engine simply drops it from the call.
    That keeps legacy :class:`PipelineEventHandler` /
    :class:`StatePipelineEventHandler` implementations working during the
    transition to this unified shape.

    Parameter conventions:

    * ``pipeline_name`` — DAG name, always present.
    * ``run_id`` — opaque identifier for a single invocation; lets ops
      correlate events across resumes and across multiple parallel runs.
    * ``visit`` — re-entry counter on cyclic graphs and fan-out. Starts at
      1 and increments each time a node is re-entered.
    * ``latency_ms`` — node wall-clock time, captured at the engine level.
    * ``reason`` — human-readable string; for skips and pauses.
    """

    async def on_pipeline_start(self, pipeline_name: str, run_id: str) -> None: ...

    async def on_node_start(self, pipeline_name: str, run_id: str, node_id: str, visit: int) -> None: ...

    async def on_node_complete(self, pipeline_name: str, run_id: str, node_id: str, latency_ms: float) -> None: ...

    async def on_node_error(self, pipeline_name: str, run_id: str, node_id: str, error: str) -> None: ...

    async def on_node_skip(self, pipeline_name: str, run_id: str, node_id: str, reason: str) -> None: ...

    async def on_node_pause(self, pipeline_name: str, run_id: str, node_id: str, reason: str) -> None: ...

    async def on_pipeline_complete(
        self, pipeline_name: str, run_id: str, success: bool, duration_ms: float
    ) -> None: ...


@runtime_checkable
class PipelineEventHandler(Protocol):
    """Legacy port-based event handler protocol. Use :class:`EventHandler`.

    Kept for backward compatibility. The engine inspects each callback's
    signature and only passes parameters the method declares — so existing
    implementations of this protocol continue to work unchanged. New code
    should implement :class:`EventHandler` so it receives ``run_id`` and
    ``visit`` too.
    """

    async def on_node_start(self, node_id: str, pipeline_name: str) -> None: ...
    async def on_node_complete(self, node_id: str, pipeline_name: str, latency_ms: float) -> None: ...
    async def on_node_error(self, node_id: str, pipeline_name: str, error: str) -> None: ...
    async def on_node_skip(self, node_id: str, pipeline_name: str, reason: str) -> None: ...
    async def on_pipeline_complete(self, pipeline_name: str, success: bool, duration_ms: float) -> None: ...


@runtime_checkable
class StatePipelineEventHandler(Protocol):
    """Legacy state-pipeline event handler protocol. Use :class:`EventHandler`.

    Same shape as :class:`EventHandler` minus ``on_node_skip``. Kept for
    backward compatibility; new code should implement :class:`EventHandler`.
    """

    async def on_pipeline_start(self, pipeline_name: str, run_id: str) -> None: ...
    async def on_node_start(self, pipeline_name: str, run_id: str, node_id: str, visit: int) -> None: ...
    async def on_node_complete(self, pipeline_name: str, run_id: str, node_id: str, latency_ms: float) -> None: ...
    async def on_node_error(self, pipeline_name: str, run_id: str, node_id: str, error: str) -> None: ...
    async def on_node_pause(self, pipeline_name: str, run_id: str, node_id: str, reason: str) -> None: ...
    async def on_pipeline_complete(
        self, pipeline_name: str, run_id: str, success: bool, duration_ms: float
    ) -> None: ...


@dataclass
class Pause:
    """Human-in-the-loop sentinel returned by a node to halt the pipeline.

    A node returns ``Pause(reason="...")`` when external approval is required
    before the pipeline may continue. The engine then:

    1. Writes a checkpoint with ``paused=True`` and the reason set.
    2. Emits ``on_node_pause`` on the configured event handler.
    3. Returns a :class:`PipelineResult` with ``paused=True`` and
       ``success=False`` — the run is not finished, but it did not fail
       either.

    Resume after approval::

        result = await engine.run(run_id=paused_run_id, approve_pause=True)

    The successor of the paused node runs next — the pause node itself is
    not re-executed. Without ``approve_pause=True``, resuming a paused run
    raises :class:`PipelineError`.
    """

    reason: str


@dataclass
class Send:
    """Runtime fan-out dispatch: run ``target`` with ``payload`` merged into state.

    A node may return a single ``Send`` or ``list[Send]`` to dispatch one or
    more targets concurrently. Each Send's payload is applied to a *copy* of
    the current state before its target runs; the target's return is then
    merged back into shared state via reducers.

    Replaces the legacy ``FanOutStep`` pattern with a first-class primitive.
    """

    target: str
    payload: dict[str, Any]


def _is_send_payload(value: Any) -> bool:
    """True when a node's return value is a single :class:`Send` or a
    non-empty ``list[Send]``. Drives the runtime fan-out branch in
    :meth:`PipelineEngine.run`.
    """
    if isinstance(value, Send):
        return True
    if isinstance(value, list) and value and all(isinstance(s, Send) for s in value):
        return True
    return False


def _serialize_value(value: Any) -> Any:
    """Best-effort conversion of arbitrary values into JSON-safe form.

    Pydantic models go through ``model_dump(mode="json")``. Primitives,
    lists, and dicts pass through. Anything else falls back to ``str()``
    so the serialization layer (checkpoint, audit) doesn't blow up on
    exotic objects.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return str(value)
    return str(value)


def start_otel_span(name: str, **attributes: Any) -> Any:
    """Start an OTel span if observability is enabled, else return ``None``.

    Module-level helper shared by :class:`PipelineEngine` and
    :class:`fireflyframework_agentic.pipeline.state_pipeline.StatePipeline`.
    """
    try:
        if not get_config().observability_enabled:
            return None
        if otel_trace is None:
            return None
        return otel_trace.get_tracer("fireflyframework_agentic").start_span(
            name,
            attributes={f"firefly.{k}": str(v) for k, v in attributes.items()},
        )
    except Exception:  # noqa: BLE001
        return None


class PipelineEngine:
    """Executes a :class:`DAG` by computing topological levels and running
    nodes within each level concurrently.

    Parameters:
        dag: The DAG to execute.
    """

    def __init__(
        self,
        dag: DAG,
        *,
        event_handler: EventHandler | PipelineEventHandler | None = None,
        checkpointer: Checkpointer | None = None,
        audit_log: AuditLog | None = None,
        state_schema: type[BaseModel] | None = None,
        recursion_limit: int = 25,
    ) -> None:
        self._dag = dag
        self._event_handler = event_handler
        self._checkpointer = checkpointer
        self._audit_log = audit_log
        # Optional shared-state overlay. When set, nodes returning a dict
        # have it merged into the state via reducers; non-dict returns
        # continue to flow through edges as port outputs. Both can coexist.
        self._state_schema = state_schema
        self._reducers: dict[str, Reducer] = discover_reducers(state_schema) if state_schema is not None else {}
        # Max visits per node for cycle-aware runs. Matches StatePipeline's default.
        self._recursion_limit = recursion_limit
        # Per-method signature cache for legacy-vs-unified dispatch.
        self._handler_params: dict[str, set[str]] = {}

    async def _dispatch(self, method_name: str, /, **kwargs: Any) -> None:
        """Invoke ``event_handler.method_name`` with the subset of ``kwargs``
        the method's signature actually declares.

        Lets the engine emit events using the unified :class:`EventHandler`
        convention while still supporting legacy
        :class:`PipelineEventHandler` implementations whose methods don't
        accept ``run_id`` or ``visit``. Missing methods and raised
        exceptions are silently swallowed — observability never breaks the
        pipeline.
        """
        if self._event_handler is None:
            return
        method = getattr(self._event_handler, method_name, None)
        if method is None:
            return
        if method_name not in self._handler_params:
            try:
                params = inspect.signature(method).parameters
                self._handler_params[method_name] = {
                    name
                    for name, p in params.items()
                    if p.kind
                    in (
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.KEYWORD_ONLY,
                    )
                }
            except (TypeError, ValueError):
                self._handler_params[method_name] = set(kwargs)
        accepted = self._handler_params[method_name]
        call_kwargs = {k: v for k, v in kwargs.items() if k in accepted}
        with contextlib.suppress(Exception):
            await method(**call_kwargs)

    async def run(
        self,
        context: PipelineContext | None = None,
        *,
        inputs: Any = None,
        state: BaseModel | None = None,
        run_id: str | None = None,
        approve_pause: bool = False,
    ) -> PipelineResult:
        """Execute the pipeline.

        Parameters:
            context: Pre-built context, or *None* to create one automatically.
            inputs: Initial inputs (used if *context* is not provided).
            state: Optional shared state object for engines configured with
                ``state_schema=``. When omitted, the engine instantiates the
                schema with its defaults.
            run_id: Identifier for this run. When given alone (no ``context``
                and no ``inputs``), the engine loads the latest checkpoint for
                that run and resumes from after the last completed node.
                Requires a checkpointer to be configured.

        Returns:
            A :class:`PipelineResult` with all node outputs, trace, ``run_id``
            (use to resume later), and ``final_state`` for state-aware runs.
        """
        if run_id is not None and context is None and inputs is None and state is None:
            resume_run_id: str = run_id
            context, pre_completed, sequence_start = self._load_for_resume(resume_run_id, approve_pause=approve_pause)
            all_results: dict[str, NodeResult] = {
                nid: nr
                for nid in pre_completed
                if (nr := context.get_node_result(nid)) is not None and isinstance(nr, NodeResult)
            }
        else:
            if context is None:
                context = PipelineContext(inputs=inputs)
            # Initialize shared state if configured.
            if self._state_schema is not None and context.state is None:
                if state is not None:
                    if not isinstance(state, self._state_schema):
                        state = self._state_schema.model_validate(state)
                    context.state = state
                else:
                    try:
                        context.state = self._state_schema()
                    except Exception as exc:
                        raise PipelineError(
                            f"state required for pipeline with state_schema {self._state_schema.__name__}: {exc}"
                        ) from exc
            pre_completed = set()
            sequence_start = 0
            all_results = {}

        if run_id is None:
            run_id = uuid.uuid4().hex[:12]

        # Observability: pipeline-level span + start event
        _pipeline_span = self._start_otel_span(
            f"pipeline.{self._dag.name}",
            pipeline=self._dag.name,
        )
        await self._dispatch("on_pipeline_start", pipeline_name=self._dag.name, run_id=run_id)

        # Cycle-aware mode: a separate sequential frontier-following scheduler
        # that respects ``recursion_limit``. The topological scheduler below
        # cannot run cyclic graphs because execution_levels()/topological_sort()
        # are undefined on them.
        if self._dag.is_cyclic():
            return await self._run_cyclic(
                context=context,
                run_id=run_id,
                all_results=all_results,
                pre_completed=pre_completed,
                sequence_start=sequence_start,
                pipeline_span=_pipeline_span,
            )

        # Topological levels ensure that all upstream dependencies of a node
        # complete before the node itself executes.  Nodes within the same
        # level are independent and run concurrently via asyncio.gather.
        levels = self._dag.execution_levels()
        trace_entries: list[ExecutionTraceEntry] = []
        pipeline_start = time.perf_counter()

        failed_nodes: set[str] = set()

        # Eager scheduling: as soon as all of a node's dependencies are
        # resolved we can schedule it, rather than waiting for the entire
        # level to finish.  This is a significant improvement when nodes
        # within a level have uneven latencies.
        pending: set[str] = set()
        for level in levels:
            pending.update(level)
        pending -= pre_completed  # resume: don't re-run nodes already completed

        completed: set[str] = set(pre_completed)
        running: dict[str, asyncio.Task[NodeResult]] = {}
        inputs_by_node: dict[str, dict[str, Any]] = {}
        sequence = sequence_start
        abort = False
        pending_pause: tuple[str, str] | None = None  # (node_id, reason) if Pause

        def _edge_alive(edge: Any) -> bool:
            """An edge is alive if it has no condition, or its condition returns True.

            Raises in the condition itself are treated as False — fail
            closed so a broken predicate kills the branch instead of
            silently waking up the wrong target.
            """
            if edge.condition is None:
                return True
            try:
                return bool(edge.condition(context))
            except Exception:
                return False

        def _ready(nid: str) -> bool:
            """A node is ready when:
            (1) every incoming edge's source has completed, AND
            (2) at least one of those edges is alive (or it has no edges).

            Entry nodes (no incoming) are always ready once scheduled.
            """
            edges = self._dag.incoming_edges(nid)
            if not edges:
                return True
            if not all(e.source in completed for e in edges):
                return False
            return any(_edge_alive(e) for e in edges)

        def _is_dead(nid: str) -> bool:
            """A node is dead when every incoming edge has resolved but
            none of them is alive. Cascades via the SKIP_DOWNSTREAM
            mechanism so transitive successors are skipped without
            being scheduled.
            """
            edges = self._dag.incoming_edges(nid)
            if not edges:
                return False
            if not all(e.source in completed for e in edges):
                return False
            return not any(_edge_alive(e) for e in edges)

        async def _record_skip(nid: str) -> None:
            """Mark a node as skipped without scheduling it. Mirrors the
            handling of in-flight skips returned by ``_execute_node``.
            """
            nonlocal sequence
            nr = NodeResult(node_id=nid, skipped=True, error="No alive incoming edge")
            all_results[nid] = nr
            context.set_node_result(nid, nr)
            completed.add(nid)
            failed_nodes.add(nid)
            failed_nodes.update(self._dag.transitive_successors(nid))
            await self._emit_node_result(nr, run_id)
            sequence += 1
            self._record_audit(
                run_id=run_id,
                node_id=nid,
                sequence=sequence,
                nr=nr,
                inputs_snapshot={},
                trace_entries=trace_entries,
            )

        while pending or running:
            # Schedule all ready nodes that aren't already running.
            if not abort:
                for nid in list(pending):
                    if _ready(nid) and nid not in running:
                        # Gather inputs outside _execute_node so we can stash
                        # them for the audit snapshot.
                        gathered = self._gather_inputs(nid, context)
                        inputs_by_node[nid] = gathered
                        task = asyncio.create_task(
                            self._execute_node(
                                nid,
                                context,
                                trace_entries,
                                failed_nodes,
                                inputs=gathered,
                                run_id=run_id,
                            ),
                        )
                        running[nid] = task
                        pending.discard(nid)

            if not running:
                break

            # Wait for at least one task to complete.
            done, _ = await asyncio.wait(
                running.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                # Find the node_id for the completed task
                node_id = next(nid for nid, t in running.items() if t is task)
                del running[node_id]
                completed.add(node_id)

                try:
                    nr = task.result()
                except Exception as exc:
                    nr = NodeResult(
                        node_id=node_id,
                        success=False,
                        error=str(exc),
                    )

                all_results[node_id] = nr
                context.set_node_result(node_id, nr)

                # Emit event callbacks
                await self._emit_node_result(nr, run_id)

                # Persist lifecycle: audit every executed visit; checkpoint only
                # successful completions (failed nodes must re-run on resume).
                sequence += 1
                self._record_audit(
                    run_id=run_id,
                    node_id=node_id,
                    sequence=sequence,
                    nr=nr,
                    inputs_snapshot=inputs_by_node.get(node_id, {}),
                    trace_entries=trace_entries,
                )
                # HITL: a node returned Pause(reason=...). Halt cleanly, save
                # a paused checkpoint, and surface the pause in the result.
                if nr.success and isinstance(nr.output, Pause):
                    pause_reason = nr.output.reason
                    await self._dispatch(
                        "on_node_pause",
                        pipeline_name=self._dag.name,
                        run_id=run_id,
                        node_id=node_id,
                        reason=pause_reason,
                    )
                    self._save_checkpoint(
                        run_id=run_id,
                        node_id=node_id,
                        sequence=sequence,
                        context=context,
                        all_results=all_results,
                        paused=True,
                        pause_reason=pause_reason,
                    )
                    pending_pause = (node_id, pause_reason)
                    abort = True
                    continue

                # Runtime fan-out: a node returned Send / list[Send].
                if nr.success and _is_send_payload(nr.output):
                    sends = nr.output if isinstance(nr.output, list) else [nr.output]
                    ok = await self._run_sends(
                        sends=sends,
                        context=context,
                        run_id=run_id,
                        all_results=all_results,
                        trace_entries=trace_entries,
                        completed=completed,
                        pending=pending,
                    )
                    if not ok:
                        abort = True
                    # Successors of the worker targets are picked up by the
                    # normal readiness sweep on the next loop iteration.
                    continue

                if nr.success and not nr.skipped:
                    # State overlay: a dict return from the node is a state
                    # update; non-dict returns flow through edges as ports.
                    if self._state_schema is not None and context.state is not None and isinstance(nr.output, dict):
                        context.state = apply_update(context.state, nr.output, self._reducers)
                    self._save_checkpoint(
                        run_id=run_id,
                        node_id=node_id,
                        sequence=sequence,
                        context=context,
                        all_results=all_results,
                    )

                # Handle failure strategies
                if not nr.success and not nr.skipped:
                    node = self._dag.nodes.get(node_id)
                    strategy = node.failure_strategy if node else FailureStrategy.SKIP_DOWNSTREAM
                    if strategy == FailureStrategy.FAIL_PIPELINE:
                        abort = True
                    elif strategy == FailureStrategy.SKIP_DOWNSTREAM:
                        failed_nodes.add(node_id)
                        failed_nodes.update(self._dag.transitive_successors(node_id))

            # Sweep pending for nodes whose incoming edges have resolved
            # but none is alive. Mark them skipped and cascade — this is
            # what makes DAGEdge.condition a usable branching primitive.
            for nid in list(pending):
                if _is_dead(nid):
                    await _record_skip(nid)
                    pending.discard(nid)

            if abort:
                # Cancel remaining tasks
                for t in running.values():
                    t.cancel()
                break

        pipeline_elapsed = (time.perf_counter() - pipeline_start) * 1000

        # Terminal nodes are those with no downstream edges.  The pipeline's
        # final output is drawn from these nodes' results.
        terminal_ids = self._dag.terminal_nodes()
        final_outputs = {
            nid: all_results[nid].output for nid in terminal_ids if nid in all_results and all_results[nid].success
        }
        final_output = list(final_outputs.values())[0] if len(final_outputs) == 1 else final_outputs or None

        success = all(r.success or r.skipped for r in all_results.values())

        # Emit pipeline complete event
        await self._dispatch(
            "on_pipeline_complete",
            pipeline_name=self._dag.name,
            run_id=run_id,
            success=success,
            duration_ms=pipeline_elapsed,
        )

        # Aggregate usage across all nodes for this pipeline run
        usage_summary = self._aggregate_usage(context.correlation_id)

        if _pipeline_span is not None:
            _pipeline_span.end()

        paused_node = pending_pause[0] if pending_pause else None
        pause_reason_final = pending_pause[1] if pending_pause else None
        if pending_pause is not None:
            # A paused run is not "successful" — it didn't finish.
            success = False

        return PipelineResult(
            pipeline_name=self._dag.name,
            outputs=all_results,
            final_output=final_output,
            execution_trace=trace_entries,
            total_duration_ms=pipeline_elapsed,
            success=success,
            usage=usage_summary,
            run_id=run_id,
            final_state=context.state,
            paused=pending_pause is not None,
            paused_node=paused_node,
            pause_reason=pause_reason_final,
        )

    async def _run_sends(
        self,
        *,
        sends: list[Send],
        context: PipelineContext,
        run_id: str,
        all_results: dict[str, NodeResult],
        trace_entries: list[ExecutionTraceEntry],
        completed: set[str],
        pending: set[str],
    ) -> bool:
        """Dispatch a list of :class:`Send` workers concurrently.

        Each Send's payload is applied to a copy of the current state before
        its target runs. Results merge back into shared state via reducers.
        Targets are added to ``completed`` and removed from ``pending`` so
        the main scheduler does not re-execute them.

        Returns ``True`` on success, ``False`` if any worker failed (the
        caller treats this as an abort signal).
        """
        # Validate targets up front so unknown ones fail loud, not after gather().
        for send in sends:
            if send.target not in self._dag.nodes:
                nr = NodeResult(
                    node_id=send.target,
                    success=False,
                    error=f"Send dispatches to unknown target '{send.target}'",
                )
                all_results[send.target] = nr
                return False

        async def _run_one(send: Send) -> tuple[Send, NodeResult]:
            await self._dispatch(
                "on_node_start",
                pipeline_name=self._dag.name,
                run_id=run_id,
                node_id=send.target,
                visit=1,
            )
            # Per-worker context: own state copy with payload applied so
            # workers don't race on the shared state object.
            worker_context = PipelineContext(inputs=context.inputs)
            if self._state_schema is not None and context.state is not None:
                worker_context.state = apply_update(context.state, send.payload, self._reducers)
            for nid, prev in context.results.items():
                worker_context.set_node_result(nid, prev)
            nr = await self._execute_node(
                send.target,
                worker_context,
                trace_entries,
                None,
                inputs={"input": send.payload},
                run_id=run_id,
            )
            return send, nr

        try:
            results = await asyncio.gather(*(_run_one(s) for s in sends))
        except Exception as exc:
            logger.exception("Fan-out worker crashed")
            for send in sends:
                if send.target not in all_results:
                    all_results[send.target] = NodeResult(node_id=send.target, success=False, error=str(exc))
            return False

        all_ok = True
        for send, nr in results:
            all_results[send.target] = nr
            context.set_node_result(send.target, nr)
            completed.add(send.target)
            pending.discard(send.target)
            await self._emit_node_result(nr, run_id)
            if not nr.success:
                all_ok = False
                continue
            if self._state_schema is not None and context.state is not None and isinstance(nr.output, dict):
                context.state = apply_update(context.state, nr.output, self._reducers)
        return all_ok

    async def _run_cyclic(
        self,
        *,
        context: PipelineContext,
        run_id: str,
        all_results: dict[str, NodeResult],
        pre_completed: set[str],
        sequence_start: int,
        pipeline_span: Any,
    ) -> PipelineResult:
        """Sequential frontier-following scheduler for cyclic DAGs.

        Walks the graph one node at a time, picking the next node from each
        completed node's alive outgoing edges. Visit counts are tracked per
        node and bounded by ``self._recursion_limit``. Within this mode,
        having multiple alive outgoing edges is currently an error — parallel
        cyclic fan-out is the job of :class:`Send` in a later layer.
        """
        trace_entries: list[ExecutionTraceEntry] = []
        pipeline_start = time.perf_counter()
        visit_counts: dict[str, int] = dict.fromkeys(pre_completed, 1)
        sequence = sequence_start

        # Entry node: insertion order, matching StatePipeline.
        nodes_in_order = list(self._dag.nodes)
        if not nodes_in_order:
            raise PipelineError("Pipeline has no nodes")
        current: str | None = nodes_in_order[0]
        # Skip past anything already completed during this resumed run.
        while current is not None and current in pre_completed:
            current = self._cyclic_next(current, context)

        result: PipelineResult | None = None
        try:
            while current is not None:
                visit_counts[current] = visit_counts.get(current, 0) + 1
                visit_n = visit_counts[current]
                if visit_n > self._recursion_limit:
                    msg = (
                        f"Recursion limit ({self._recursion_limit}) exceeded at node "
                        f"'{current}'. Raise recursion_limit= or fix the routing logic."
                    )
                    logger.error(msg)
                    nr = NodeResult(node_id=current, success=False, error=msg)
                    all_results[current] = nr
                    sequence += 1
                    self._record_audit(
                        run_id=run_id,
                        node_id=current,
                        sequence=sequence,
                        nr=nr,
                        inputs_snapshot={},
                        trace_entries=trace_entries,
                    )
                    break

                gathered = self._gather_inputs(current, context)
                await self._dispatch(
                    "on_node_start",
                    pipeline_name=self._dag.name,
                    run_id=run_id,
                    node_id=current,
                    visit=visit_n,
                )
                nr = await self._execute_node(
                    current,
                    context,
                    trace_entries,
                    None,
                    inputs=gathered,
                    run_id=run_id,
                )
                all_results[current] = nr
                context.set_node_result(current, nr)
                await self._emit_node_result(nr, run_id)

                sequence += 1
                self._record_audit(
                    run_id=run_id,
                    node_id=current,
                    sequence=sequence,
                    nr=nr,
                    inputs_snapshot=gathered,
                    trace_entries=trace_entries,
                    visit=visit_n,
                )

                if not nr.success and not nr.skipped:
                    break

                if not nr.skipped:
                    if self._state_schema is not None and context.state is not None and isinstance(nr.output, dict):
                        context.state = apply_update(context.state, nr.output, self._reducers)
                    self._save_checkpoint(
                        run_id=run_id,
                        node_id=current,
                        sequence=sequence,
                        context=context,
                        all_results=all_results,
                    )

                current = self._cyclic_next(current, context)
        finally:
            elapsed = (time.perf_counter() - pipeline_start) * 1000
            success = (
                result.success if result is not None else all(r.success or r.skipped for r in all_results.values())
            )
            await self._dispatch(
                "on_pipeline_complete",
                pipeline_name=self._dag.name,
                run_id=run_id,
                success=success,
                duration_ms=elapsed,
            )
            if pipeline_span is not None:
                with contextlib.suppress(Exception):
                    pipeline_span.end()

        final_output = None
        return PipelineResult(
            pipeline_name=self._dag.name,
            outputs=all_results,
            final_output=final_output,
            execution_trace=trace_entries,
            total_duration_ms=elapsed,
            success=success,
            usage=None,
            run_id=run_id,
            final_state=context.state,
        )

    def _cyclic_next(self, current: str, context: PipelineContext) -> str | None:
        """Pick the next node by following the unique alive outgoing edge.

        Returns ``None`` when no outgoing edge is alive (terminus). Raises
        if more than one is alive — parallel cyclic fan-out lands with
        :class:`Send` in a later layer.
        """

        def _alive(edge: Any) -> bool:
            if edge.condition is None:
                return True
            try:
                return bool(edge.condition(context))
            except Exception:
                return False

        outgoing = [e for e in self._dag.edges if e.source == current]
        alive = [e for e in outgoing if _alive(e)]
        if not alive:
            return None
        if len(alive) > 1:
            raise PipelineError(
                f"Cyclic node '{current}' has multiple alive outgoing edges "
                f"({[e.target for e in alive]}). Parallel cyclic fan-out arrives "
                f"with Send in a later layer; for now, use mutually exclusive "
                f"edge conditions."
            )
        return alive[0].target

    async def _execute_node(
        self,
        node_id: str,
        context: PipelineContext,
        trace_entries: list[ExecutionTraceEntry],
        failed_nodes: set[str] | None = None,
        *,
        inputs: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> NodeResult:
        """Execute a single node with retries and condition gating.

        ``inputs`` may be pre-gathered by the caller so the same dict can be
        used both for execution and for the audit log's inputs snapshot.
        """
        # Skip if an upstream node failed with SKIP_DOWNSTREAM strategy
        if failed_nodes and node_id in failed_nodes:
            logger.debug("Node '%s' skipped (upstream failure)", node_id)
            # Event emission is handled centrally by _emit_node_result in run()
            return NodeResult(node_id=node_id, skipped=True, error="Skipped due to upstream failure")

        node = self._dag.nodes[node_id]

        # Check condition gate
        if node.condition is not None:
            try:
                should_run = node.condition(context)
            except Exception:
                should_run = False
            if not should_run:
                logger.debug("Node '%s' skipped (condition not met)", node_id)
                return NodeResult(node_id=node_id, skipped=True)

        # Gather inputs from upstream edges (unless caller already did)
        if inputs is None:
            inputs = self._gather_inputs(node_id, context)

        _node_span = self._start_otel_span(
            f"pipeline.node.{node_id}",
            node=node_id,
        )

        # Emit node start event (visit=1; cycles arrive in a later layer)
        await self._dispatch(
            "on_node_start",
            pipeline_name=self._dag.name,
            run_id=run_id,
            node_id=node_id,
            visit=1,
        )

        max_retries = node.retry_max
        backoff_factor = node.backoff_factor
        retries = 0
        last_error: str | None = None
        started_at = datetime.now(UTC)

        while retries <= max_retries:
            started_at = datetime.now(UTC)
            start_time = time.perf_counter()
            try:
                if node.timeout_seconds > 0:
                    output = await asyncio.wait_for(
                        node.step.execute(context, inputs),
                        timeout=node.timeout_seconds,
                    )
                else:
                    output = await node.step.execute(context, inputs)

                elapsed = (time.perf_counter() - start_time) * 1000
                completed_at = datetime.now(UTC)
                trace_entries.append(
                    ExecutionTraceEntry(
                        node_id=node_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="success",
                    )
                )
                if _node_span is not None:
                    _node_span.end()
                return NodeResult(
                    node_id=node_id,
                    output=output,
                    success=True,
                    latency_ms=elapsed,
                    retries=retries,
                )
            except Exception as exc:
                last_error = str(exc)
                retries += 1
                if retries <= max_retries:
                    # Exponential backoff with jitter
                    delay = backoff_factor * (2 ** (retries - 1))
                    jitter = random.uniform(0, delay * 0.25)  # noqa: S311
                    backoff = delay + jitter
                    logger.warning(
                        "Node '%s' failed (attempt %d/%d): %s. Retrying in %.1fs",
                        node_id,
                        retries,
                        max_retries + 1,
                        exc,
                        backoff,
                    )
                    await asyncio.sleep(backoff)

        completed_at = datetime.now(UTC)
        trace_entries.append(
            ExecutionTraceEntry(
                node_id=node_id,
                started_at=started_at,
                completed_at=completed_at,
                status="failed",
            )
        )
        if _node_span is not None:
            _node_span.end()
        return NodeResult(
            node_id=node_id,
            success=False,
            error=last_error,
            retries=retries - 1,
        )

    @staticmethod
    def _start_otel_span(name: str, **attributes: Any) -> Any:
        """Backwards-compatible wrapper around the module-level :func:`start_otel_span`."""
        return start_otel_span(name, **attributes)

    @staticmethod
    def _aggregate_usage(correlation_id: str) -> Any:
        """Aggregate usage records for the given correlation ID."""
        try:
            if not get_config().cost_tracking_enabled:
                return None

            summary = default_usage_tracker.get_summary_for_correlation(correlation_id)
            return summary if summary.record_count > 0 else None
        except Exception:  # noqa: BLE001
            return None

    async def _emit_node_result(self, nr: NodeResult, run_id: str) -> None:
        """Emit handler callbacks for a completed node via :meth:`_dispatch`."""
        if self._event_handler is None:
            return
        common = {
            "pipeline_name": self._dag.name,
            "run_id": run_id,
            "node_id": nr.node_id,
        }
        if nr.skipped:
            await self._dispatch("on_node_skip", reason=nr.error or "skipped", **common)
        elif nr.success:
            await self._dispatch("on_node_complete", latency_ms=nr.latency_ms or 0.0, **common)
        else:
            await self._dispatch("on_node_error", error=nr.error or "unknown", **common)

    def _load_for_resume(self, run_id: str, *, approve_pause: bool = False) -> tuple[PipelineContext, set[str], int]:
        """Rebuild context + completed-set from the latest checkpoint.

        Resuming a paused run (checkpoint.paused=True) requires
        ``approve_pause=True``; otherwise a :class:`PipelineError` halts the
        attempt and surfaces the pause reason.
        """
        if self._checkpointer is None:
            raise PipelineError("Cannot resume: pipeline has no checkpointer configured")
        record = self._checkpointer.load_latest(self._dag.name, run_id)
        if record is None:
            raise PipelineError(f"No checkpoint found for run_id='{run_id}'")
        if record.paused and not approve_pause:
            raise PipelineError(
                f"Run '{run_id}' is paused at node '{record.node_id}' "
                f"(reason: {record.pause_reason!r}). Pass approve_pause=True to resume."
            )
        context = PipelineContext(inputs=record.state.get("inputs"))
        for nid, nr_dict in record.state.get("results", {}).items():
            try:
                context.set_node_result(nid, NodeResult.model_validate(nr_dict))
            except Exception:
                logger.warning("Could not restore NodeResult for '%s' on resume", nid)
        # Restore shared state if the run was state-aware.
        saved_state = record.state.get("shared_state")
        if self._state_schema is not None and isinstance(saved_state, dict):
            try:
                context.state = self._state_schema.model_validate(saved_state)
            except Exception:
                logger.warning("Could not restore shared state on resume for run '%s'", run_id)
        return context, set(record.completed_nodes), record.sequence

    def _save_checkpoint(
        self,
        *,
        run_id: str,
        node_id: str,
        sequence: int,
        context: PipelineContext,
        all_results: dict[str, NodeResult],
        paused: bool = False,
        pause_reason: str | None = None,
    ) -> None:
        """Persist state after a successful node. No-op if no checkpointer.

        Only successful (non-skipped) nodes go into ``completed_nodes`` so
        that resume re-attempts the failures.
        """
        if self._checkpointer is None:
            return
        completed_successful = [nid for nid, nr in all_results.items() if nr.success and not nr.skipped]
        state = {
            "inputs": _serialize_value(context.inputs),
            "results": {nid: all_results[nid].model_dump(mode="json") for nid in completed_successful},
            "shared_state": _serialize_value(context.state),
        }
        try:
            self._checkpointer.save(
                CheckpointRecord(
                    pipeline_name=self._dag.name,
                    run_id=run_id,
                    node_id=node_id,
                    sequence=sequence,
                    state=state,
                    completed_nodes=completed_successful,
                    paused=paused,
                    pause_reason=pause_reason,
                )
            )
        except Exception:
            logger.exception("Checkpoint save failed for run '%s' at '%s'", run_id, node_id)

    def _record_audit(
        self,
        *,
        run_id: str,
        node_id: str,
        sequence: int,
        nr: NodeResult,
        inputs_snapshot: dict[str, Any],
        trace_entries: list[ExecutionTraceEntry],
        visit: int = 1,
    ) -> None:
        """Write an audit entry for a node visit. No-op if no audit log.

        Skipped nodes are not recorded — they represent work that did NOT
        happen and would clutter the trail. ``visit`` defaults to 1 for the
        acyclic scheduler and is supplied by the cyclic scheduler.
        """
        if self._audit_log is None or nr.skipped:
            return
        # Pull timing from the trace entry the node just wrote.
        started_at = completed_at = datetime.now(UTC)
        for te in reversed(trace_entries):
            if te.node_id == node_id:
                started_at = te.started_at
                completed_at = te.completed_at
                break
        status: AuditStatus = "success" if nr.success else "error"
        outputs: dict[str, Any] = {"output": _serialize_value(nr.output)} if nr.success else {}
        entry = AuditEntry(
            pipeline_name=self._dag.name,
            run_id=run_id,
            node_id=node_id,
            sequence=sequence,
            visit=visit,
            started_at=started_at,
            completed_at=completed_at,
            latency_ms=nr.latency_ms or 0.0,
            status=status,
            inputs_snapshot={k: _serialize_value(v) for k, v in inputs_snapshot.items()},
            outputs_snapshot=outputs,
            error_message=nr.error if not nr.success else None,
        )
        try:
            self._audit_log.record(entry)
        except Exception:
            logger.exception("Audit log write failed for run '%s' at '%s'", run_id, node_id)

    def _gather_inputs(self, node_id: str, context: PipelineContext) -> dict[str, Any]:
        """Collect inputs for a node from its upstream edges."""
        edges = self._dag.incoming_edges(node_id)
        if not edges:
            return {"input": context.inputs}

        inputs: dict[str, Any] = {}
        for edge in edges:
            upstream_result = context.get_node_result(edge.source)
            if upstream_result is not None:
                raw = upstream_result.output if hasattr(upstream_result, "output") else upstream_result
                if edge.output_key and edge.output_key != "output":
                    if isinstance(raw, dict):
                        value = raw.get(edge.output_key, raw)
                    else:
                        value = getattr(raw, edge.output_key, raw)
                else:
                    value = raw
                inputs[edge.input_key] = value
        return inputs
