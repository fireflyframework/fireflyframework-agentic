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

"""RAG-specific OTel instruments and a stage-timing helper.

Instruments are created against the global OTel API; whichever
:class:`MeterProvider` is registered when an instrument is first used (via
:func:`fireflyframework_agentic.observability.configure_exporters`)
receives the data. With no provider registered, the OTel API returns NoOp
proxies — code keeps working, telemetry is silently dropped.

The :func:`timed_span` async context manager is the workhorse of the
instrumentation pass: it wraps a code block in a span *and* records its
wall-clock duration to a histogram with the same labels. Spans are
sampled at the backend; histograms are not. Using both gives forensic
drill-down (spans) plus reliable SLO/regression alerts (histograms).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.trace import Span, StatusCode

_tracer = trace.get_tracer("fireflyframework_agentic.rag")
_meter = metrics.get_meter("fireflyframework_agentic.rag")

# ── Histograms (latency) ──────────────────────────────────────────────────
ingest_stage_duration = _meter.create_histogram(
    "firefly.rag.ingest.duration",
    description="Per-stage wall-clock duration inside ingest_one",
    unit="ms",
)
ingest_document_duration = _meter.create_histogram(
    "firefly.rag.ingest.document.duration",
    description="End-to-end ingestion duration per document",
    unit="ms",
)
embed_attempt_duration = _meter.create_histogram(
    "firefly.rag.embed.attempt.duration",
    description="Per-attempt embed call duration",
    unit="ms",
)
query_stage_duration = _meter.create_histogram(
    "firefly.rag.query.duration",
    description="Per-stage wall-clock duration inside query()",
    unit="ms",
)
query_total_duration = _meter.create_histogram(
    "firefly.rag.query.total.duration",
    description="End-to-end query duration",
    unit="ms",
)
retrieve_modality_duration = _meter.create_histogram(
    "firefly.rag.retrieve.modality.duration",
    description="Per-modality retrieval duration (BM25 or vector)",
    unit="ms",
)

# ── Counters ──────────────────────────────────────────────────────────────
ingest_documents = _meter.create_counter(
    "firefly.rag.ingest.documents",
    description="Documents processed by ingest_one (label: status)",
    unit="1",
)
ingest_chunks = _meter.create_counter(
    "firefly.rag.ingest.chunks",
    description="Chunks written to the corpus + vector store",
    unit="1",
)
ingest_bytes = _meter.create_counter(
    "firefly.rag.ingest.bytes",
    description="Source bytes ingested (file size at the time of read)",
    unit="By",
)
embed_retries = _meter.create_counter(
    "firefly.rag.embed.retries",
    description="Embed-call retry attempts (label: provider, outcome)",
    unit="1",
)
rerank_fallback = _meter.create_counter(
    "firefly.rag.rerank.fallback",
    description="Times the reranker fell back to retrieval order due to error",
    unit="1",
)


@asynccontextmanager
async def timed_span(
    name: str,
    *,
    histogram: Any | None = None,
    attributes: dict[str, Any] | None = None,
    metric_labels: dict[str, str] | None = None,
) -> AsyncIterator[Span]:
    """Wrap an async block in a span and (optionally) record its duration to *histogram*.

    Parameters:
        name: Span name (e.g. ``rag.ingest.embed``).
        histogram: Optional OTel ``Histogram`` instrument. When supplied,
            the elapsed time in milliseconds is recorded on exit. **Use
            ``None`` for outer-scope spans whose histogram labels (status,
            outcome) are only known at exit time** — record the histogram
            explicitly at the call site after the labels are resolved.
            Otherwise the labels here are snapshotted at entry, leading to
            stuck-at-`in_flight` histograms.
        attributes: Extra span attributes; namespaced with ``firefly.rag.``
            if not already prefixed. Native types (int, float, bool, str)
            are passed through; everything else is stringified.
        metric_labels: Labels recorded against *histogram*. Ignored when
            ``histogram`` is *None*.

    On exception the span is marked ERROR, the exception is recorded, the
    histogram (if any) still gets the failure-path latency sample, and
    the exception re-propagates.
    """
    start = time.perf_counter()
    span_attrs = _coerce_attrs(attributes)
    labels = metric_labels or {}
    with _tracer.start_as_current_span(name, attributes=span_attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        finally:
            if histogram is not None:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                histogram.record(elapsed_ms, labels)


def _coerce_attrs(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """Namespace attribute keys under ``firefly.rag.`` and pass through
    OTel-native types (int, float, bool, str). Everything else is
    stringified — coercing native types to strings would lose KQL's
    ability to slice on ``customDimensions.bytes > 1000`` against AppInsights.
    """
    if not attributes:
        return {}
    out: dict[str, Any] = {}
    for key, value in attributes.items():
        namespaced = f"firefly.rag.{key}" if "." not in key else key
        out[namespaced] = value if isinstance(value, (int, float, bool, str)) else str(value)
    return out
