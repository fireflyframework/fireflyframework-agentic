"""Layer 1B of the unification (#245): unified EventHandler protocol.

PipelineEngine now uses a single :class:`EventHandler` protocol that
includes ``run_id`` and ``visit`` on every callback, plus
``on_pipeline_start`` and ``on_node_pause``. Dispatch is by parameter name
via signature inspection, so legacy :class:`PipelineEventHandler`
implementations (port-based, run_id-unaware) still receive the events
they declared.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine


class _Echo:
    async def execute(self, ctx, inputs):
        return inputs.get("input", "")


def _two_node_dag() -> DAG:
    dag = DAG("dispatch")
    dag.add_node(DAGNode(node_id="a", step=_Echo()))
    dag.add_node(DAGNode(node_id="b", step=_Echo()))
    dag.add_edge(DAGEdge(source="a", target="b"))
    return dag


# ---- Unified (rich) handler ------------------------------------------------


@dataclass
class _UnifiedHandler:
    """Implements the full EventHandler shape (run_id + visit aware)."""

    started: list[tuple[str, str]] = field(default_factory=list)  # (pipeline, run_id)
    node_starts: list[tuple[str, int]] = field(default_factory=list)  # (node_id, visit)
    node_completes: list[str] = field(default_factory=list)
    completed: list[tuple[str, bool]] = field(default_factory=list)  # (run_id, success)

    async def on_pipeline_start(self, pipeline_name: str, run_id: str) -> None:
        self.started.append((pipeline_name, run_id))

    async def on_node_start(self, pipeline_name, run_id, node_id, visit):
        self.node_starts.append((node_id, visit))

    async def on_node_complete(self, pipeline_name, run_id, node_id, latency_ms):
        self.node_completes.append(node_id)

    async def on_pipeline_complete(self, pipeline_name, run_id, success, duration_ms):
        self.completed.append((run_id, success))


async def test_unified_handler_receives_pipeline_start_with_run_id():
    handler = _UnifiedHandler()
    engine = PipelineEngine(_two_node_dag(), event_handler=handler)
    result = await engine.run(inputs="x")
    assert handler.started == [("dispatch", result.run_id)]


async def test_unified_handler_receives_visit_on_node_start():
    handler = _UnifiedHandler()
    engine = PipelineEngine(_two_node_dag(), event_handler=handler)
    await engine.run(inputs="x")
    # Port-based pipelines always emit visit=1 until cycles arrive in a later layer.
    assert handler.node_starts == [("a", 1), ("b", 1)]


async def test_unified_handler_receives_pipeline_complete_with_run_id():
    handler = _UnifiedHandler()
    engine = PipelineEngine(_two_node_dag(), event_handler=handler)
    result = await engine.run(inputs="x")
    assert handler.completed == [(result.run_id, True)]


# ---- Legacy PipelineEventHandler (run_id-unaware) --------------------------


@dataclass
class _LegacyHandler:
    """Implements the legacy PipelineEventHandler signatures (no run_id)."""

    starts: list[str] = field(default_factory=list)
    completes: list[str] = field(default_factory=list)
    pipeline_done: list[tuple[str, bool]] = field(default_factory=list)

    async def on_node_start(self, node_id: str, pipeline_name: str) -> None:
        self.starts.append(node_id)

    async def on_node_complete(self, node_id: str, pipeline_name: str, latency_ms: float) -> None:
        self.completes.append(node_id)

    async def on_pipeline_complete(self, pipeline_name: str, success: bool, duration_ms: float) -> None:
        self.pipeline_done.append((pipeline_name, success))


async def test_legacy_handler_still_works_without_run_id():
    """The engine drops run_id/visit when the handler doesn't declare them."""
    handler = _LegacyHandler()
    engine = PipelineEngine(_two_node_dag(), event_handler=handler)
    result = await engine.run(inputs="x")
    assert result.success
    assert handler.starts == ["a", "b"]
    assert handler.completes == ["a", "b"]
    assert handler.pipeline_done == [("dispatch", True)]


async def test_legacy_handler_without_on_pipeline_start_is_fine():
    """Legacy handlers don't have on_pipeline_start; engine just skips it."""
    handler = _LegacyHandler()
    assert not hasattr(handler, "on_pipeline_start")
    engine = PipelineEngine(_two_node_dag(), event_handler=handler)
    # Should not raise — missing methods are no-ops.
    await engine.run(inputs="x")


# ---- Mixed handler (some legacy methods, some new) ------------------------


@dataclass
class _MixedHandler:
    """Some methods unified-signature, some legacy. Both should fire."""

    pipeline_starts_with_run_id: list[str] = field(default_factory=list)
    legacy_node_starts: list[str] = field(default_factory=list)

    # New (rich) signature
    async def on_pipeline_start(self, pipeline_name: str, run_id: str) -> None:
        self.pipeline_starts_with_run_id.append(run_id)

    # Legacy signature — engine should still call it without run_id/visit
    async def on_node_start(self, node_id: str, pipeline_name: str) -> None:
        self.legacy_node_starts.append(node_id)


async def test_mixed_handler_dispatches_correctly():
    handler = _MixedHandler()
    engine = PipelineEngine(_two_node_dag(), event_handler=handler)
    result = await engine.run(inputs="x")
    assert handler.pipeline_starts_with_run_id == [result.run_id]
    assert handler.legacy_node_starts == ["a", "b"]


# ---- Exception safety ------------------------------------------------------


async def test_handler_exception_does_not_break_pipeline():
    class _Broken:
        async def on_pipeline_start(self, pipeline_name: str, run_id: str) -> None:
            raise RuntimeError("boom in start")

        async def on_node_start(self, pipeline_name, run_id, node_id, visit):
            raise RuntimeError("boom in node start")

        async def on_pipeline_complete(self, pipeline_name, run_id, success, duration_ms):
            raise RuntimeError("boom in complete")

    engine = PipelineEngine(_two_node_dag(), event_handler=_Broken())
    result = await engine.run(inputs="x")
    assert result.success
