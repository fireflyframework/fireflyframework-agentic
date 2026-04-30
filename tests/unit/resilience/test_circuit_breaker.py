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

"""Unit tests for circuit breaker pattern."""

from __future__ import annotations

import asyncio

import pytest

from fireflyframework_agentic.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)


@pytest.mark.asyncio
class TestCircuitBreaker:
    """Test suite for circuit breaker."""

    async def test_circuit_breaker_initial_state(self):
        """Test that circuit breaker starts in CLOSED state."""
        breaker = CircuitBreaker()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    async def test_circuit_breaker_successful_request(self):
        """Test successful request through circuit breaker."""
        breaker = CircuitBreaker()

        async with breaker:
            # Successful request
            pass

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    async def test_circuit_breaker_single_failure(self):
        """Test single failure doesn't open circuit."""
        breaker = CircuitBreaker(failure_threshold=3)

        try:
            async with breaker:
                raise ValueError("Test error")
        except ValueError:
            pass

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 1

    async def test_circuit_breaker_opens_after_threshold(self):
        """Test circuit opens after failure threshold."""
        breaker = CircuitBreaker(failure_threshold=3)

        # Cause 3 failures
        for _ in range(3):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        # Circuit should be OPEN
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    async def test_circuit_breaker_rejects_when_open(self):
        """Test circuit breaker rejects requests when OPEN."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Cause 2 failures to open circuit
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        assert breaker.state == CircuitState.OPEN

        # Next request should be rejected immediately
        with pytest.raises(CircuitBreakerOpenError):
            async with breaker:
                pass

    async def test_circuit_breaker_transitions_to_half_open(self):
        """Test circuit transitions to HALF_OPEN after recovery timeout."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0.1,  # 100ms for fast test
        )

        # Open the circuit
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Next request should transition to HALF_OPEN
        async with breaker:
            pass

        assert breaker.state == CircuitState.HALF_OPEN

    async def test_circuit_breaker_closes_from_half_open(self):
        """Test circuit closes after successful requests in HALF_OPEN."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=2,
        )

        # Open the circuit
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        # Wait for recovery
        await asyncio.sleep(0.15)

        # Make 2 successful requests in HALF_OPEN
        async with breaker:
            pass
        async with breaker:
            pass

        # Circuit should be CLOSED
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    async def test_circuit_breaker_reopens_on_half_open_failure(self):
        """Test circuit reopens if failure occurs in HALF_OPEN."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0.1,
        )

        # Open the circuit
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        # Wait for recovery
        await asyncio.sleep(0.15)

        # Failure in HALF_OPEN should reopen circuit
        try:
            async with breaker:
                raise ValueError("Test error")
        except ValueError:
            pass

        assert breaker.state == CircuitState.OPEN

    async def test_circuit_breaker_excluded_exceptions(self):
        """Test that excluded exceptions don't count as failures."""

        class ValidationError(Exception):
            pass

        breaker = CircuitBreaker(
            failure_threshold=2,
            excluded_exceptions=(ValidationError,),
        )

        # ValidationError should not count as failure
        try:
            async with breaker:
                raise ValidationError("Validation failed")
        except ValidationError:
            pass

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    async def test_circuit_breaker_reset(self):
        """Test manual circuit breaker reset."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Open the circuit
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        assert breaker.state == CircuitState.OPEN

        # Reset circuit
        await breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    async def test_circuit_breaker_get_metrics(self):
        """Test circuit breaker metrics."""
        breaker = CircuitBreaker(failure_threshold=3)

        metrics = breaker.get_metrics()

        assert metrics["state"] == "closed"
        assert metrics["failure_count"] == 0
        assert metrics["failure_threshold"] == 3

    async def test_circuit_breaker_failure_count_resets_on_success(self):
        """Test failure count resets on success in CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=5)

        # Record some failures
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        assert breaker.failure_count == 2

        # Successful request should reset count
        async with breaker:
            pass

        assert breaker.failure_count == 0

    async def test_circuit_breaker_concurrent_requests(self):
        """Test circuit breaker with concurrent requests."""
        breaker = CircuitBreaker(failure_threshold=3)

        async def failing_request():
            try:
                async with breaker:
                    raise ValueError("Test error")
            except ValueError:
                pass

        # Execute 3 concurrent failing requests
        await asyncio.gather(*[failing_request() for _ in range(3)])

        # Circuit should be OPEN
        assert breaker.state == CircuitState.OPEN

    async def test_circuit_breaker_custom_thresholds(self):
        """Test circuit breaker with custom thresholds."""
        breaker = CircuitBreaker(
            failure_threshold=10,
            success_threshold=5,
        )

        assert breaker._failure_threshold == 10
        assert breaker._success_threshold == 5

    async def test_circuit_breaker_state_transitions(self):
        """Test complete state transition cycle."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=1,
        )

        # Start: CLOSED
        assert breaker.state == CircuitState.CLOSED

        # Fail twice: CLOSED -> OPEN
        for _ in range(2):
            try:
                async with breaker:
                    raise ValueError("Error")
            except ValueError:
                pass

        assert breaker.state == CircuitState.OPEN

        # Wait: OPEN -> (ready for HALF_OPEN)
        await asyncio.sleep(0.15)

        # Success: HALF_OPEN -> CLOSED
        async with breaker:
            pass

        assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
class TestCircuitBreakerEdgeCases:
    """Test edge cases for circuit breaker."""

    async def test_circuit_breaker_zero_recovery_timeout(self):
        """Test circuit with immediate recovery attempt."""
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.0,
        )

        # Open circuit
        try:
            async with breaker:
                raise ValueError("Error")
        except ValueError:
            pass

        # Should immediately allow retry (HALF_OPEN)
        async with breaker:
            pass

        assert breaker.state == CircuitState.HALF_OPEN

    async def test_circuit_breaker_multiple_resets(self):
        """Test multiple circuit resets."""
        breaker = CircuitBreaker(failure_threshold=2)

        for _ in range(3):
            # Open circuit
            for _ in range(2):
                try:
                    async with breaker:
                        raise ValueError("Error")
                except ValueError:
                    pass

            assert breaker.state == CircuitState.OPEN

            # Reset
            await breaker.reset()
            assert breaker.state == CircuitState.CLOSED

    async def test_circuit_breaker_high_failure_threshold(self):
        """Test circuit with high failure threshold."""
        breaker = CircuitBreaker(failure_threshold=100)

        # 99 failures should not open circuit
        for _ in range(99):
            try:
                async with breaker:
                    raise ValueError("Error")
            except ValueError:
                pass

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 99

        # 100th failure should open it
        try:
            async with breaker:
                raise ValueError("Error")
        except ValueError:
            pass

        assert breaker.state == CircuitState.OPEN
