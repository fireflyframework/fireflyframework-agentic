#!/usr/bin/env python3
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

"""Offline budget, rate-limit, and retry controls using public framework APIs.

No model requests are made. Known usage records stand in for provider billing
reports so that the budget boundary can be reproduced without spending money.
The retry example really waits, using millisecond delays for a local exercise.
Run: uv run python examples/quota_management.py
"""

from __future__ import annotations

import asyncio

from fireflyframework_agentic.exceptions import BudgetExceededError, RateLimitError
from fireflyframework_agentic.observability.budget import BudgetGate, BudgetRule, BudgetWindow
from fireflyframework_agentic.observability.quota import AdaptiveBackoff, QuotaManager
from fireflyframework_agentic.observability.usage import UsageRecord, UsageTracker

MODEL = "example:local-workload"


async def demonstrate_budget_enforcement() -> float:
    """Accept two known-cost records; reject a third before recording it."""
    gate = BudgetGate([BudgetRule(name="daily", limit_usd=0.02, window=BudgetWindow.DAILY)])
    tracker = UsageTracker(gate=gate)
    for index in range(3):
        try:
            gate.precheck(estimated_cost_usd=0.01)
        except BudgetExceededError as exc:
            print(f"Budget blocked request {index + 1}: {exc}")
            break
        tracker.record(UsageRecord(model=MODEL, request_count=1, cost_usd=0.01))
    spend = tracker.get_summary().total_cost_usd
    print(f"Recorded illustrative spend: ${spend:.2f}")
    return spend


async def demonstrate_rate_limiting() -> int:
    """Apply a three-request window to real local word-count operations."""
    quota = QuotaManager(rate_limits={MODEL: 3}, rate_limit_window=60)
    completed = 0
    for document in ("Small workloads", "Use explicit limits", "Record each success", "Blocked document"):
        try:
            quota.check_quota_before_request(MODEL)
        except RateLimitError as exc:
            print(f"Rate limiter blocked the fourth operation: {exc}")
            break
        print(f"Document word count: {len(document.split())}")
        quota.record_request(MODEL)
        completed += 1
    print(f"Requests remaining in window: {quota.get_rate_limit_remaining(MODEL)}")
    return completed


async def demonstrate_adaptive_backoff() -> list[float]:
    """Exercise retry timing for three explicitly simulated failures."""
    backoff = AdaptiveBackoff(base_delay=0.01, max_delay=0.1, jitter=False)
    delays = []
    for _ in range(3):
        backoff.record_failure(MODEL)
        delay = backoff.get_delay(MODEL)
        delays.append(delay)
        await asyncio.sleep(delay)
        print(f"Waited {delay:.2f}s after simulated failure {backoff.get_failure_count(MODEL)}")
    backoff.reset(MODEL)
    print(f"Failure count after recovery: {backoff.get_failure_count(MODEL)}")
    return delays


async def main() -> None:
    await demonstrate_budget_enforcement()
    await demonstrate_rate_limiting()
    await demonstrate_adaptive_backoff()
    print("Use UsageTracker(gate=...) on a FireflyAgent for actual model billing records.")
    print("Configure automatic rate checks with FIREFLY_AGENTIC_QUOTA_ENABLED and FIREFLY_AGENTIC_QUOTA_RATE_LIMITS.")


if __name__ == "__main__":
    asyncio.run(main())
