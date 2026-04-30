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

"""Tests for the usage tracking module."""

from __future__ import annotations

import logging

from fireflyframework_agentic.config import reset_config
from fireflyframework_agentic.observability.usage import (
    UsageRecord,
    UsageSummary,
    UsageTracker,
    _aggregate,
)


class TestUsageRecord:
    def test_defaults(self):
        r = UsageRecord()
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.cost_usd == 0.0
        assert r.agent == ""
        assert r.correlation_id == ""

    def test_with_values(self):
        r = UsageRecord(
            agent="test-agent",
            model="openai:gpt-4o",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            request_count=1,
            cost_usd=0.001,
            latency_ms=250.0,
            correlation_id="abc123",
        )
        assert r.agent == "test-agent"
        assert r.total_tokens == 150
        assert r.correlation_id == "abc123"


class TestUsageSummary:
    def test_defaults(self):
        s = UsageSummary()
        assert s.total_tokens == 0
        assert s.total_cost_usd == 0.0
        assert s.record_count == 0
        assert s.by_agent == {}


class TestAggregate:
    def test_empty_list(self):
        summary = _aggregate([])
        assert summary.record_count == 0
        assert summary.total_tokens == 0

    def test_single_record(self):
        records = [
            UsageRecord(
                agent="a1",
                model="m1",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                request_count=1,
                cost_usd=0.01,
                latency_ms=100.0,
            ),
        ]
        summary = _aggregate(records)
        assert summary.record_count == 1
        assert summary.total_input_tokens == 100
        assert summary.total_output_tokens == 50
        assert summary.total_tokens == 150
        assert summary.total_requests == 1
        assert summary.total_cost_usd == 0.01
        assert "a1" in summary.by_agent
        assert "m1" in summary.by_model

    def test_multiple_records(self):
        records = [
            UsageRecord(agent="a1", model="m1", input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01),
            UsageRecord(agent="a2", model="m1", input_tokens=200, output_tokens=100, total_tokens=300, cost_usd=0.02),
            UsageRecord(agent="a1", model="m2", input_tokens=50, output_tokens=25, total_tokens=75, cost_usd=0.005),
        ]
        summary = _aggregate(records)
        assert summary.record_count == 3
        assert summary.total_input_tokens == 350
        assert summary.total_output_tokens == 175
        assert summary.total_tokens == 525
        assert len(summary.by_agent) == 2
        assert len(summary.by_model) == 2
        assert summary.by_agent["a1"]["total_tokens"] == 225
        assert summary.by_model["m1"]["total_tokens"] == 450


