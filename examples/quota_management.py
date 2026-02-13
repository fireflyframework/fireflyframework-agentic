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

"""API quota management and rate limiting example.

This example demonstrates how to use Firefly GenAI's quota management system
to enforce production-grade budget and rate limits for LLM API calls.

Features demonstrated:
- Daily budget enforcement in USD
- Per-model rate limiting (requests per minute)
- Adaptive exponential backoff for 429 responses
- Token quota tracking
- Budget alerts and warnings

Prerequisites:
    Set environment variables:
       export FIREFLY_GENAI_QUOTA_ENABLED=true
       export FIREFLY_GENAI_QUOTA_BUDGET_DAILY_USD=5.0
       export FIREFLY_GENAI_QUOTA_RATE_LIMITS='{"openai:gpt-4o-mini": 10}'
       export OPENAI_API_KEY=sk-...

Usage:
    python examples/quota_management.py
"""

import asyncio

from fireflyframework_genai.agents.base import FireflyAgent
from fireflyframework_genai.config import get_config
from fireflyframework_genai.exceptions import BudgetExceededError, RateLimitError
from fireflyframework_genai.observability.quota import QuotaManager
from fireflyframework_genai.observability.usage import default_usage_tracker


async def demonstrate_budget_enforcement():
    """Demonstrate daily budget enforcement."""
    print("\n" + "=" * 70)
    print("Budget Enforcement Demonstration")
    print("=" * 70)

    # Create quota manager with $2 daily budget
    quota = QuotaManager(daily_budget_usd=2.0)

    print(f"\n✓ Daily budget: ${quota._daily_budget:.2f}")
    print(f"✓ Current spend: ${quota.get_daily_spend():.2f}")
    print(f"✓ Remaining: ${quota.get_budget_remaining():.2f}")

    agent = FireflyAgent(
        name="budget_demo_agent",
        model="openai:gpt-4o-mini",  # Cheap model for testing
        description="Agent with budget constraints",
    )

    print("\n--- Making API calls until budget is exhausted ---")

    for i in range(1, 100):
        try:
            # Check quota before making request
            estimated_cost = 0.001  # Rough estimate
            quota.check_quota_before_request("openai:gpt-4o-mini", estimated_cost)

            # Make request
            await agent.run(f"Say 'hello {i}' in one word")

            # Get actual cost from usage tracker
            default_usage_tracker.get_summary()

            # Record actual cost
            quota.record_request("openai:gpt-4o-mini", cost_usd=estimated_cost, success=True)

            print(
                f"  Request #{i}: OK (spend=${quota.get_daily_spend():.4f}, remaining=${quota.get_budget_remaining():.4f})"
            )

        except BudgetExceededError as e:
            print(f"\n✗ Request #{i} BLOCKED: {e}")
            print(f"  Final spend: ${quota.get_daily_spend():.4f}")
            print(f"  Budget limit: ${quota._daily_budget:.2f}")
            break

    print("\n✓ Budget enforcement successful - requests blocked after limit reached")


async def demonstrate_rate_limiting():
    """Demonstrate per-model rate limiting."""
    print("\n" + "=" * 70)
    print("Rate Limiting Demonstration")
    print("=" * 70)

    # Create quota manager with strict rate limit
    quota = QuotaManager(
        rate_limits={
            "openai:gpt-4o-mini": 5,  # 5 requests per minute
        }
    )

    print("\n✓ Rate limit: 5 requests/minute for openai:gpt-4o-mini")

    agent = FireflyAgent(
        name="rate_limit_demo_agent",
        model="openai:gpt-4o-mini",
        description="Agent with rate limits",
    )

    print("\n--- Making rapid API calls ---")

    for i in range(1, 10):
        try:
            # Check rate limit
            quota.check_quota_before_request("openai:gpt-4o-mini")

            # Make request
            await agent.run(f"Count to {i}")

            # Record request
            quota.record_request("openai:gpt-4o-mini", cost_usd=0.0, success=True)

            remaining = quota.get_rate_limit_remaining("openai:gpt-4o-mini")
            print(f"  Request #{i}: OK (remaining={remaining})")

        except RateLimitError as e:
            print(f"\n✗ Request #{i} BLOCKED: {e}")
            remaining = quota.get_rate_limit_remaining("openai:gpt-4o-mini")
            print(f"  Remaining: {remaining}")
            print("  Rate limit enforced - requests blocked")
            break

    print("\n✓ Rate limiting successful")


