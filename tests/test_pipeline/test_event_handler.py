"""Tests for pipeline event handling — PipelineEventHandler protocol."""

from __future__ import annotations

from dataclasses import dataclass, field

from fireflyframework_agentic.pipeline.dag import DAG, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine, PipelineEventHandler


class _EchoStep:
    def __init__(self, prefix: str = ""):
        self._prefix = prefix

    async def execute(self, context, inputs):
        val = inputs.get("input", "")
        return f"{self._prefix}{val}"


@dataclass
class _TestEventHandler:
    """Collects pipeline events for assertions."""

    starts: list[str] = field(default_factory=list)
    completes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)
    pipeline_done: list[tuple[str, bool]] = field(default_factory=list)

    async def on_node_start(self, node_id: str, pipeline_name: str) -> None:
        self.starts.append(node_id)

    async def on_node_complete(self, node_id: str, pipeline_name: str, latency_ms: float) -> None:
        self.completes.append(node_id)

    async def on_node_error(self, node_id: str, pipeline_name: str, error: str) -> None:
        self.errors.append(node_id)

    async def on_node_skip(self, node_id: str, pipeline_name: str, reason: str) -> None:
        self.skips.append(node_id)

    async def on_pipeline_complete(self, pipeline_name: str, success: bool, duration_ms: float) -> None:
        self.pipeline_done.append((pipeline_name, success))


class TestPipelineEventHandler:
    async def test_events_on_success(self):
        from fireflyframework_agentic.pipeline.dag import DAGEdge

        handler = _TestEventHandler()
        dag = DAG("evt-test")
        dag.add_node(DAGNode(node_id="a", step=_EchoStep("A:")))
        dag.add_node(DAGNode(node_id="b", step=_EchoStep("B:")))
        dag.add_edge(DAGEdge(source="a", target="b"))
        engine = PipelineEngine(dag, event_handler=handler)
        result = await engine.run(inputs="hello")
        assert result.success is True
        assert "a" in handler.starts
        assert "b" in handler.starts
        assert "a" in handler.completes
        assert "b" in handler.completes
        assert ("evt-test", True) in handler.pipeline_done

    async def test_events_on_failure(self):
        class FailStep:
            async def execute(self, context, inputs):
                raise RuntimeError("boom")

        handler = _TestEventHandler()
        dag = DAG("fail-evt")
        dag.add_node(DAGNode(node_id="fail", step=FailStep()))
        engine = PipelineEngine(dag, event_handler=handler)
        result = await engine.run(inputs="test")
        assert result.success is False
        assert "fail" in handler.errors
        assert ("fail-evt", False) in handler.pipeline_done

    async def test_events_on_skip(self):
        handler = _TestEventHandler()
        dag = DAG("skip-evt")
        dag.add_node(
            DAGNode(
                node_id="skipped",
                step=_EchoStep(),
                condition=lambda ctx: False,
            )
        )
        engine = PipelineEngine(dag, event_handler=handler)
        await engine.run(inputs="test")
        assert "skipped" in handler.skips

    def test_pipeline_event_handler_is_protocol(self):
        assert isinstance(_TestEventHandler(), PipelineEventHandler)


class TestPipelineEventHandlerEdgeCases:
    async def test_no_handler_still_works(self):
        dag = DAG("no-handler")
        dag.add_node(DAGNode(node_id="a", step=_EchoStep("A:")))
        engine = PipelineEngine(dag, event_handler=None)
        result = await engine.run(inputs="test")
        assert result.success is True

    async def test_handler_exception_does_not_crash_pipeline(self):
        class _BrokenHandler:
            async def on_node_start(self, node_id, pipeline_name):
                raise RuntimeError("handler boom")

            async def on_node_complete(self, node_id, pipeline_name, latency_ms):
                raise RuntimeError("handler boom")

            async def on_pipeline_complete(self, pipeline_name, success, duration_ms):
                raise RuntimeError("handler boom")

        dag = DAG("broken-handler")
        dag.add_node(DAGNode(node_id="a", step=_EchoStep("A:")))
        engine = PipelineEngine(dag, event_handler=_BrokenHandler())
        result = await engine.run(inputs="test")
        # Pipeline should still succeed despite handler errors
        assert result.success is True
