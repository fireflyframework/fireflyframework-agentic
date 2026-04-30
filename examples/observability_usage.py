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

"""Observability and usage tracking example.

Demonstrates:
- ``UsageTracker`` — record and summarise LLM usage.
- ``max_records`` — bounded tracker with FIFO eviction.
- Cumulative cost tracking (survives eviction).
- Per-agent and per-correlation summaries.

Usage::

    uv run python examples/observability_usage.py

.. note:: This example does NOT require an OpenAI API key.
"""

from __future__ import annotations


def main() -> None:
    from fireflyframework_agentic.observability.usage import UsageRecord, UsageTracker

    # ── 1. Basic usage recording ────────────────────────────────────────
    print("=== Basic Usage Tracking ===\n")

    tracker = UsageTracker()
    tracker.record(
        UsageRecord(
            agent="summarizer",
            model="openai:gpt-4o-mini",
            input_tokens=500,
            output_tokens=150,
            total_tokens=650,
            cost_usd=0.001,
            latency_ms=320.0,
            correlation_id="run-1",
        )
    )
    tracker.record(
        UsageRecord(
            agent="classifier",
            model="openai:gpt-4o-mini",
            input_tokens=200,
            output_tokens=50,
            total_tokens=250,
            cost_usd=0.0004,
            latency_ms=180.0,
            correlation_id="run-1",
        )
    )
    tracker.record(
        UsageRecord(
            agent="summarizer",
            model="openai:gpt-4o",
            input_tokens=1000,
            output_tokens=300,
            total_tokens=1300,
            cost_usd=0.015,
            latency_ms=1200.0,
            correlation_id="run-2",
        )
    )

    summary = tracker.get_summary()
    print(f"  Total records  : {summary.record_count}")
    print(f"  Total tokens   : {summary.total_tokens}")
    print(f"  Total cost     : ${summary.total_cost_usd:.4f}")
    print(f"  Cumulative cost: ${tracker.cumulative_cost_usd:.4f}")

    # ── 2. Per-agent summary ────────────────────────────────────────────
    print("\n=== Per-Agent Summary ===\n")

    for agent_name in ["summarizer", "classifier"]:
        s = tracker.get_summary_for_agent(agent_name)
        print(f"  {agent_name}: {s.record_count} records, {s.total_tokens} tokens, ${s.total_cost_usd:.4f}")

    # ── 3. Per-correlation summary ──────────────────────────────────────
    print("\n=== Per-Correlation Summary ===\n")

    for corr_id in ["run-1", "run-2"]:
        s = tracker.get_summary_for_correlation(corr_id)
        print(f"  {corr_id}: {s.record_count} records, {s.total_tokens} tokens, ${s.total_cost_usd:.4f}")

    # ── 4. Bounded tracker (max_records) ────────────────────────────────
    print("\n=== Bounded Tracker (max_records=3) ===\n")

    bounded = UsageTracker(max_records=3)
    for i in range(5):
        bounded.record(UsageRecord(agent=f"agent_{i}", cost_usd=0.01 * (i + 1)))

    records = bounded.records
    print(f"  Records retained: {len(records)} (max_records=3)")
    print(f"  Agents: {[r.agent for r in records]}")
    print(f"  Cumulative cost: ${bounded.cumulative_cost_usd:.2f} (includes evicted)")
    print(f"  (Expected: ${sum(0.01 * (i + 1) for i in range(5)):.2f})")

    # ── 5. Reset ────────────────────────────────────────────────────────
    print("\n=== Reset ===\n")

    tracker.reset()
    print(f"  After reset: records={len(tracker.records)}, cost=${tracker.cumulative_cost_usd:.4f}")

    print("\nObservability demo complete.")


if __name__ == "__main__":
    main()
