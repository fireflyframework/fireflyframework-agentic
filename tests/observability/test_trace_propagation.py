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

"""Unit tests for W3C Trace Context propagation."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanContext, TraceFlags

from fireflyframework_agentic.observability.tracer import (
    extract_trace_context,
    get_trace_context,
    inject_trace_context,
    set_trace_context,
    trace_context_scope,
)


@pytest.fixture(scope="module", autouse=True)
def setup_tracing():
    """Set up OpenTelemetry tracer provider for tests."""
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    yield
    # Reset after tests
    trace._TRACER_PROVIDER = None


class TestTraceContextInjection:
    """Test suite for trace context injection."""

    def test_inject_with_active_span(self):
        """Test that inject adds traceparent header when span is active."""
        tracer = trace.get_tracer(__name__)

        headers = {}
        with tracer.start_as_current_span("test-span"):
            inject_trace_context(headers)

        assert "traceparent" in headers
        # Validate format: 00-{trace_id}-{span_id}-{flags}
        parts = headers["traceparent"].split("-")
        assert len(parts) == 4
        assert parts[0] == "00"  # version
        assert len(parts[1]) == 32  # trace_id (128-bit hex)
        assert len(parts[2]) == 16  # span_id (64-bit hex)
        assert len(parts[3]) == 2  # flags (8-bit hex)

    def test_inject_without_active_span(self):
        """Test that inject does nothing when no span is active."""
        headers = {}
        inject_trace_context(headers)

        assert "traceparent" not in headers

    def test_inject_preserves_existing_headers(self):
        """Test that inject doesn't overwrite other headers."""
        tracer = trace.get_tracer(__name__)

        headers = {"x-custom-header": "value"}
        with tracer.start_as_current_span("test-span"):
            inject_trace_context(headers)

        assert "x-custom-header" in headers
        assert headers["x-custom-header"] == "value"
        assert "traceparent" in headers


class TestTraceContextExtraction:
    """Test suite for trace context extraction."""

    def test_extract_valid_traceparent(self):
        """Test extraction of valid W3C traceparent header."""
        headers = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}

        context = extract_trace_context(headers)

        assert context is not None
        assert context.trace_id == 0x0AF7651916CD43DD8448EB211C80319C
        assert context.span_id == 0xB7AD6B7169203331
        assert context.trace_flags == TraceFlags.SAMPLED
        assert context.is_remote

    def test_extract_case_insensitive(self):
        """Test that header names are case-insensitive."""
        headers = {"TraceParent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}

        context = extract_trace_context(headers)

        assert context is not None
        assert context.trace_id == 0x0AF7651916CD43DD8448EB211C80319C

    def test_extract_missing_header(self):
        """Test extraction returns None when traceparent is missing."""
        headers = {}

        context = extract_trace_context(headers)

        assert context is None

    def test_extract_invalid_format(self):
        """Test extraction returns None for malformed traceparent."""
        invalid_headers = [
            {"traceparent": "invalid"},
            {"traceparent": "00-abc"},  # Too few parts
            {"traceparent": "01-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"},  # Unsupported version
            {"traceparent": "00-xxx-yyy-01"},  # Invalid hex
        ]

        for headers in invalid_headers:
            context = extract_trace_context(headers)
            assert context is None

    def test_extract_with_tracestate(self):
        """Test extraction of traceparent with tracestate."""
        headers = {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
            "tracestate": "vendor1=value1,vendor2=value2",
        }

        context = extract_trace_context(headers)

        assert context is not None
        assert context.trace_state is not None
        # Note: TraceState parsing is handled by OpenTelemetry


class TestTraceContextScope:
    """Test suite for trace context scope management."""

    def test_context_scope_sets_and_resets(self):
        """Test that context scope properly sets and resets context."""
        # Create a mock span context
        context = SpanContext(
            trace_id=0x0AF7651916CD43DD8448EB211C80319C,
            span_id=0xB7AD6B7169203331,
            is_remote=True,
            trace_flags=TraceFlags.SAMPLED,
        )

        # Initially no context
        assert get_trace_context() is None

        # Inside scope, context is set
        with trace_context_scope(context):
            assert get_trace_context() == context

        # After scope, context is reset
        assert get_trace_context() is None

    def test_nested_context_scopes(self):
        """Test that nested scopes work correctly."""
        context1 = SpanContext(
            trace_id=1,
            span_id=1,
            is_remote=True,
            trace_flags=TraceFlags.DEFAULT,
        )
        context2 = SpanContext(
            trace_id=2,
            span_id=2,
            is_remote=True,
            trace_flags=TraceFlags.DEFAULT,
        )

        with trace_context_scope(context1):
            assert get_trace_context() == context1

            with trace_context_scope(context2):
                assert get_trace_context() == context2

            # Outer context restored
            assert get_trace_context() == context1

        # All contexts cleared
        assert get_trace_context() is None

    def test_context_scope_with_none(self):
        """Test that scope can be used with None context."""
        with trace_context_scope(None):
            assert get_trace_context() is None


class TestTraceContextAccessors:
    """Test suite for context variable accessors."""

    def test_get_and_set_context(self):
        """Test getting and setting trace context."""
        context = SpanContext(
            trace_id=0x0AF7651916CD43DD8448EB211C80319C,
            span_id=0xB7AD6B7169203331,
            is_remote=True,
            trace_flags=TraceFlags.SAMPLED,
        )

        set_trace_context(context)
        assert get_trace_context() == context

        set_trace_context(None)
        assert get_trace_context() is None


class TestRoundTripPropagation:
    """Test suite for full inject -> extract round-trip."""

    def test_round_trip_preserves_context(self):
        """Test that inject followed by extract preserves trace information."""
        tracer = trace.get_tracer(__name__)

        # Start a span and inject its context
        with tracer.start_as_current_span("test-span") as span:
            original_context = span.get_span_context()

            headers = {}
            inject_trace_context(headers)

            # Extract the context from headers
            extracted_context = extract_trace_context(headers)

            assert extracted_context is not None
            assert extracted_context.trace_id == original_context.trace_id
            assert extracted_context.span_id == original_context.span_id
            assert extracted_context.trace_flags == original_context.trace_flags

    def test_multiple_services_chain(self):
        """Test trace context propagation through multiple service hops."""
        tracer = trace.get_tracer(__name__)

        # Service A starts a trace
        with tracer.start_as_current_span("service-a") as span_a:
            context_a = span_a.get_span_context()

            # Service A sends request to Service B
            headers_to_b = {}
            inject_trace_context(headers_to_b)

            # Service B receives request
            context_b = extract_trace_context(headers_to_b)
            assert context_b is not None

            # Service B continues the trace
            with trace_context_scope(context_b), tracer.start_as_current_span("service-b") as span_b:
                # Service B sends request to Service C
                headers_to_c = {}
                inject_trace_context(headers_to_c)

                # Service C receives request
                context_c = extract_trace_context(headers_to_c)
                assert context_c is not None

                # All services share the same trace ID
                assert context_a.trace_id == context_b.trace_id == context_c.trace_id
                # context_b has context_a's span as parent, context_c has context_b's span as parent
                # (extracted contexts contain the parent span ID)
                assert context_b.span_id == context_a.span_id  # B's parent is A
                # The actual span created in B will have a different ID
                assert span_b.get_span_context().span_id != context_a.span_id
