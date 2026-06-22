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

"""SP-10: native pydantic-ai OpenTelemetry instrumentation.

When ``native_instrumentation_enabled`` is on, every FireflyAgent enables
pydantic-ai's native instrumentation via ``capabilities=[Instrumentation(...)]``
(the warning-free path — never the deprecated ``Agent(instrument=)``). The rich
GenAI-convention spans (``chat`` / ``execute_tool`` / ``invoke_agent``) nest
UNDER the framework's ``agent.{name}`` span because ObservabilityMiddleware now
activates its span in the OTel context. Content is stripped by default (privacy).
"""

from __future__ import annotations

import json
import warnings
from typing import Any

import pytest
from opentelemetry import trace as ot
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai._warnings import PydanticAIDeprecationWarning
from pydantic_ai.capabilities import HandleDeferredToolCalls, Instrumentation
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.builtin_middleware import ObservabilityMiddleware
from fireflyframework_agentic.agents.middleware import MiddlewareContext
from fireflyframework_agentic.config import FireflyAgenticConfig, reset_config
from fireflyframework_agentic.tools.decorators import firefly_tool


@firefly_tool("weather", description="Get the weather for a city", auto_register=False)
async def weather(city: str) -> str:
    return f"sunny in {city}"


def _tool_then_text(tool_name: str = "weather", args: dict[str, Any] | None = None) -> FunctionModel:
    state = {"n": 0}

    def fn(messages: Any, info: Any) -> ModelResponse:
        state["n"] += 1
        if state["n"] == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name=tool_name, args=args or {"city": "Paris"}, tool_call_id="c1")]
            )
        return ModelResponse(parts=[TextPart("It is sunny in Paris.")])

    return FunctionModel(fn)


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    """An in-memory SDK exporter wired to the (global) tracer provider.

    The framework's ObservabilityMiddleware uses the global tracer, and native
    instrumentation defaults to the global provider too, so a single exporter
    captures both. The global provider can only be set once per process: reuse it
    if an SDK provider is already installed, otherwise install one.
    """
    exporter = InMemorySpanExporter()
    current = ot.get_tracer_provider()
    provider = current if isinstance(current, TracerProvider) else TracerProvider()
    if provider is not current:
        ot.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def native_on(monkeypatch: pytest.MonkeyPatch, span_exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    monkeypatch.setenv("FIREFLY_AGENTIC_NATIVE_INSTRUMENTATION_ENABLED", "true")
    monkeypatch.setenv("FIREFLY_AGENTIC_INSTRUMENTATION_INCLUDE_CONTENT", "false")
    reset_config()
    span_exporter.clear()
    yield span_exporter
    reset_config()


def _ops(spans: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for s in spans:
        op = (s.attributes or {}).get("gen_ai.operation.name")
        if op:
            out.setdefault(op, []).append(s)
    return out


def _firefly_span(spans: Any, name: str) -> Any:
    return next((s for s in spans if s.name == f"agent.{name}"), None)


# -- Capability gating (no exporter needed) ----------------------------------


def test_build_capabilities_gating():
    on = FireflyAgenticConfig(native_instrumentation_enabled=True)
    off = FireflyAgenticConfig(native_instrumentation_enabled=False)
    obs_off = FireflyAgenticConfig(observability_enabled=False, native_instrumentation_enabled=True)

    assert [type(c).__name__ for c in FireflyAgent._build_capabilities(off, None)] == []
    assert [type(c).__name__ for c in FireflyAgent._build_capabilities(on, None)] == ["Instrumentation"]
    # native instrumentation requires observability_enabled too
    assert FireflyAgent._build_capabilities(obs_off, None) == []

    # composes with the SP-3 inline approval handler
    def handler(ctx: Any, reqs: Any) -> Any:
        return None

    caps = FireflyAgent._build_capabilities(on, handler)
    types = [type(c).__name__ for c in caps]
    assert types == ["HandleDeferredToolCalls", "Instrumentation"]
    assert isinstance(caps[0], HandleDeferredToolCalls)
    assert isinstance(caps[1], Instrumentation)


def test_instrumentation_settings_reflect_config():
    cfg = FireflyAgenticConfig(
        native_instrumentation_enabled=True,
        instrumentation_include_content=True,
        instrumentation_version=3,
    )
    inst = FireflyAgent._build_capabilities(cfg, None)[0]
    assert isinstance(inst, Instrumentation)
    assert inst.settings.include_content is True
    assert inst.settings.version == 3


# -- End-to-end span behaviour (in-memory exporter) --------------------------


@pytest.mark.asyncio
async def test_native_spans_nest_under_firefly_span(native_on: InMemorySpanExporter):
    agent = FireflyAgent("weatherbot", model=_tool_then_text(), tools=[weather], auto_register=False)
    result = await agent.run("Weather in Paris?")
    assert result.output == "It is sunny in Paris."

    spans = native_on.get_finished_spans()
    fire = _firefly_span(spans, "weatherbot")
    assert fire is not None, "framework agent span missing"
    ops = _ops(spans)
    assert "invoke_agent" in ops and "chat" in ops and "execute_tool" in ops

    invoke = ops["invoke_agent"][0]
    assert invoke.parent is not None and invoke.parent.span_id == fire.context.span_id, (
        "native span not nested under firefly span"
    )
    assert invoke.context.trace_id == fire.context.trace_id, "native span in a different trace"
    # chat + tool spans descend within the same trace
    for s in ops["chat"] + ops["execute_tool"]:
        assert s.context.trace_id == fire.context.trace_id


@pytest.mark.asyncio
async def test_exactly_one_chat_span_per_model_request(native_on: InMemorySpanExporter):
    # _tool_then_text drives exactly two model requests (tool call, then final text).
    agent = FireflyAgent("oneperreq", model=_tool_then_text(), tools=[weather], auto_register=False)
    await agent.run("Weather?")
    chat = _ops(native_on.get_finished_spans()).get("chat", [])
    assert len(chat) == 2, f"expected one chat span per request, got {len(chat)}"


@pytest.mark.asyncio
async def test_native_instrumentation_off_emits_no_genai_spans(
    monkeypatch: pytest.MonkeyPatch, span_exporter: InMemorySpanExporter
):
    monkeypatch.setenv("FIREFLY_AGENTIC_NATIVE_INSTRUMENTATION_ENABLED", "false")
    reset_config()
    span_exporter.clear()
    agent = FireflyAgent("plainbot", model=_tool_then_text(), tools=[weather], auto_register=False)
    await agent.run("Weather?")
    spans = span_exporter.get_finished_spans()
    assert _firefly_span(spans, "plainbot") is not None  # framework span still emitted
    assert _ops(spans) == {}  # but NO native gen_ai spans
    reset_config()


@pytest.mark.asyncio
async def test_include_content_false_strips_prompt_and_response(native_on: InMemorySpanExporter):
    agent = FireflyAgent("privacy", model=_tool_then_text(), tools=[weather], auto_register=False)
    await agent.run("Weather in Paris?")
    blob = json.dumps([{k: str(v) for k, v in (s.attributes or {}).items()} for s in native_on.get_finished_spans()])
    assert "Weather in Paris" not in blob
    assert "It is sunny in Paris" not in blob


@pytest.mark.asyncio
async def test_include_content_true_records_content(
    monkeypatch: pytest.MonkeyPatch, span_exporter: InMemorySpanExporter
):
    monkeypatch.setenv("FIREFLY_AGENTIC_NATIVE_INSTRUMENTATION_ENABLED", "true")
    monkeypatch.setenv("FIREFLY_AGENTIC_INSTRUMENTATION_INCLUDE_CONTENT", "true")
    reset_config()
    span_exporter.clear()
    agent = FireflyAgent("verbose", model=_tool_then_text(), tools=[weather], auto_register=False)
    await agent.run("Weather in Paris?")
    blob = json.dumps(
        [{k: str(v) for k, v in (s.attributes or {}).items()} for s in span_exporter.get_finished_spans()]
    )
    assert "Paris" in blob  # opt-in: content now present
    reset_config()


@pytest.mark.asyncio
async def test_correlation_id_is_stamped_on_firefly_span(native_on: InMemorySpanExporter):
    agent = FireflyAgent("corr", model=_tool_then_text(), tools=[weather], auto_register=False)
    await agent.run("Weather?")
    fire = _firefly_span(native_on.get_finished_spans(), "corr")
    assert fire is not None
    assert (fire.attributes or {}).get("firefly.correlation_id")  # non-empty join key


@pytest.mark.asyncio
async def test_no_pydantic_ai_deprecation_warning(native_on: InMemorySpanExporter):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        agent = FireflyAgent("nodepr", model=_tool_then_text(), tools=[weather], auto_register=False)
        await agent.run("Weather?")
    deprecations = [w for w in caught if issubclass(w.category, PydanticAIDeprecationWarning)]
    assert deprecations == [], (
        f"native instrumentation must not use deprecated APIs: {[str(w.message) for w in deprecations]}"
    )


# -- Middleware context-activation contract ----------------------------------


@pytest.mark.asyncio
async def test_observability_middleware_activates_and_detaches_context():
    mw = ObservabilityMiddleware()
    ctx = MiddlewareContext(agent_name="ctx", prompt="p", method="run")
    await mw.before_run(ctx)
    assert ctx.metadata.get("_otel_span") is not None
    assert ctx.metadata.get("_otel_ctx_token") is not None  # span activated in the OTel context

    await mw.after_run(ctx, result="done")
    assert "_otel_span" not in ctx.metadata  # span ended
    assert "_otel_ctx_token" not in ctx.metadata  # context token detached (no leak)


@pytest.mark.asyncio
async def test_observability_middleware_detaches_context_on_error():
    mw = ObservabilityMiddleware()
    ctx = MiddlewareContext(agent_name="ctx-err", prompt="p", method="run")
    await mw.before_run(ctx)
    await mw.on_error(ctx, RuntimeError("boom"))
    assert "_otel_span" not in ctx.metadata  # span ended on error
    assert "_otel_ctx_token" not in ctx.metadata  # token detached on the error path too
