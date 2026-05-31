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

"""OpenTelemetry tracer integration for Firefly Agentic.

:class:`FireflyTracer` wraps the OpenTelemetry tracer with convenience
methods for creating agent- and tool-scoped spans.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode, Tracer

_TRACER_NAME = "fireflyframework_agentic"


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

    def event(self, name: str, **attributes: Any) -> None:
        """Attach an instantaneous event to the currently active span.

        Use this for zero-duration annotations (e.g. routing decisions,
        cache hits, retries) instead of opening an empty span. No-op when
        no span is active.
        """
        span = trace.get_current_span()
        if span is None:
            return
        span.add_event(
            name,
            attributes={f"firefly.{k}": str(v) for k, v in attributes.items()},
        )

    @staticmethod
    def set_error(span: Span, error: Exception) -> None:
        """Record an exception on the span and set error status."""
        span.set_status(StatusCode.ERROR, str(error))
        span.record_exception(error)


# Module-level default tracer
default_tracer = FireflyTracer()
