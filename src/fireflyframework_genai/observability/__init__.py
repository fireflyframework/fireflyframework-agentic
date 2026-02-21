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

"""Observability subpackage -- tracing, metrics, events, and exporters."""

from fireflyframework_genai.observability.cost import (
    CostCalculator,
    GenAIPricesCostCalculator,
    StaticPriceCostCalculator,
    get_cost_calculator,
)
from fireflyframework_genai.observability.decorators import metered, traced
from fireflyframework_genai.observability.events import FireflyEvent, FireflyEvents, default_events
from fireflyframework_genai.observability.exporters import configure_exporters
from fireflyframework_genai.observability.metrics import FireflyMetrics, default_metrics
from fireflyframework_genai.observability.tracer import (
    FireflyTracer,
    default_tracer,
    extract_trace_context,
    inject_trace_context,
    trace_context_scope,
)
from fireflyframework_genai.observability.usage import (
    UsageRecord,
    UsageSummary,
    UsageTracker,
    default_usage_tracker,
)

__all__ = [
    "CostCalculator",
    "FireflyEvent",
    "FireflyEvents",
    "FireflyMetrics",
    "FireflyTracer",
    "GenAIPricesCostCalculator",
    "StaticPriceCostCalculator",
    "UsageRecord",
    "UsageSummary",
    "UsageTracker",
    "configure_exporters",
    "default_events",
    "default_metrics",
    "default_tracer",
    "default_usage_tracker",
    "extract_trace_context",
    "get_cost_calculator",
    "inject_trace_context",
    "metered",
    "trace_context_scope",
    "traced",
]
