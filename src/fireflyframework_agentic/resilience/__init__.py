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

"""Resilience patterns for fault tolerance and failure recovery.

This module provides resilience patterns to make applications more robust
against transient failures, cascading errors, and service degradation.

Available Patterns:
    - Circuit Breaker: Prevents cascading failures by stopping requests to failing services
    - Retry with Backoff: Automatically retries failed requests with exponential backoff
    - Bulkhead: Isolates failures to prevent resource exhaustion

Example::

    from fireflyframework_agentic.resilience.circuit_breaker import CircuitBreaker

    breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60.0,
    )

    async def make_api_call():
        async with breaker:
            return await api.call()
"""

from __future__ import annotations

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerMiddleware",
    "CircuitBreakerOpenError",
    "CircuitState",
]

from fireflyframework_agentic.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerMiddleware,
    CircuitBreakerOpenError,
    CircuitState,
)
