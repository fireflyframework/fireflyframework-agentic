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

"""Observability decorators: ``@traced`` and ``@metered``.

These decorators instrument any async (or sync) function with
OpenTelemetry spans and latency metrics.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

from fireflyframework_genai.observability.metrics import default_metrics
from fireflyframework_genai.observability.tracer import default_tracer

F = TypeVar("F", bound=Callable[..., Any])


def traced(name: str | None = None, **span_attrs: Any) -> Callable[[F], F]:
    """Add an OpenTelemetry span around the decorated function.

    Parameters:
        name: Span name.  Defaults to the function's qualified name.
        **span_attrs: Additional span attributes.
    """

    def decorator(func: F) -> F:
        span_name = name or func.__qualname__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with default_tracer.custom_span(span_name, **span_attrs) as span:
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    default_tracer.set_error(span, exc)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with default_tracer.custom_span(span_name, **span_attrs) as span:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    default_tracer.set_error(span, exc)
                    raise

        import asyncio

        # Detect whether the original function is async or sync at decoration
        # time, then return the matching wrapper so callers see the same
        # calling convention as the unwrapped function.
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def metered(operation: str | None = None) -> Callable[[F], F]:
    """Record latency of the decorated function via :class:`FireflyMetrics`.

    Parameters:
        operation: Operation label.  Defaults to the function's qualified name.
    """

    def decorator(func: F) -> F:
        op_name = operation or func.__qualname__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception:
                default_metrics.record_error(operation=op_name)
                raise
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                default_metrics.record_latency(elapsed, operation=op_name)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                default_metrics.record_error(operation=op_name)
                raise
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                default_metrics.record_latency(elapsed, operation=op_name)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator
