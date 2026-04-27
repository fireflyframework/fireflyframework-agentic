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

"""OpenTelemetry tracer integration for Firefly Agentic.

:class:`FireflyTracer` wraps the OpenTelemetry tracer with convenience
methods for creating agent- and tool-scoped spans.

This module also provides W3C Trace Context propagation utilities for
distributed tracing across HTTP and queue boundaries.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanContext, StatusCode, TraceFlags, Tracer

_TRACER_NAME = "fireflyframework_agentic"

# Context variable for trace propagation across async boundaries
_trace_context: ContextVar[SpanContext | None] = ContextVar("trace_context", default=None)


class FireflyTracer:
    """High-level tracer that creates spans with Firefly-specific attributes.

    Parameters:
        service_name: The OpenTelemetry service name.
    """

    def __init__(self, service_name: str = _TRACER_NAME) -> None:
        self._tracer: Tracer = trace.get_tracer(service_name)

    @contextmanager
    def agent_span(self, agent_name: str, *, model: str = "", **attributes: Any) -> Generator[Span]:
        """Create a span for an agent run."""
        with self._tracer.start_as_current_span(
            f"agent.{agent_name}",
            attributes={
                "firefly.agent.name": agent_name,
                "firefly.agent.model": model,
                **{f"firefly.{k}": str(v) for k, v in attributes.items()},
            },
        ) as span:
            yield span

    @contextmanager
    def tool_span(self, tool_name: str, **attributes: Any) -> Generator[Span]:
        """Create a span for a tool execution."""
        with self._tracer.start_as_current_span(
            f"tool.{tool_name}",
            attributes={
                "firefly.tool.name": tool_name,
                **{f"firefly.{k}": str(v) for k, v in attributes.items()},
            },
        ) as span:
            yield span

    @contextmanager
    def reasoning_span(self, pattern_name: str, step: int = 0, **attributes: Any) -> Generator[Span]:
        """Create a span for a reasoning step."""
        with self._tracer.start_as_current_span(
            f"reasoning.{pattern_name}.step_{step}",
            attributes={
                "firefly.reasoning.pattern": pattern_name,
                "firefly.reasoning.step": step,
                **{f"firefly.{k}": str(v) for k, v in attributes.items()},
            },
        ) as span:
            yield span

    @contextmanager
    def custom_span(self, name: str, **attributes: Any) -> Generator[Span]:
        """Create a span with arbitrary attributes."""
        with self._tracer.start_as_current_span(
            name,
            attributes={f"firefly.{k}": str(v) for k, v in attributes.items()},
        ) as span:
            yield span

    @staticmethod
    def set_error(span: Span, error: Exception) -> None:
        """Record an exception on the span and set error status."""
        span.set_status(StatusCode.ERROR, str(error))
        span.record_exception(error)


# Module-level default tracer
default_tracer = FireflyTracer()


# -- W3C Trace Context Propagation ------------------------------------------


def inject_trace_context(headers: dict[str, str]) -> None:
    """Inject W3C Trace Context headers into an outgoing request/message.

    This function follows the W3C Trace Context specification to propagate
    trace information across HTTP and message queue boundaries. It adds
    ``traceparent`` and ``tracestate`` headers to the provided dictionary.

    Parameters:
        headers: Dictionary of headers to inject trace context into. Modified in-place.

    Example:
        Inject trace context for HTTP request::

            headers = {}
            inject_trace_context(headers)
            response = await http_client.post(url, headers=headers, ...)

        Inject trace context for Kafka message::

            headers = {}
            inject_trace_context(headers)
            await producer.send(
                topic,
                value=message,
                headers=[(k, v.encode()) for k, v in headers.items()]
            )

    See Also:
        - https://www.w3.org/TR/trace-context/
        - :func:`extract_trace_context`
    """
    span = trace.get_current_span()
    if span is None:
        return

    ctx = span.get_span_context()
    if not ctx.is_valid:
        return

    # W3C traceparent header format:
    # version-trace_id-parent_id-trace_flags
    # Example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
    traceparent = f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-{ctx.trace_flags:02x}"
    headers["traceparent"] = traceparent

    # Include tracestate if present
    if ctx.trace_state:
        headers["tracestate"] = ctx.trace_state.to_header()


def extract_trace_context(headers: dict[str, str]) -> SpanContext | None:
    """Extract W3C Trace Context from incoming request/message headers.

    This function parses ``traceparent`` and ``tracestate`` headers according
    to the W3C Trace Context specification and returns a SpanContext that can
    be used to continue a distributed trace.

    Parameters:
        headers: Dictionary of headers containing trace context. Keys are
            case-insensitive (``traceparent`` or ``Traceparent`` both work).

    Returns:
        SpanContext if valid trace context is found, None otherwise.

    Example:
        Extract trace context from HTTP request::

            from opentelemetry import trace

            span_context = extract_trace_context(request.headers)
            if span_context:
                with trace.use_span(
                    trace.NonRecordingSpan(span_context),
                    end_on_exit=False
                ):
                    # Your code runs within the distributed trace
                    await agent.run(prompt)

        Extract trace context from Kafka message::

            headers = {k: v.decode() for k, v in message.headers}
            span_context = extract_trace_context(headers)
            if span_context:
                _trace_context.set(span_context)
                await process_message(message)

    See Also:
        - https://www.w3.org/TR/trace-context/
        - :func:`inject_trace_context`
    """
    # Case-insensitive header lookup
    headers_lower = {k.lower(): v for k, v in headers.items()}
    traceparent = headers_lower.get("traceparent")

    if not traceparent:
        return None

    try:
        # Parse W3C traceparent: version-trace_id-parent_id-trace_flags
        parts = traceparent.split("-")
        if len(parts) != 4:
            return None

        version, trace_id_hex, span_id_hex, flags_hex = parts

        # Only support version 00
        if version != "00":
            return None

        trace_id = int(trace_id_hex, 16)
        span_id = int(span_id_hex, 16)
        trace_flags = TraceFlags(int(flags_hex, 16))

        # Parse tracestate if present
        from opentelemetry.trace import TraceState

        tracestate_header = headers_lower.get("tracestate")
        trace_state = TraceState.from_header([tracestate_header]) if tracestate_header else None

        return SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=True,
            trace_flags=trace_flags,
            trace_state=trace_state,
        )
    except (ValueError, TypeError):
        # Invalid trace context format
        return None


def get_trace_context() -> SpanContext | None:
    """Get the current trace context from the context variable.

    Returns:
        The active SpanContext, or None if no context is set.
    """
    return _trace_context.get()


def set_trace_context(context: SpanContext | None) -> None:
    """Set the trace context in the context variable.

    Parameters:
        context: SpanContext to set, or None to clear.
    """
    _trace_context.set(context)


@contextmanager
def trace_context_scope(context: SpanContext | None) -> Generator[None]:
    """Context manager that sets trace context for the duration of the scope.

    Parameters:
        context: SpanContext to use within the scope.

    Example::

        span_context = extract_trace_context(headers)
        with trace_context_scope(span_context):
            # All spans created here will be children of the extracted context
            with default_tracer.agent_span("my_agent"):
                result = await agent.run(prompt)
    """
    token = _trace_context.set(context)
    try:
        if context:
            # Make OpenTelemetry use this context as the parent
            with trace.use_span(
                trace.NonRecordingSpan(context),
                end_on_exit=False,
            ):
                yield
        else:
            yield
    finally:
        _trace_context.reset(token)
