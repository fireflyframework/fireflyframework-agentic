"""Tests for pipeline/builder.py, pipeline/steps.py, and pipeline/context.py."""

from __future__ import annotations

from typing import Any

from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.steps import (
    CallableStep,
    FanInStep,
    FanOutStep,
)


class _EchoStep:
    """Minimal step that echoes input with a prefix."""

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        val = inputs.get("input", context.inputs)
        return f"{self._prefix}{val}"


class TestPipelineBuilder:
    async def test_build_and_run_linear(self) -> None:
        engine = (
            PipelineBuilder("test")
            .add_node("a", _EchoStep("A:"))
            .add_node("b", _EchoStep("B:"))
            .add_edge("a", "b")
            .build()
        )
        result = await engine.run(inputs="hello")
        assert result.success is True

    async def test_chain_shorthand(self) -> None:
        engine = (
            PipelineBuilder("chain")
            .add_node("x", _EchoStep())
            .add_node("y", _EchoStep())
            .add_node("z", _EchoStep())
            .chain("x", "y", "z")
            .build()
        )
        result = await engine.run(inputs="hi")
        assert result.success is True

    def test_build_dag_only(self) -> None:
        dag = PipelineBuilder("dag").add_node("n1", _EchoStep()).build_dag()
        assert "n1" in dag._nodes

    async def test_async_callable_auto_wrapped(self) -> None:
        async def my_step(context: PipelineContext, inputs: dict[str, Any]) -> str:
            return "callable"

        engine = PipelineBuilder("auto").add_node("c", my_step).build()
        result = await engine.run(inputs="x")
        assert result.success is True


class TestCallableStep:
    async def test_executes_callable(self) -> None:
        async def fn(ctx: PipelineContext, inputs: dict[str, Any]) -> str:
            return "done"

        step = CallableStep(fn)
        ctx = PipelineContext(inputs="x")
        result = await step.execute(ctx, {"input": "x"})
        assert result == "done"


class TestFanOutStep:
    async def test_splits_input(self) -> None:
        step = FanOutStep(lambda x: x.split(","))
        ctx = PipelineContext(inputs="a,b,c")
        result = await step.execute(ctx, {"input": "a,b,c"})
        assert result == ["a", "b", "c"]


class TestFanInStep:
    async def test_merges_inputs(self) -> None:
        step = FanInStep()
        ctx = PipelineContext(inputs="")
        result = await step.execute(ctx, {"a": 1, "b": 2})
        assert set(result) == {1, 2}

    async def test_custom_merge_fn(self) -> None:
        step = FanInStep(merge_fn=lambda items: sum(items))
        ctx = PipelineContext(inputs="")
        result = await step.execute(ctx, {"a": 10, "b": 20})
        assert result == 30


class TestPipelineContext:
    def test_default_values(self) -> None:
        ctx = PipelineContext(inputs="test")
        assert ctx.inputs == "test"
        assert ctx.correlation_id is not None
        assert ctx.metadata == {}
        assert ctx.memory is None
