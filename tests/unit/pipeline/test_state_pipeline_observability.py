# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Phase-3b tests: StatePipelineEventHandler callbacks + OTel spans for state pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

import fireflyframework_agentic.pipeline.engine as engine_module
from fireflyframework_agentic.pipeline import (
    FileCheckpointer,
    PipelineBuilder,
    Send,
    extend,
)


@dataclass
class RecordingHandler:
    """A test handler that captures every callback in order."""

    events: list[tuple] = field(default_factory=list)

    async def on_pipeline_start(self, pipeline_name: str, run_id: str) -> None:
        self.events.append(("pipeline_start", pipeline_name, run_id))

    async def on_node_start(self, pipeline_name: str, run_id: str, node_id: str, visit: int) -> None:
        self.events.append(("node_start", node_id, visit))

    async def on_node_complete(self, pipeline_name: str, run_id: str, node_id: str, latency_ms: float) -> None:
        self.events.append(("node_complete", node_id))

    async def on_node_error(self, pipeline_name: str, run_id: str, node_id: str, error: str) -> None:
        self.events.append(("node_error", node_id, error))

    async def on_pipeline_complete(self, pipeline_name: str, run_id: str, success: bool, duration_ms: float) -> None:
        self.events.append(("pipeline_complete", success))


class LinearState(BaseModel):
    log: Annotated[list[str], extend] = []


class LoopState(BaseModel):
    counter: int = 0


# --- linear pipeline event ordering -----------------------------------------


@pytest.mark.asyncio
async def test_linear_pipeline_emits_events_in_order() -> None:
    async def a(state: LinearState) -> dict:
        return {"log": ["a"]}

    async def b(state: LinearState) -> dict:
        return {"log": ["b"]}

    async def c(state: LinearState) -> dict:
        return {"log": ["c"]}

    handler = RecordingHandler()
    pipeline = (
        PipelineBuilder("linear", state=LinearState, event_handler=handler)
        .add_node(a)
        .add_node(b)
        .add_node(c)
        .chain(a, b, c)
        .build()
    )
    await pipeline.invoke(LinearState())

    event_kinds = [e[0] for e in handler.events]
    assert event_kinds == [
        "pipeline_start",
        "node_start",
        "node_complete",
        "node_start",
        "node_complete",
        "node_start",
        "node_complete",
        "pipeline_complete",
    ]
    assert handler.events[-1] == ("pipeline_complete", True)


# --- failure path ----------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_emits_node_error_and_pipeline_complete_false() -> None:
    async def boom(state: LinearState) -> dict:
        raise RuntimeError("nope")

    handler = RecordingHandler()
    pipeline = PipelineBuilder("fail", state=LinearState, event_handler=handler).add_node(boom).build()
    result = await pipeline.invoke(LinearState())
    assert not result.success

    assert ("node_error", "boom", "nope") in handler.events
    assert ("pipeline_complete", False) in handler.events
    # node_error fires BEFORE pipeline_complete
    err_idx = handler.events.index(("node_error", "boom", "nope"))
    done_idx = handler.events.index(("pipeline_complete", False))
    assert err_idx < done_idx


# --- cyclic graph visit count ----------------------------------------------


@pytest.mark.asyncio
async def test_cyclic_graph_increments_visit_count() -> None:
    async def step(state: LoopState) -> dict:
        return {"counter": state.counter + 1}

    async def done(state: LoopState) -> dict:
        return {}

    def route(state: LoopState) -> str:
        return "done" if state.counter >= 3 else "step"

    handler = RecordingHandler()
    pipeline = (
        PipelineBuilder("loop", state=LoopState, event_handler=handler)
        .add_node(step)
        .add_node(done)
        .branch(step, route)
        .build()
    )
    await pipeline.invoke(LoopState())

    step_starts = [e for e in handler.events if e[0] == "node_start" and e[1] == "step"]
    assert [e[2] for e in step_starts] == [1, 2, 3]


# --- fan-out via Send -------------------------------------------------------


class FanOutState(BaseModel):
    items: list[str] = []
    results: Annotated[list[str], extend] = []
    item: str | None = None


@pytest.mark.asyncio
async def test_fanout_emits_per_send_node_events() -> None:
    async def planner(state: FanOutState) -> dict:
        return {}

    async def worker(state: FanOutState) -> dict:
        return {"results": [f"r:{state.item}"]}

    async def collect(state: FanOutState) -> dict:
        return {}

    def dispatch(state: FanOutState) -> list[Send]:
        return [Send("worker", {"item": x}) for x in state.items]

    handler = RecordingHandler()
    pipeline = (
        PipelineBuilder("fanout", state=FanOutState, event_handler=handler)
        .add_node(planner)
        .add_node(worker)
        .add_node(collect)
        .add_edge(worker, collect)
        .branch(planner, dispatch)
        .build()
    )
    await pipeline.invoke(FanOutState(items=["a", "b", "c"]))

    worker_starts = [e for e in handler.events if e[0] == "node_start" and e[1] == "worker"]
    worker_completes = [e for e in handler.events if e[0] == "node_complete" and e[1] == "worker"]
    assert len(worker_starts) == 3
    assert len(worker_completes) == 3
    # Visits are 1, 2, 3 across the three Sends.
    assert sorted(e[2] for e in worker_starts) == [1, 2, 3]


