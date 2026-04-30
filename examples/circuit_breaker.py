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

"""Example demonstrating circuit breaker pattern for resilience.

The circuit breaker pattern prevents cascading failures by monitoring
service health and fast-failing when issues are detected.

Benefits:
    - Prevents wasting resources on failing services
    - Allows failing services time to recover
    - Fast-fail instead of timeout waits
    - Reduces load on struggling services

States:
    - CLOSED: Normal operation (healthy service)
    - OPEN: Too many failures (rejecting requests)
    - HALF_OPEN: Testing recovery (limited requests)

Use Cases:
    - External API calls
    - Database connections
    - Microservice communication
    - LLM provider failures
"""

from __future__ import annotations

import asyncio
import random

from fireflyframework_agentic.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
)


async def demo_basic_circuit_breaker():
    """Demonstrate basic circuit breaker usage."""
    print("\n=== Basic Circuit Breaker Demo ===\n")

    breaker = CircuitBreaker(
        failure_threshold=3,  # Open after 3 failures
        recovery_timeout=5.0,  # Try recovery after 5 seconds
        success_threshold=2,  # Close after 2 successes
    )

    print(f"Initial state: {breaker.state.value}")
    print(f"Failure threshold: {breaker._failure_threshold}")
    print()

    # Simulate service that fails
    async def unreliable_service(should_fail: bool):
        if should_fail:
            raise ValueError("Service unavailable")
        return "Success"

    # Make requests with circuit breaker
    for i in range(6):
        try:
            async with breaker:
                # Fail first 3 requests
                result = await unreliable_service(should_fail=(i < 3))
                print(f"Request {i + 1}: {result} (state: {breaker.state.value})")

        except CircuitBreakerOpenError as e:
            print(f"Request {i + 1}: REJECTED - {e.message}")

        except ValueError as e:
            print(f"Request {i + 1}: FAILED - {e} (failures: {breaker.failure_count})")

        await asyncio.sleep(0.5)

    print(f"\nFinal state: {breaker.state.value}")


async def demo_state_transitions():
    """Demonstrate circuit breaker state transitions."""
    print("\n\n=== State Transition Demo ===\n")

    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout=2.0,
        success_threshold=1,
    )

    async def maybe_fail(should_fail: bool):
        if should_fail:
            raise RuntimeError("Simulated failure")
        return "OK"

    print("Phase 1: CLOSED state (normal operation)")
    print(f"Current state: {breaker.state.value}\n")

    # Success in CLOSED state
    try:
        async with breaker:
            await maybe_fail(False)
        print("✓ Request succeeded")
    except Exception as e:
        print(f"✗ Request failed: {e}")

    print()

    print("Phase 2: Accumulating failures")
    for i in range(2):
        try:
            async with breaker:
                await maybe_fail(True)
        except RuntimeError:
            print(f"✗ Failure {i + 1}/2 recorded")

    print(f"→ State transitioned to: {breaker.state.value}\n")

    print("Phase 3: OPEN state (rejecting requests)")
    for i in range(2):
        try:
            async with breaker:
                await maybe_fail(False)
        except CircuitBreakerOpenError:
            print(f"✗ Request {i + 1} rejected (circuit OPEN)")

    print()

    print("Phase 4: Waiting for recovery timeout...")
    await asyncio.sleep(2.5)
    print("Recovery timeout elapsed\n")

    print("Phase 5: HALF_OPEN state (testing recovery)")
    try:
        async with breaker:
            await maybe_fail(False)
        print("✓ Test request succeeded")
        print(f"→ State transitioned to: {breaker.state.value}\n")
    except Exception as e:
        print(f"✗ Test failed: {e}")

    print("Circuit is now CLOSED and healthy!")


async def demo_with_fallback():
    """Demonstrate circuit breaker with fallback strategy."""
    print("\n\n=== Circuit Breaker with Fallback ===\n")

    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=3.0)

    # Simulated cache for fallback
    cache = {"question1": "Cached answer 1", "question2": "Cached answer 2"}

    async def call_llm_api(question: str) -> str:
        """Simulated LLM API call that may fail."""
        # Simulate random failures
        if random.random() < 0.5:
            raise ConnectionError("LLM API unavailable")
        return f"Fresh answer for: {question}"

    async def ask_question(question: str) -> str:
        """Ask question with circuit breaker and fallback."""
        try:
            async with breaker:
                return await call_llm_api(question)

        except CircuitBreakerOpenError:
            # Circuit is open, use cache immediately
            print(f"  → Circuit OPEN, using cache for: {question}")
            return cache.get(question, "No cached answer available")

        except ConnectionError:
            # LLM failed, use cache
            print(f"  → LLM failed, using cache for: {question}")
            return cache.get(question, "No cached answer available")

    print("Making requests with fallback strategy:\n")

    questions = ["question1", "question2", "question3", "question1"]

    for i, q in enumerate(questions, 1):
        print(f"Request {i}: {q}")
        answer = await ask_question(q)
        print(f"  Answer: {answer}")
        print(f"  Circuit state: {breaker.state.value}\n")

        await asyncio.sleep(0.5)


