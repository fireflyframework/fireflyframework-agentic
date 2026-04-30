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

"""Explainability subpackage -- trace recording, explanations, audit, and reports."""

from fireflyframework_agentic.explainability.audit import AuditEntry, AuditTrail
from fireflyframework_agentic.explainability.explanation import ExplanationGenerator
from fireflyframework_agentic.explainability.report import (
    ExplainabilityReport,
    ReportBuilder,
    ReportSection,
)
from fireflyframework_agentic.explainability.trace_recorder import (
    DecisionRecord,
    TraceRecorder,
    default_trace_recorder,
)

__all__ = [
    "AuditEntry",
    "AuditTrail",
    "DecisionRecord",
    "ExplainabilityReport",
    "ExplanationGenerator",
    "ReportBuilder",
    "ReportSection",
    "TraceRecorder",
    "default_trace_recorder",
]
