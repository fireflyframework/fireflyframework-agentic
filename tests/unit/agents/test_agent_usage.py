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

"""Tests for usage tracking wired into FireflyAgent."""

from __future__ import annotations

from unittest.mock import patch

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.config import reset_config
from fireflyframework_agentic.observability.usage import UsageTracker


class _FakeUsage:
    """Simulates pydantic_ai RunUsage."""

    def __init__(self, *, input_tokens=10, output_tokens=5, total_tokens=15, request_count=1):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.request_count = request_count
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0


class _FakeResult:
    """Simulates a pydantic_ai RunResult."""

    def __init__(self, output="hello", usage=None):
        self.output = output
        self._usage = usage or _FakeUsage()

    def usage(self):
        return self._usage

    def new_messages(self):
        return []


class TestAgentRecordUsage:
    def test_record_usage_creates_record(self):
        agent = FireflyAgent(name="test-usage", model="test", auto_register=False)
        tracker = UsageTracker()
        fake_result = _FakeResult(usage=_FakeUsage(input_tokens=100, output_tokens=50, total_tokens=150))

        with patch(
            "fireflyframework_agentic.observability.usage.default_usage_tracker",
            tracker,
        ):
            agent._record_usage(fake_result, 42.0)

        summary = tracker.get_summary()
        assert summary.record_count == 1
        assert summary.total_input_tokens == 100
        assert summary.total_output_tokens == 50
        assert summary.total_tokens == 150
        assert summary.total_latency_ms == 42.0

    def test_record_usage_with_correlation_id(self):
        agent = FireflyAgent(name="corr-test", model="test", auto_register=False)
        tracker = UsageTracker()
        fake_result = _FakeResult(usage=_FakeUsage(total_tokens=50))

        with patch(
            "fireflyframework_agentic.observability.usage.default_usage_tracker",
            tracker,
        ):
            agent._record_usage(fake_result, 10.0, correlation_id="pipe-123")

        records = tracker.records
        assert len(records) == 1
        assert records[0].correlation_id == "pipe-123"

    def test_record_usage_cost_calculation(self):
        agent = FireflyAgent(name="cost-test", model="test", auto_register=False)
        agent._model_identifier = "openai:gpt-4o"  # exercise real pricing path without API key
        tracker = UsageTracker()
        fake_result = _FakeResult(usage=_FakeUsage(input_tokens=1000, output_tokens=500, total_tokens=1500))

        with patch(
            "fireflyframework_agentic.observability.usage.default_usage_tracker",
            tracker,
        ):
            agent._record_usage(fake_result, 100.0)

        records = tracker.records
        assert len(records) == 1
        assert records[0].cost_usd > 0  # cost should be calculated

    def test_record_usage_disabled(self, monkeypatch):
        monkeypatch.setenv("FIREFLY_AGENTIC_COST_TRACKING_ENABLED", "false")
        reset_config()

        agent = FireflyAgent(name="disabled-test", model="test", auto_register=False)
        tracker = UsageTracker()
        fake_result = _FakeResult()

        with patch(
            "fireflyframework_agentic.observability.usage.default_usage_tracker",
            tracker,
        ):
            agent._record_usage(fake_result, 10.0)

        reset_config()
        assert tracker.get_summary().record_count == 0

    def test_record_usage_no_usage_method(self):
        """Should not raise if result has no usage() method."""
        agent = FireflyAgent(name="no-usage", model="test", auto_register=False)
        tracker = UsageTracker()

        class _NoUsageResult:
            output = "hi"

        with patch(
            "fireflyframework_agentic.observability.usage.default_usage_tracker",
            tracker,
        ):
            agent._record_usage(_NoUsageResult(), 10.0)

        assert tracker.get_summary().record_count == 0

    def test_record_usage_agent_name_in_record(self):
        agent = FireflyAgent(name="named-agent", model="test", auto_register=False)
        tracker = UsageTracker()
        fake_result = _FakeResult(usage=_FakeUsage(total_tokens=10))

        with patch(
            "fireflyframework_agentic.observability.usage.default_usage_tracker",
            tracker,
        ):
            agent._record_usage(fake_result, 5.0)

        records = tracker.records
        assert records[0].agent == "named-agent"
