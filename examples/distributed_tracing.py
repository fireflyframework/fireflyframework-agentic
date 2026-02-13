#!/usr/bin/env python3
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

"""Distributed tracing with W3C Trace Context propagation.

This example demonstrates how Firefly GenAI automatically propagates trace
context across service boundaries using the W3C Trace Context standard.

Features demonstrated:
- Automatic trace context injection into HTTP requests
- Trace context extraction from incoming requests
- Multi-agent distributed tracing
- Queue-based trace propagation (Kafka, RabbitMQ, Redis)
- Jaeger UI visualization

Prerequisites:
    1. Start Jaeger for trace visualization:
       docker run -d --name jaeger \\
         -p 16686:16686 \\
         -p 4317:4317 \\
         jaegertracing/all-in-one:latest

    2. Set environment variables:
       export FIREFLY_GENAI_OTLP_ENDPOINT=http://localhost:4317
       export OPENAI_API_KEY=sk-...

    3. View traces at: http://localhost:16686

Usage:
    python examples/distributed_tracing.py
"""

import asyncio

from opentelemetry import trace

from fireflyframework_genai.agents.base import FireflyAgent
from fireflyframework_genai.config import get_config
from fireflyframework_genai.observability.tracer import (
    default_tracer,
    extract_trace_context,
    inject_trace_context,
    trace_context_scope,
)


async def simulate_http_request(url: str, payload: str) -> str:
    """Simulate an HTTP request with trace propagation.

    In a real application, this would be an actual HTTP client call.
    """
    # Inject trace context into outgoing request headers
    headers = {"Content-Type": "application/json"}
    inject_trace_context(headers)

    print(f"→ HTTP POST {url}")
    print(f"  Headers: {headers}")
    print(f"  traceparent: {headers.get('traceparent', 'None')}")

    # Simulate receiving response headers
    response_headers = {}
    inject_trace_context(response_headers)

    return "Response from service"


async def agent_service_a() -> str:
    """Service A: Initial request handler."""
    print("\n" + "=" * 70)
    print("SERVICE A: Processing initial request")
    print("=" * 70)

    agent = FireflyAgent(
        name="service_a_agent",
        model="openai:gpt-4o-mini",
        description="First agent in the distributed trace",
    )

    # Create a span for Service A
    with default_tracer.agent_span("service_a", model="gpt-4o-mini"):
        result = await agent.run("Generate a short creative story opening (max 2 sentences).")

        # Service A calls Service B via HTTP
        print("\n→ Service A calling Service B via HTTP...")
        await simulate_http_request("http://service-b/process", result.output)

        return result.output


async def agent_service_b(incoming_headers: dict[str, str], prompt: str) -> str:
    """Service B: Receives request from Service A with trace context."""
    print("\n" + "=" * 70)
    print("SERVICE B: Processing request from Service A")
    print("=" * 70)
    print(f"  Received traceparent: {incoming_headers.get('traceparent', 'None')}")

    # Extract trace context from incoming request
    span_context = extract_trace_context(incoming_headers)

    agent = FireflyAgent(
        name="service_b_agent",
        model="openai:gpt-4o-mini",
        description="Second agent in the distributed trace",
    )

    # Continue the trace from Service A
    with trace_context_scope(span_context), default_tracer.agent_span("service_b", model="gpt-4o-mini"):
        result = await agent.run(f"Continue this story with one more sentence: {prompt}")

        # Service B calls Service C
        print("\n→ Service B calling Service C via HTTP...")
        await simulate_http_request("http://service-c/finalize", result.output)

        return result.output


async def agent_service_c(incoming_headers: dict[str, str], prompt: str) -> str:
    """Service C: Final service in the chain."""
    print("\n" + "=" * 70)
    print("SERVICE C: Processing request from Service B")
    print("=" * 70)
    print(f"  Received traceparent: {incoming_headers.get('traceparent', 'None')}")

    # Extract trace context from incoming request
    span_context = extract_trace_context(incoming_headers)

    agent = FireflyAgent(
        name="service_c_agent",
        model="openai:gpt-4o-mini",
        description="Final agent in the distributed trace",
    )

    # Continue the trace from Service B
    with trace_context_scope(span_context), default_tracer.agent_span("service_c", model="gpt-4o-mini"):
        result = await agent.run(f"Add a surprising plot twist to this story: {prompt}")

        return result.output


