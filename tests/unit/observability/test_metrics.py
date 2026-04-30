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

"""Tests for the observability metrics."""

from __future__ import annotations

from fireflyframework_agentic.observability.metrics import FireflyMetrics


class TestFireflyMetrics:
    def test_metrics_creation(self):
        m = FireflyMetrics(service_name="test-svc")
        assert m is not None

    def test_record_tokens_does_not_raise(self):
        m = FireflyMetrics(service_name="test-svc")
        m.record_tokens(100, agent="test")

    def test_record_latency_does_not_raise(self):
        m = FireflyMetrics(service_name="test-svc")
        m.record_latency(42.0, operation="test")

    def test_record_error_does_not_raise(self):
        m = FireflyMetrics(service_name="test-svc")
        m.record_error(operation="test")
