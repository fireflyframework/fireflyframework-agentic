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

"""The middleware error hook: failures now reach on_error.

Before this, the chain ran only before_run/after_run, so a failing model run
left observability spans open and the circuit breaker could never count a
failure (its on_error was never called). Now FireflyAgent.run/run_sync/run_stream
invoke the chain's run_error on failure.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.models.function import FunctionModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.builtin_middleware import ObservabilityMiddleware
from fireflyframework_agentic.agents.middleware import MiddlewareChain, MiddlewareContext
from fireflyframework_agentic.resilience import CircuitBreakerMiddleware, CircuitBreakerOpenError


def _boom(messages: Any, info: Any) -> Any:
    raise RuntimeError("model down")


@pytest.mark.asyncio
async def test_on_error_fires_and_circuit_breaker_opens():
    errors: list[BaseException] = []

    class RecordingMW:
        async def before_run(self, context: MiddlewareContext) -> None:
            pass

        async def on_error(self, context: MiddlewareContext, exc: BaseException) -> None:
            errors.append(exc)

    breaker = CircuitBreakerMiddleware(failure_threshold=2)
    agent = FireflyAgent(
        "cb-agent",
        model=FunctionModel(_boom),
        middleware=[RecordingMW(), breaker],
        default_middleware=False,
        auto_register=False,
    )

    # Two real failures: each must reach on_error and be counted by the breaker.
    for _ in range(2):
        with pytest.raises(RuntimeError, match="model down"):
            await agent.run("hello")
    assert len(errors) == 2

    # The breaker is now OPEN, so the next call fast-fails before the model.
    with pytest.raises(CircuitBreakerOpenError):
        await agent.run("hello")


@pytest.mark.asyncio
async def test_run_with_reasoning_also_fires_on_error():
    """The error lifecycle is uniform: run_with_reasoning fires on_error too."""
    errors: list[BaseException] = []

    class RecordingMW:
        async def before_run(self, context: MiddlewareContext) -> None:
            pass

        async def on_error(self, context: MiddlewareContext, exc: BaseException) -> None:
            errors.append(exc)

    class _BoomPattern:
        name = "boom"

        async def execute(self, agent: Any, prompt: Any, **kwargs: Any) -> Any:
            raise RuntimeError("pattern down")

    agent = FireflyAgent("rwr", model="test", middleware=[RecordingMW()], default_middleware=False, auto_register=False)
    with pytest.raises(RuntimeError, match="pattern down"):
        await agent.run_with_reasoning(_BoomPattern(), "x")
    assert len(errors) == 1


@pytest.mark.asyncio
async def test_run_error_invokes_hooks_in_reverse_and_suppresses_secondary_errors():
    order: list[str] = []

    class A:
        async def on_error(self, context: MiddlewareContext, exc: BaseException) -> None:
            order.append("A")

    class B:
        async def on_error(self, context: MiddlewareContext, exc: BaseException) -> None:
            order.append("B")
            raise RuntimeError("secondary error in cleanup")  # must not mask the original

    chain = MiddlewareChain([A(), B()])
    await chain.run_error(MiddlewareContext(agent_name="x", prompt="p"), ValueError("orig"))
    assert order == ["B", "A"]  # reverse order, and B's raise was suppressed


@pytest.mark.asyncio
async def test_observability_span_is_ended_on_error():
    mw = ObservabilityMiddleware()
    ctx = MiddlewareContext(agent_name="obs", prompt="p", method="run")
    await mw.before_run(ctx)
    assert ctx.metadata.get("_otel_span") is not None
    await mw.on_error(ctx, RuntimeError("boom"))
    assert "_otel_span" not in ctx.metadata  # span popped and ended, not leaked
