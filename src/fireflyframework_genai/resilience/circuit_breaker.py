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

"""Circuit breaker pattern for preventing cascading failures.

A circuit breaker monitors for failures and temporarily disables a service
when failures exceed a threshold, allowing it to recover and preventing
cascading failures across the system.

States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests are rejected immediately
    - HALF_OPEN: Testing if service has recovered

Example::

    from fireflyframework_genai.resilience.circuit_breaker import CircuitBreaker

    breaker = CircuitBreaker(
        failure_threshold=5,      # Open after 5 failures
        recovery_timeout=60.0,    # Try to recover after 60s
        success_threshold=2,      # Close after 2 successes in half-open
    )

    async def call_external_api():
        async with breaker:
            # If circuit is open, this raises CircuitBreakerOpenError
            return await api.call()

Benefits:
    - Prevents cascading failures
    - Allows failing services time to recover
    - Fast-fail instead of waiting for timeouts
    - Reduces load on struggling services
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit is open, rejecting requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and rejects a request."""

    def __init__(self, message: str = "Circuit breaker is OPEN"):
        self.message = message
        super().__init__(self.message)


class CircuitBreaker:
    """Circuit breaker for fault tolerance and failure isolation.

    The circuit breaker monitors request failures and transitions between states:

    - **CLOSED**: Normal operation. All requests pass through. Failures are counted.
    - **OPEN**: Too many failures detected. All requests fail fast without trying.
    - **HALF_OPEN**: Testing recovery. Limited requests allowed to test service health.

    Parameters:
        failure_threshold: Number of failures before opening circuit (default: 5).
        recovery_timeout: Seconds to wait before transitioning to HALF_OPEN (default: 60).
        success_threshold: Consecutive successes needed to close from HALF_OPEN (default: 2).
        timeout: Per-request timeout in seconds (default: 30).
        excluded_exceptions: Exception types that don't count as failures (e.g., validation errors).

    Example::

        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

        async def fetch_data():
            async with breaker:
                return await expensive_api_call()

        try:
            data = await fetch_data()
        except CircuitBreakerOpenError:
            # Circuit is open, use fallback
            data = get_cached_data()

    State Transitions::

        CLOSED --[failures >= threshold]--> OPEN
        OPEN --[recovery_timeout elapsed]--> HALF_OPEN
        HALF_OPEN --[success_threshold met]--> CLOSED
        HALF_OPEN --[any failure]--> OPEN
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
        timeout: float = 30.0,
        excluded_exceptions: tuple[type[Exception], ...] = (),
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold
        self._timeout = timeout
        self._excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit breaker state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    @property
    def success_count(self) -> int:
        """Get consecutive success count (in HALF_OPEN state)."""
        return self._success_count

    async def __aenter__(self) -> CircuitBreaker:
        """Enter circuit breaker context.

        Raises:
            CircuitBreakerOpenError: If circuit is OPEN and not ready to retry.
        """
        async with self._lock:
            # Check if we should transition from OPEN to HALF_OPEN
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    logger.info("Circuit breaker transitioning: OPEN -> HALF_OPEN")
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is OPEN. Recovery timeout: "
                        f"{self._recovery_timeout}s. "
                        f"Time since last failure: "
                        f"{time.monotonic() - (self._last_failure_time or 0):.1f}s"
                    )

            return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        """Exit circuit breaker context and handle success/failure.

        Args:
            exc_type: Exception type if an exception occurred.
            exc_val: Exception value.
            exc_tb: Exception traceback.

        Returns:
            False (exceptions are not suppressed).
        """
        async with self._lock:
            if exc_type is None:
                # Success
                await self._on_success()
            elif exc_type and not issubclass(exc_type, self._excluded_exceptions):
                # Failure (excluding certain exception types)
                await self._on_failure(exc_val)

        return False  # Don't suppress exceptions

    async def _on_success(self) -> None:
        """Handle successful request."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            logger.debug(
                "Circuit breaker: Success in HALF_OPEN state (%d/%d)",
                self._success_count,
                self._success_threshold,
            )

            if self._success_count >= self._success_threshold:
                logger.info("Circuit breaker transitioning: HALF_OPEN -> CLOSED")
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0

        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            if self._failure_count > 0:
                self._failure_count = 0

    async def _on_failure(self, exception: BaseException | None) -> None:
        """Handle failed request.

        Args:
            exception: The exception that caused the failure.
        """
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in HALF_OPEN immediately opens circuit
            logger.warning(
                "Circuit breaker: Failure in HALF_OPEN state, transitioning to OPEN. Error: %s",
                exception,
            )
            self._state = CircuitState.OPEN
            self._success_count = 0
            self._failure_count = 1

        elif self._state == CircuitState.CLOSED:
            self._failure_count += 1
            logger.warning(
                "Circuit breaker: Failure recorded (%d/%d). Error: %s",
                self._failure_count,
                self._failure_threshold,
                exception,
            )

            if self._failure_count >= self._failure_threshold:
                logger.error(
                    "Circuit breaker transitioning: CLOSED -> OPEN (threshold %d failures reached)",
                    self._failure_threshold,
                )
                self._state = CircuitState.OPEN

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery.

        Returns:
            True if circuit should transition to HALF_OPEN.
        """
        if self._last_failure_time is None:
            return True

        time_since_failure = time.monotonic() - self._last_failure_time
        return time_since_failure >= self._recovery_timeout

    async def reset(self) -> None:
        """Reset circuit breaker to CLOSED state.

        This can be used for manual recovery or testing.
        """
        async with self._lock:
            logger.info("Circuit breaker manually reset to CLOSED state")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None

    def get_metrics(self) -> dict[str, Any]:
        """Get current circuit breaker metrics.

        Returns:
            Dictionary with state, counts, and timestamps.
        """
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self._failure_threshold,
            "success_threshold": self._success_threshold,
            "recovery_timeout": self._recovery_timeout,
            "time_since_last_failure": (
                time.monotonic() - self._last_failure_time if self._last_failure_time else None
            ),
        }


class CircuitBreakerMiddleware:
    """Middleware that adds circuit breaker protection to agents.

    This middleware wraps agent execution in a circuit breaker to prevent
    cascading failures when the LLM provider or downstream services are
    experiencing issues.

    Parameters:
        failure_threshold: Number of failures before opening circuit (default: 5).
        recovery_timeout: Seconds to wait before testing recovery (default: 60).
        success_threshold: Successes needed to close circuit (default: 2).
        enabled: Whether circuit breaker is enabled (default: True).

    Example::

        from fireflyframework_genai.resilience.circuit_breaker import CircuitBreakerMiddleware

        agent = FireflyAgent(
            "resilient-agent",
            model="openai:gpt-4o",
            middleware=[
                CircuitBreakerMiddleware(
                    failure_threshold=3,
                    recovery_timeout=30.0,
                ),
            ],
        )

        try:
            result = await agent.run("Question")
        except CircuitBreakerOpenError:
            # Circuit is open, use fallback
            result = get_cached_response()

    Benefits:
        - Prevents wasting resources on failing services
        - Fast-fail instead of timeout waits
        - Automatic recovery testing
        - Protects upstream services from overload
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        if enabled:
            self._breaker = CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                success_threshold=success_threshold,
            )
        else:
            self._breaker = None

    async def before_run(self, context: Any) -> None:
        """Check circuit breaker before agent execution.

        Args:
            context: Middleware context.

        Raises:
            CircuitBreakerOpenError: If circuit is open.
        """
        if not self._enabled or self._breaker is None:
            return

        # Store breaker in context for after hook
        if not hasattr(context, "metadata"):
            context.metadata = {}
        context.metadata["_circuit_breaker"] = self._breaker

        # Enter circuit breaker (will raise if open)
        await self._breaker.__aenter__()

    async def after_run(self, context: Any, result: Any) -> Any:
        """Update circuit breaker after agent execution.

        Args:
            context: Middleware context.
            result: Agent result.

        Returns:
            Unchanged result.
        """
        if not self._enabled or self._breaker is None:
            return result

        # Exit circuit breaker (records success)
        await self._breaker.__aexit__(None, None, None)

        return result

    async def on_error(self, context: Any, error: Exception) -> None:
        """Update circuit breaker on agent execution error.

        Args:
            context: Middleware context.
            error: The exception that caused the failure.
        """
        if not self._enabled or self._breaker is None:
            return

        # Record failure in the circuit breaker
        await self._breaker.__aexit__(type(error), error, None)

    def get_metrics(self) -> dict[str, Any]:
        """Get circuit breaker metrics.

        Returns:
            Dictionary with breaker state and metrics.
        """
        if not self._enabled or self._breaker is None:
            return {"enabled": False}

        return {
            "enabled": True,
            **self._breaker.get_metrics(),
        }