# --- resume from a checkpoint ----------------------------------------------


class BuildState(BaseModel):
    requirements: str
    spec: str | None = None
    code: str | None = None
    deploy: str | None = None


@pytest.mark.asyncio
async def test_resume_emits_events_only_for_remaining_nodes(tmp_path: Path) -> None:
    fail_once = {"flag": False}

    async def arch(state: BuildState) -> dict:
        return {"spec": "s"}

    async def dev(state: BuildState) -> dict:
        return {"code": "c"}

    async def deploy(state: BuildState) -> dict:
        if not fail_once["flag"]:
            fail_once["flag"] = True
            raise RuntimeError("blip")
        return {"deploy": "ok"}

    handler1 = RecordingHandler()
    handler2 = RecordingHandler()
    ckpt = FileCheckpointer(tmp_path)

    # First run uses handler1; deploy fails.
    p1 = (
        PipelineBuilder("factory", state=BuildState, checkpointer=ckpt, event_handler=handler1)
        .add_node(arch)
        .add_node(dev)
        .add_node(deploy)
        .chain(arch, dev, deploy)
        .build()
    )
    first = await p1.invoke(BuildState(requirements="x"))
    assert not first.success

    # Second run uses handler2 and resumes; only deploy should run.
    p2 = (
        PipelineBuilder("factory", state=BuildState, checkpointer=ckpt, event_handler=handler2)
        .add_node(arch)
        .add_node(dev)
        .add_node(deploy)
        .chain(arch, dev, deploy)
        .build()
    )
    second = await p2.invoke(run_id=first.run_id)
    assert second.success

    nodes_started_on_resume = [e[1] for e in handler2.events if e[0] == "node_start"]
    assert nodes_started_on_resume == ["deploy"]


# --- partial handler --------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_handler_only_implementing_node_error_works() -> None:
    captured: list[str] = []

    class JustErrors:
        async def on_node_error(self, pipeline_name, run_id, node_id, error):
            captured.append(f"{node_id}:{error}")

    async def boom(state: LinearState) -> dict:
        raise RuntimeError("kaboom")

    pipeline = PipelineBuilder("partial", state=LinearState, event_handler=JustErrors()).add_node(boom).build()
    result = await pipeline.invoke(LinearState())
    assert not result.success
    assert captured == ["boom:kaboom"]


# --- handler exception is swallowed ----------------------------------------


@pytest.mark.asyncio
async def test_handler_exception_does_not_break_pipeline() -> None:
    class CrashyHandler:
        async def on_node_complete(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("handler crashed")

    async def step(state: LinearState) -> dict:
        return {"log": ["ran"]}

    pipeline = PipelineBuilder("crash", state=LinearState, event_handler=CrashyHandler()).add_node(step).build()
    result = await pipeline.invoke(LinearState())
    assert result.success
    assert result.state.log == ["ran"]


# --- OTel spans -------------------------------------------------------------


@pytest.mark.asyncio
async def test_otel_spans_emitted_per_pipeline_and_per_node(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the observability path to fire even if the config disables it by default.
    mock_config = MagicMock(observability_enabled=True)
    monkeypatch.setattr(engine_module, "get_config", lambda: mock_config)

    # Stub the OTel tracer so we can record span starts.
    started: list[tuple[str, dict]] = []
    mock_tracer = MagicMock()

    def fake_start_span(name: str, attributes: dict | None = None) -> MagicMock:
        started.append((name, attributes or {}))
        return MagicMock()

    mock_tracer.start_span.side_effect = fake_start_span
    mock_trace = MagicMock()
    mock_trace.get_tracer.return_value = mock_tracer
    monkeypatch.setattr(engine_module, "otel_trace", mock_trace)

    async def a(state: LinearState) -> dict:
        return {}

    async def b(state: LinearState) -> dict:
        return {}

    pipeline = PipelineBuilder("otel", state=LinearState).add_node(a).add_node(b).chain(a, b).build()
    await pipeline.invoke(LinearState())

    names = [n for n, _ in started]
    assert "pipeline.state.otel" in names
    assert "pipeline.state.node.a" in names
    assert "pipeline.state.node.b" in names

    # Spot-check attributes: pipeline span carries run_id, node span carries visit.
    pipeline_attrs = next(attrs for name, attrs in started if name == "pipeline.state.otel")
    assert "firefly.run_id" in pipeline_attrs
    node_a_attrs = next(attrs for name, attrs in started if name == "pipeline.state.node.a")
    assert node_a_attrs.get("firefly.visit") == "1"
