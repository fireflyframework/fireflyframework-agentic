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

"""Tests for the observability tracer."""

from __future__ import annotations

from fireflyframework_agentic.observability.tracer import FireflyTracer


class TestFireflyTracer:
    def test_tracer_creation(self):
        tracer = FireflyTracer(service_name="test-svc")
        assert tracer is not None

    def test_agent_span_context_manager(self):
        tracer = FireflyTracer(service_name="test-svc")
        with tracer.agent_span("test_agent") as span:
            assert span is not None

    def test_custom_span_context_manager(self):
        tracer = FireflyTracer(service_name="test-svc")
        with tracer.custom_span("test.span") as span:
            assert span is not None