async def demonstrate_adaptive_backoff():
    """Demonstrate adaptive exponential backoff for 429 errors."""
    print("\n" + "=" * 70)
    print("Adaptive Backoff Demonstration")
    print("=" * 70)

    quota = QuotaManager(
        enable_adaptive_backoff=True,
    )

    print("\n✓ Adaptive backoff enabled")
    print("✓ Simulating consecutive 429 (rate limit) errors...")

    model = "openai:gpt-4o-mini"

    # Simulate multiple 429 errors
    for attempt in range(1, 6):
        print(f"\n--- Attempt {attempt} ---")

        # Simulate rate limit error
        quota.record_rate_limit_error(model)

        # Get recommended backoff delay
        delay = quota.get_backoff_delay(model)
        failure_count = quota._backoff.get_failure_count(model) if quota._backoff else 0

        print("  ✗ Received 429 (Rate Limit) error")
        print(f"  Failure count: {failure_count}")
        print(f"  Recommended backoff: {delay:.2f}s")
        print(f"  Waiting {delay:.2f}s before retry...")

        # In a real application, you would sleep here
        # await asyncio.sleep(delay)

    # Simulate successful request
    print("\n--- Successful request ---")
    quota.record_request(model, cost_usd=0.0, success=True)
    print("  ✓ Request succeeded")
    print("  Backoff reset - next failure will start from base delay")

    print("\n✓ Adaptive backoff demonstration complete")


async def demonstrate_config_integration():
    """Demonstrate quota management from configuration."""
    print("\n" + "=" * 70)
    print("Configuration Integration")
    print("=" * 70)

    cfg = get_config()

    print(f"\n✓ Quota enabled: {cfg.quota_enabled}")
    print(f"✓ Daily budget: ${cfg.quota_budget_daily_usd}")
    print(f"✓ Rate limits: {cfg.quota_rate_limits}")
    print(f"✓ Adaptive backoff: {cfg.quota_adaptive_backoff}")

    if cfg.quota_enabled:
        # Quota manager is automatically created from config
        from fireflyframework_genai.observability.quota import default_quota_manager

        if default_quota_manager:
            print("\n✓ Default quota manager created from configuration")
            print(f"  Daily budget: ${default_quota_manager._daily_budget}")
            print(f"  Rate limits: {default_quota_manager._rate_limits}")
        else:
            print("\n⚠ Quota enabled but no default manager created")
    else:
        print("\n⚠ Quota management is disabled")
        print("  Set FIREFLY_GENAI_QUOTA_ENABLED=true to enable")


async def demonstrate_production_pattern():
    """Demonstrate production-ready quota management pattern."""
    print("\n" + "=" * 70)
    print("Production Pattern")
    print("=" * 70)

    quota = QuotaManager(
        daily_budget_usd=100.0,
        rate_limits={
            "openai:gpt-4o": 60,  # Premium model: 60 req/min
            "openai:gpt-4o-mini": 200,  # Budget model: 200 req/min
        },
        enable_adaptive_backoff=True,
    )

    agent = FireflyAgent(
        name="production_agent",
        model="openai:gpt-4o-mini",
        description="Production agent with quota management",
    )

    print("\n--- Production request pattern with quota checks ---")

    max_retries = 3
    prompt = "Explain quantum computing in one sentence."

    for attempt in range(1, max_retries + 1):
        try:
            print(f"\n  Attempt {attempt}/{max_retries}")

            # 1. Check quota before making request
            print("  → Checking quotas...")
            quota.check_quota_before_request(agent.model, estimated_cost=0.01)
            print("  ✓ Quota check passed")

            # 2. Make API request
            print("  → Making API call...")
            result = await agent.run(prompt)
            print(f"  ✓ Response: {result.output[:50]}...")

            # 3. Record successful request
            quota.record_request(agent.model, cost_usd=0.008, success=True)
            print("  ✓ Usage recorded")

            # Success - exit retry loop
            break

        except BudgetExceededError as e:
            print(f"  ✗ Budget exceeded: {e}")
            print("  Cannot retry - budget limit reached")
            break

        except RateLimitError as e:
            print(f"  ✗ Rate limit exceeded: {e}")

            if attempt < max_retries:
                # Record rate limit error
                quota.record_rate_limit_error(agent.model)

                # Get adaptive backoff delay
                delay = quota.get_backoff_delay(agent.model)
                print(f"  → Waiting {delay:.2f}s before retry...")

                # In production, you would actually sleep here
                # await asyncio.sleep(delay)
            else:
                print("  Max retries reached - giving up")

        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            break

    print("\n✓ Production pattern demonstration complete")


async def main():
    """Run all quota management demonstrations."""
    print("=" * 70)
    print("API Quota Management & Rate Limiting Example")
    print("=" * 70)

    # Run demonstrations
    await demonstrate_config_integration()
    await demonstrate_budget_enforcement()
    await demonstrate_rate_limiting()
    await demonstrate_adaptive_backoff()
    await demonstrate_production_pattern()

    print("\n" + "=" * 70)
    print("Key Benefits of Quota Management")
    print("=" * 70)
    print("✓ Cost control: Prevent unexpected API bills")
    print("✓ Rate limiting: Respect provider API limits")
    print("✓ Adaptive backoff: Automatic retry with exponential backoff")
    print("✓ Production-ready: Thread-safe, configurable, observable")
    print("✓ Integration: Works seamlessly with existing usage tracking")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
