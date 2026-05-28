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
import logging
import random
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

try:
    from opentelemetry import trace as otel_trace
except ImportError:  # pragma: no cover - optional dep
    otel_trace = None  # type: ignore[assignment]

from fireflyframework_agentic.config import get_config
from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.observability.usage import default_usage_tracker
from fireflyframework_agentic.pipeline.audit import AuditEntry, AuditLog, AuditStatus
from fireflyframework_agentic.pipeline.checkpoint import Checkpointer, CheckpointRecord
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.dag import DAG, FailureStrategy
from fireflyframework_agentic.pipeline.result import (
    ExecutionTraceEntry,
    NodeResult,
    PipelineResult,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class PipelineEventHandler(Protocol):
    """Protocol for pipeline progress callbacks.

    Implement any subset of these methods to receive notifications
    when pipeline nodes start, complete, or fail.
    """

    async def on_node_start(self, node_id: str, pipeline_name: str) -> None:
        """Called when a node begins execution."""
        ...

    async def on_node_complete(self, node_id: str, pipeline_name: str, latency_ms: float) -> None:
        """Called when a node completes successfully."""
        ...

    async def on_node_error(self, node_id: str, pipeline_name: str, error: str) -> None:
        """Called when a node fails (after all retries exhausted)."""
        ...

    async def on_node_skip(self, node_id: str, pipeline_name: str, reason: str) -> None:
        """Called when a node is skipped."""
        ...

    async def on_pipeline_complete(self, pipeline_name: str, success: bool, duration_ms: float) -> None:
        """Called when the entire pipeline finishes."""
        ...


@runtime_checkable
class StatePipelineEventHandler(Protocol):
    """Protocol for state-pipeline progress callbacks.

    Mirrors :class:`PipelineEventHandler` but every callback carries the
    ``run_id`` so ops can correlate events across resumes, and
    ``on_node_start`` carries a ``visit`` counter so cyclic graphs are
    distinguishable per iteration. There is no ``on_node_skip`` — state
    pipelines abort on failure rather than skipping downstream nodes.

    Implement any subset of methods; missing ones are no-ops.
    """

    async def on_pipeline_start(self, pipeline_name: str, run_id: str) -> None:
        """Called once when ``invoke`` begins."""
        ...

    async def on_node_start(self, pipeline_name: str, run_id: str, node_id: str, visit: int) -> None:
        """Called each time a node is about to run. ``visit`` starts at 1
        and increments per re-entry (cycles, Send fan-out)."""
        ...

    async def on_node_complete(self, pipeline_name: str, run_id: str, node_id: str, latency_ms: float) -> None:
        """Called when a node completes successfully."""
        ...

    async def on_node_error(self, pipeline_name: str, run_id: str, node_id: str, error: str) -> None:
        """Called when a node raises an exception."""
        ...

    async def on_node_pause(self, pipeline_name: str, run_id: str, node_id: str, reason: str) -> None:
        """Called when a node returns :class:`Pause`, halting the pipeline
        until an external ``invoke(run_id=..., approve_pause=True)`` resumes it."""
        ...

    async def on_pipeline_complete(self, pipeline_name: str, run_id: str, success: bool, duration_ms: float) -> None:
        """Called once when ``invoke`` returns."""
        ...


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
        event_handler: PipelineEventHandler | None = None,
        checkpointer: Checkpointer | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._dag = dag
        self._event_handler = event_handler
        self._checkpointer = checkpointer
        self._audit_log = audit_log

    async def run(
        self,
        context: PipelineContext | None = None,
        *,
        inputs: Any = None,
        run_id: str | None = None,
    ) -> PipelineResult:
        """Execute the pipeline.

        Parameters:
            context: Pre-built context, or *None* to create one automatically.
            inputs: Initial inputs (used if *context* is not provided).
            run_id: Identifier for this run. When given alone (no ``context``
                and no ``inputs``), the engine loads the latest checkpoint for
                that run and resumes from after the last completed node.
                Requires a checkpointer to be configured.

        Returns:
            A :class:`PipelineResult` with all node outputs, trace, and
            ``run_id`` (use to resume later).
        """
        if run_id is not None and context is None and inputs is None:
            resume_run_id: str = run_id
            context, pre_completed, sequence_start = self._load_for_resume(resume_run_id)
            all_results: dict[str, NodeResult] = {
                nid: nr
                for nid in pre_completed
                if (nr := context.get_node_result(nid)) is not None and isinstance(nr, NodeResult)
            }
        else:
            if context is None:
                context = PipelineContext(inputs=inputs)
            pre_completed = set()
            sequence_start = 0
            all_results = {}

        if run_id is None:
            run_id = uuid.uuid4().hex[:12]

        # Observability: pipeline-level span
        _pipeline_span = self._start_otel_span(
            f"pipeline.{self._dag.name}",
            pipeline=self._dag.name,
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

        def _ready(nid: str) -> bool:
            """A node is ready when all its upstream deps have completed."""
            edges = self._dag.incoming_edges(nid)
            return all(e.source in completed for e in edges)

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
                            self._execute_node(nid, context, trace_entries, failed_nodes, inputs=gathered),
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
                await self._emit_node_result(nr)

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
                if nr.success and not nr.skipped:
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
        if self._event_handler is not None and hasattr(self._event_handler, "on_pipeline_complete"):
            with contextlib.suppress(Exception):
                await self._event_handler.on_pipeline_complete(
                    self._dag.name,
                    success,
                    pipeline_elapsed,
                )

        # Aggregate usage across all nodes for this pipeline run
        usage_summary = self._aggregate_usage(context.correlation_id)

        if _pipeline_span is not None:
            _pipeline_span.end()

        return PipelineResult(
            pipeline_name=self._dag.name,
            outputs=all_results,
            final_output=final_output,
            execution_trace=trace_entries,
            total_duration_ms=pipeline_elapsed,
            success=success,
            usage=usage_summary,
            run_id=run_id,
        )

    async def _execute_node(
        self,
        node_id: str,
        context: PipelineContext,
        trace_entries: list[ExecutionTraceEntry],
        failed_nodes: set[str] | None = None,
        *,
        inputs: dict[str, Any] | None = None,
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

        # Emit node start event
        if self._event_handler is not None and hasattr(self._event_handler, "on_node_start"):
            with contextlib.suppress(Exception):
                await self._event_handler.on_node_start(node_id, self._dag.name)

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

    async def _emit_node_result(self, nr: NodeResult) -> None:
        """Emit event handler callbacks for a completed node."""
        if self._event_handler is None:
            return
        try:
            if nr.skipped and hasattr(self._event_handler, "on_node_skip"):
                await self._event_handler.on_node_skip(
                    nr.node_id,
                    self._dag.name,
                    nr.error or "skipped",
                )
            elif nr.success and hasattr(self._event_handler, "on_node_complete"):
                await self._event_handler.on_node_complete(
                    nr.node_id,
                    self._dag.name,
                    nr.latency_ms or 0.0,
                )
            elif not nr.success and hasattr(self._event_handler, "on_node_error"):
                await self._event_handler.on_node_error(
                    nr.node_id,
                    self._dag.name,
                    nr.error or "unknown",
                )
        except Exception:  # noqa: BLE001
            pass

    def _load_for_resume(self, run_id: str) -> tuple[PipelineContext, set[str], int]:
        """Rebuild context + completed-set from the latest checkpoint."""
        if self._checkpointer is None:
            raise PipelineError("Cannot resume: pipeline has no checkpointer configured")
        record = self._checkpointer.load_latest(self._dag.name, run_id)
        if record is None:
            raise PipelineError(f"No checkpoint found for run_id='{run_id}'")
        context = PipelineContext(inputs=record.state.get("inputs"))
        for nid, nr_dict in record.state.get("results", {}).items():
            try:
                context.set_node_result(nid, NodeResult.model_validate(nr_dict))
            except Exception:
                logger.warning("Could not restore NodeResult for '%s' on resume", nid)
        return context, set(record.completed_nodes), record.sequence

    def _save_checkpoint(
        self,
        *,
        run_id: str,
        node_id: str,
        sequence: int,
        context: PipelineContext,
        all_results: dict[str, NodeResult],
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
    ) -> None:
        """Write an audit entry for a node visit. No-op if no audit log.

        Skipped nodes are not recorded — they represent work that did NOT
        happen and would clutter the trail.
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
            visit=1,
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
