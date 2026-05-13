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

"""Observability subpackage -- tracing, metrics, events, and exporters."""

from fireflyframework_agentic.observability.budget import (
    BudgetGate,
    BudgetMode,
    BudgetRule,
    BudgetWindow,
    ScopeContext,
)
from fireflyframework_agentic.observability.cost import (
    DEFAULT_RESOLVERS,
    CostContext,
    genai_prices_cost,
    provider_reported_cost,
    resolve_cost,
)
from fireflyframework_agentic.observability.decorators import metered, traced
from fireflyframework_agentic.observability.events import FireflyEvent, FireflyEvents, default_events
from fireflyframework_agentic.observability.exporters import ProviderBundle, configure_exporters
from fireflyframework_agentic.observability.metrics import FireflyMetrics, default_metrics
from fireflyframework_agentic.observability.sinks import (
    CostSink,
    EventBusSink,
    JSONLFileSink,
    LoggingSink,
    OTelMetricsSink,
    WebhookSink,
)
from fireflyframework_agentic.observability.tracer import (
    FireflyTracer,
    default_tracer,
    extract_trace_context,
    inject_trace_context,
    trace_context_scope,
)
from fireflyframework_agentic.observability.usage import (
    UsageRecord,
    UsageSummary,
    UsageTracker,
    default_usage_tracker,
)

__all__ = [
    "BudgetGate",
    "BudgetMode",
    "BudgetRule",
    "BudgetWindow",
    "CostContext",
    "CostSink",
    "DEFAULT_RESOLVERS",
    "EventBusSink",
    "FireflyEvent",
    "FireflyEvents",
    "FireflyMetrics",
    "FireflyTracer",
    "JSONLFileSink",
    "LoggingSink",
    "OTelMetricsSink",
    "ProviderBundle",
    "ScopeContext",
    "UsageRecord",
    "UsageSummary",
    "UsageTracker",
    "WebhookSink",
    "configure_exporters",
    "default_events",
    "default_metrics",
    "default_tracer",
    "default_usage_tracker",
    "extract_trace_context",
    "genai_prices_cost",
    "inject_trace_context",
    "metered",
    "provider_reported_cost",
    "resolve_cost",
    "trace_context_scope",
    "traced",
]