class TestUsageTracker:
    def _make_tracker(self) -> UsageTracker:
        return UsageTracker()

    def test_record_and_get_summary(self):
        tracker = self._make_tracker()
        tracker.record(
            UsageRecord(
                agent="a1",
                model="m1",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                cost_usd=0.01,
            )
        )
        summary = tracker.get_summary()
        assert summary.record_count == 1
        assert summary.total_tokens == 150

    def test_cumulative_cost(self):
        tracker = self._make_tracker()
        tracker.record(UsageRecord(cost_usd=0.01))
        tracker.record(UsageRecord(cost_usd=0.02))
        assert abs(tracker.cumulative_cost_usd - 0.03) < 1e-9

    def test_records_property(self):
        tracker = self._make_tracker()
        r = UsageRecord(agent="a1")
        tracker.record(r)
        records = tracker.records
        assert len(records) == 1
        # Should be a copy
        records.clear()
        assert len(tracker.records) == 1

    def test_get_summary_for_agent(self):
        tracker = self._make_tracker()
        tracker.record(UsageRecord(agent="a1", total_tokens=100))
        tracker.record(UsageRecord(agent="a2", total_tokens=200))
        tracker.record(UsageRecord(agent="a1", total_tokens=50))
        summary = tracker.get_summary_for_agent("a1")
        assert summary.record_count == 2
        assert summary.total_tokens == 150

    def test_get_summary_for_correlation(self):
        tracker = self._make_tracker()
        tracker.record(UsageRecord(correlation_id="run-1", total_tokens=100))
        tracker.record(UsageRecord(correlation_id="run-2", total_tokens=200))
        tracker.record(UsageRecord(correlation_id="run-1", total_tokens=50))
        summary = tracker.get_summary_for_correlation("run-1")
        assert summary.record_count == 2
        assert summary.total_tokens == 150

    def test_reset(self):
        tracker = self._make_tracker()
        tracker.record(UsageRecord(cost_usd=0.01, total_tokens=100))
        tracker.reset()
        assert tracker.cumulative_cost_usd == 0.0
        assert tracker.get_summary().record_count == 0

    def test_budget_alert_logged(self, monkeypatch, caplog):
        """Budget alert warning should be logged when threshold is exceeded."""
        monkeypatch.setenv("FIREFLY_AGENTIC_COST_TRACKING_ENABLED", "true")
        monkeypatch.setenv("FIREFLY_AGENTIC_BUDGET_ALERT_THRESHOLD_USD", "0.005")
        reset_config()

        tracker = self._make_tracker()
        with caplog.at_level(logging.WARNING):
            tracker.record(UsageRecord(cost_usd=0.01, agent="test"))

        reset_config()
        assert any("Budget alert" in msg for msg in caplog.messages)

    def test_budget_limit_logged(self, monkeypatch, caplog):
        """Budget limit warning should be logged when limit is exceeded."""
        monkeypatch.setenv("FIREFLY_AGENTIC_COST_TRACKING_ENABLED", "true")
        monkeypatch.setenv("FIREFLY_AGENTIC_BUDGET_LIMIT_USD", "0.005")
        reset_config()

        tracker = self._make_tracker()
        with caplog.at_level(logging.WARNING):
            tracker.record(UsageRecord(cost_usd=0.01, agent="test"))

        reset_config()
        assert any("Budget EXCEEDED" in msg for msg in caplog.messages)

    def test_cost_tracking_disabled_skips_budget(self, monkeypatch, caplog):
        """No budget warnings when cost tracking is disabled."""
        monkeypatch.setenv("FIREFLY_AGENTIC_COST_TRACKING_ENABLED", "false")
        monkeypatch.setenv("FIREFLY_AGENTIC_BUDGET_LIMIT_USD", "0.001")
        reset_config()

        tracker = self._make_tracker()
        with caplog.at_level(logging.WARNING):
            tracker.record(UsageRecord(cost_usd=1.0))

        reset_config()
        assert not any("Budget" in msg for msg in caplog.messages)


# -- Bounded UsageTracker tests -----------------------------------------------


class TestBoundedUsageTracker:
    def test_default_unlimited(self):
        tracker = UsageTracker()
        assert tracker._max_records == 0

    def test_max_records_evicts_oldest(self):
        tracker = UsageTracker(max_records=3)
        for i in range(5):
            tracker.record(UsageRecord(agent=f"a{i}", total_tokens=i * 10))
        records = tracker.records
        assert len(records) == 3
        agents = [r.agent for r in records]
        assert agents == ["a2", "a3", "a4"]

    def test_cumulative_cost_not_affected_by_eviction(self):
        tracker = UsageTracker(max_records=2)
        tracker.record(UsageRecord(cost_usd=0.01))
        tracker.record(UsageRecord(cost_usd=0.02))
        tracker.record(UsageRecord(cost_usd=0.03))
        assert abs(tracker.cumulative_cost_usd - 0.06) < 1e-9
        assert len(tracker.records) == 2

    def test_max_records_of_one(self):
        tracker = UsageTracker(max_records=1)
        tracker.record(UsageRecord(agent="a"))
        tracker.record(UsageRecord(agent="b"))
        records = tracker.records
        assert len(records) == 1
        assert records[0].agent == "b"

    def test_exact_limit_no_eviction(self):
        tracker = UsageTracker(max_records=3)
        for i in range(3):
            tracker.record(UsageRecord(agent=f"a{i}"))
        assert len(tracker.records) == 3
