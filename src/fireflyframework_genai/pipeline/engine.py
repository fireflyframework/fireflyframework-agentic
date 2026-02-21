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

"""Pipeline execution engine: runs DAGs level-by-level with concurrency."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.pipeline.dag import DAG, FailureStrategy
from fireflyframework_genai.pipeline.result import (
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
    ) -> None:
        self._dag = dag
        self._event_handler = event_handler

    async def run(
        self,
        context: PipelineContext | None = None,
        *,
        inputs: Any = None,
    ) -> PipelineResult:
        """Execute the pipeline.

        Parameters:
            context: Pre-built context, or *None* to create one automatically.
            inputs: Initial inputs (used if *context* is not provided).

        Returns:
            A :class:`PipelineResult` with all node outputs and trace.
        """
        if context is None:
            context = PipelineContext(inputs=inputs)

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
        all_results: dict[str, NodeResult] = {}
        pipeline_start = time.perf_counter()

        failed_nodes: set[str] = set()

        # Eager scheduling: as soon as all of a node's dependencies are
        # resolved we can schedule it, rather than waiting for the entire
        # level to finish.  This is a significant improvement when nodes
        # within a level have uneven latencies.
        pending: set[str] = set()
        for level in levels:
            pending.update(level)

        completed: set[str] = set()
        running: dict[str, asyncio.Task[NodeResult]] = {}
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
                        task = asyncio.create_task(
                            self._execute_node(nid, context, trace_entries, failed_nodes),
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
        )

    async def _execute_node(
        self,
        node_id: str,
        context: PipelineContext,
        trace_entries: list[ExecutionTraceEntry],
        failed_nodes: set[str] | None = None,
    ) -> NodeResult:
        """Execute a single node with retries and condition gating."""
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

        # Gather inputs from upstream edges
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
        """Start an OTel span if observability is enabled, else return *None*."""
        try:
            from fireflyframework_genai.config import get_config

            if not get_config().observability_enabled:
                return None
            from opentelemetry import trace

            return trace.get_tracer("fireflyframework_genai").start_span(
                name,
                attributes={f"firefly.{k}": str(v) for k, v in attributes.items()},
            )
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _aggregate_usage(correlation_id: str) -> Any:
        """Aggregate usage records for the given correlation ID."""
        try:
            from fireflyframework_genai.config import get_config

            if not get_config().cost_tracking_enabled:
                return None

            from fireflyframework_genai.observability.usage import default_usage_tracker

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