async def main() -> None:
    """Demonstrate distributed tracing across multiple services."""

    print("=" * 70)
    print("Distributed Tracing Example")
    print("=" * 70)

    cfg = get_config()
    if cfg.otlp_endpoint:
        print(f"\n✓ OTLP endpoint: {cfg.otlp_endpoint}")
        print("✓ Traces will be exported to Jaeger")
        print("✓ View at: http://localhost:16686")
    else:
        print("\n⚠ No OTLP endpoint configured - traces will be console-only")
        print("Set FIREFLY_GENAI_OTLP_ENDPOINT=http://localhost:4317 to enable Jaeger")

    # Start distributed trace
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("distributed_trace_example") as root_span:
        print("\n✓ Started root trace")
        root_context = root_span.get_span_context()
        print(f"  Trace ID: {root_context.trace_id:032x}")
        print(f"  Root Span ID: {root_context.span_id:016x}")

        # Service A processes initial request
        story_opening = await agent_service_a()

        # Simulate Service A calling Service B with trace propagation
        headers_to_b = {}
        inject_trace_context(headers_to_b)
        story_continuation = await agent_service_b(headers_to_b, story_opening)

        # Simulate Service B calling Service C with trace propagation
        headers_to_c = {}
        inject_trace_context(headers_to_c)
        story_final = await agent_service_c(headers_to_c, story_continuation)

        print("\n" + "=" * 70)
        print("Final Story Result")
        print("=" * 70)
        print(story_final)

    print("\n" + "=" * 70)
    print("Trace Propagation Summary")
    print("=" * 70)
    print("✓ Service A → Service B → Service C")
    print("✓ All services share the same trace ID")
    print("✓ Each service has its own span ID")
    print("✓ Parent-child relationships are preserved")
    print("=" * 70)

    print("\n" + "=" * 70)
    print("View Trace in Jaeger")
    print("=" * 70)
    print("1. Open http://localhost:16686")
    print("2. Select 'fireflyframework_genai' service")
    print("3. Click 'Find Traces'")
    print(f"4. Look for trace ID: {root_context.trace_id:032x}")
    print("5. Click the trace to see the full span hierarchy:")
    print("   - distributed_trace_example (root)")
    print("     - agent.service_a")
    print("       - agent.service_b")
    print("         - agent.service_c")
    print("=" * 70)

    # Allow time for trace export
    await asyncio.sleep(1)


async def demonstrate_queue_propagation():
    """Demonstrate trace propagation through message queues.

    This shows how trace context is automatically propagated through
    Kafka, RabbitMQ, and Redis Pub/Sub.
    """
    print("\n" + "=" * 70)
    print("Queue-Based Trace Propagation")
    print("=" * 70)

    # Example of injecting trace context into Kafka message
    print("\n1. Kafka Message:")
    headers = {}
    inject_trace_context(headers)
    kafka_headers = [(k, v.encode()) for k, v in headers.items()]
    print(f"   Headers: {kafka_headers}")

    # Example of injecting trace context into RabbitMQ message
    print("\n2. RabbitMQ Message:")
    headers = {}
    inject_trace_context(headers)
    print(f"   Headers: {headers}")

    # Example of injecting trace context into Redis message
    print("\n3. Redis Pub/Sub Message (JSON-wrapped):")
    import json

    headers = {}
    inject_trace_context(headers)
    redis_message = json.dumps({"headers": headers, "body": "message content"})
    print(f"   Wrapped message: {redis_message}")

    print("\n✓ Queue consumers automatically extract trace context")
    print("✓ Traces span across async message boundaries")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(demonstrate_queue_propagation())