async def demo_monitoring_metrics():
    """Demonstrate circuit breaker metrics monitoring."""
    print("\n\n=== Circuit Breaker Metrics Monitoring ===\n")

    breaker = CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=2.0,
    )

    async def service_call(fail: bool):
        if fail:
            raise Exception("Service error")
        return "Success"

    def print_metrics():
        metrics = breaker.get_metrics()
        print(f"  State: {metrics['state']}")
        print(f"  Failures: {metrics['failure_count']}/{metrics['failure_threshold']}")
        print(f"  Successes: {metrics['success_count']}/{metrics['success_threshold']}")
        if metrics["time_since_last_failure"]:
            print(f"  Time since last failure: {metrics['time_since_last_failure']:.1f}s")
        print()

    print("Initial metrics:")
    print_metrics()

    print("Recording 2 failures...")
    for _ in range(2):
        try:
            async with breaker:
                await service_call(fail=True)
        except Exception:
            pass

    print_metrics()

    print("Recording 1 more failure (should open circuit)...")
    try:
        async with breaker:
            await service_call(fail=True)
    except Exception:
        pass

    print_metrics()

    print("Attempting request while circuit is OPEN...")
    try:
        async with breaker:
            await service_call(fail=False)
    except CircuitBreakerOpenError:
        print("  → Request rejected\n")

    print_metrics()


async def demo_best_practices():
    """Demonstrate best practices for circuit breakers."""
    print("\n\n=== Circuit Breaker Best Practices ===\n")

    print("1. CONFIGURATION GUIDELINES:")
    print("   • failure_threshold: 3-10 (balance sensitivity vs stability)")
    print("   • recovery_timeout: 30-120s (allow time for recovery)")
    print("   • success_threshold: 1-3 (gradual recovery)")
    print()

    print("2. WHEN TO USE CIRCUIT BREAKERS:")
    print("   ✓ External API calls (LLM providers, databases)")
    print("   ✓ Microservice communication")
    print("   ✓ Any service that can fail and recover")
    print("   ✓ Services where timeouts are expensive")
    print()

    print("3. FALLBACK STRATEGIES:")
    print("   • Return cached data")
    print("   • Use degraded functionality")
    print("   • Return default/error response")
    print("   • Queue request for later processing")
    print()

    print("4. MONITORING RECOMMENDATIONS:")
    print("   • Track circuit state changes")
    print("   • Alert on OPEN state")
    print("   • Monitor failure patterns")
    print("   • Log recovery attempts")
    print()

    print("5. COMMON PATTERNS:")
    print("   • Circuit breaker + retry (with backoff)")
    print("   • Circuit breaker + fallback (cache, degraded mode)")
    print("   • Circuit breaker + timeout (prevent hanging)")
    print("   • Multiple circuit breakers (per-service isolation)")
    print()


async def main():
    """Run all demonstrations."""
    print("=" * 70)
    print("Circuit Breaker Pattern Demonstrations")
    print("=" * 70)

    await demo_basic_circuit_breaker()
    await demo_state_transitions()
    await demo_with_fallback()
    await demo_monitoring_metrics()
    await demo_best_practices()

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print("\n✓ Circuit breakers prevent cascading failures")
    print("✓ Three states: CLOSED (healthy), OPEN (failing), HALF_OPEN (testing)")
    print("✓ Automatically transitions based on failures and successes")
    print("✓ Use with fallback strategies for resilient applications")
    print("\nUsage:")
    print("  from fireflyframework_agentic.resilience import CircuitBreaker")
    print()
    print("  breaker = CircuitBreaker(")
    print("      failure_threshold=5,")
    print("      recovery_timeout=60.0,")
    print("      success_threshold=2,")
    print("  )")
    print()
    print("  async with breaker:")
    print("      result = await external_api_call()")
    print()
    print("With agent middleware:")
    print("  from fireflyframework_agentic.resilience import CircuitBreakerMiddleware")
    print()
    print("  agent = FireflyAgent(")
    print("      'resilient-agent',")
    print("      model='openai:gpt-4o',")
    print("      middleware=[CircuitBreakerMiddleware(failure_threshold=3)],")
    print("  )")
    print()


if __name__ == "__main__":
    asyncio.run(main())
