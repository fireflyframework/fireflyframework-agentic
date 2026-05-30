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

"""OpenTelemetry exporter configuration helpers.

:func:`configure_exporters` is the single place vendor knowledge lives. It
sets up traces, metrics, and logs providers and attaches the exporters chosen
by which kwargs are passed (console, OTLP).

Application code never imports vendor exporters directly --- it uses
``trace.get_tracer(...)``, ``metrics.get_meter(...)``, and Python ``logging``,
all of which the providers configured here transparently route to whichever
backend is active.
"""

from __future__ import annotations

import logging
import socket
import uuid
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from opentelemetry import _logs as otel_logs
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk._logs.export import ConsoleLogExporter as _ConsoleLogExporter

# Newer SDKs renamed ConsoleLogExporter to ConsoleLogRecordExporter; tolerate both.
try:
    from opentelemetry.sdk._logs.export import (
        ConsoleLogRecordExporter as ConsoleLogExporter,  # type: ignore[import-not-found]
    )
except ImportError:
    ConsoleLogExporter = _ConsoleLogExporter  # type: ignore[assignment, misc]
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

try:
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (  # type: ignore[import-not-found]
        OTLPLogExporter,
    )
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # type: ignore[import-not-found]
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
        OTLPSpanExporter,
    )
except ImportError:  # pragma: no cover - optional dep
    OTLPLogExporter = None  # type: ignore[assignment,misc]
    OTLPMetricExporter = None  # type: ignore[assignment,misc]
    OTLPSpanExporter = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

_FIREFLY_LOGGER_NAME = "fireflyframework_agentic"


def _service_version() -> str:
    """Return the installed package version for the OTel ``service.version``
    resource attribute. Falls back to ``"unknown"`` if the package is not
    installed (e.g. running from a source checkout without ``uv sync``).
    """
    try:
        return version("fireflyframework-agentic")
    except PackageNotFoundError:
        return "unknown"


@dataclass(frozen=True)
class ProviderBundle:
    """The three OTel providers configured by :func:`configure_exporters`.

    Returned so callers can attach extra processors, but the providers are
    also registered globally so ``trace.get_tracer(...)`` / ``metrics.get_meter(...)``
    pick them up automatically.

    The ``tracer`` attribute preserves the legacy return type of
    :func:`configure_exporters`; existing code that did
    ``provider = configure_exporters(...)`` and called
    ``provider.add_span_processor(...)`` should migrate to
    ``configure_exporters(...).tracer``.
    """

    tracer: TracerProvider
    meter: MeterProvider
    log: LoggerProvider


class _ConfigState:
    """Module-level guard so repeat calls don't double-register exporters or
    stack a second LoggingHandler on the firefly logger.

    Encapsulated as a class rather than two ``module-level`` globals so
    static analysers (CodeQL, the github-code-quality bot) correctly see
    the read-then-write pattern as a real read-after-write rather than
    incorrectly flagging the writes as "unused global variables". Same
    runtime behaviour as the previous ``_configured_signature`` and
    ``_logging_handler_installed`` globals.
    """

    signature: tuple[object, ...] | None = None
    handler: LoggingHandler | None = None


_state = _ConfigState()


def configure_exporters(
    *,
    service_name: str = _FIREFLY_LOGGER_NAME,
    otlp_endpoint: str | None = None,
    console: bool = False,
    metric_export_interval_ms: int = 60_000,
) -> ProviderBundle:
    """Set up trace, metric, and log providers with the requested exporters.

    Parameters:
        service_name: OTel ``service.name`` resource attribute.
        otlp_endpoint: When set, attaches gRPC OTLP exporters for traces,
            metrics, and logs. Vendor-neutral path (Jaeger, Tempo, ADOT, ...).
        console: When *True*, attaches console exporters for all three signal
            types. Useful for local development.
        metric_export_interval_ms: How often the metric reader flushes
            histograms and counters. Default 60s.

    Returns:
        A :class:`ProviderBundle` exposing the three providers. The providers
        are also registered globally; in most cases callers do not need to
        touch the bundle.

    Notes:
        - **Idempotent**: repeat calls with identical effective configuration
          are a no-op. The kwargs become a signature tuple keyed against
          ``_state.signature``.
        - A :class:`LoggingHandler` is attached to the
          ``fireflyframework_agentic`` parent logger so both
          ``logger.info(...)`` calls and :class:`FireflyEvents` payloads are
          delivered through OTel logs to whichever exporter is active.
    """
    signature = (
        service_name,
        otlp_endpoint,
        console,
        metric_export_interval_ms,
    )
    if _state.signature == signature:
        # Nothing to do; existing providers already serve get_tracer/get_meter.
        return ProviderBundle(
            tracer=trace.get_tracer_provider(),  # type: ignore[return-value]
            meter=otel_metrics.get_meter_provider(),  # type: ignore[return-value]
            log=otel_logs.get_logger_provider(),  # type: ignore[return-value]
        )

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": _service_version(),
            "service.instance.id": f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}",
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    metric_readers: list[PeriodicExportingMetricReader] = []
    logger_provider = LoggerProvider(resource=resource)

    # ── Console exporters ──────────────────────────────────────────────────
    if console:
        tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        metric_readers.append(
            PeriodicExportingMetricReader(
                ConsoleMetricExporter(),
                export_interval_millis=metric_export_interval_ms,
            )
        )
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(ConsoleLogExporter()))
        logger.info("Console exporters attached")

    # ── OTLP exporters (Jaeger, Tempo, ADOT, generic collectors) ──────────
    if otlp_endpoint:
        if OTLPSpanExporter is None or OTLPMetricExporter is None or OTLPLogExporter is None:
            logger.warning(
                "opentelemetry-exporter-otlp-proto-grpc is not installed; "
                "OTLP export disabled. Install the package to enable it."
            )
        else:
            tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
            metric_readers.append(
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=otlp_endpoint),
                    export_interval_millis=metric_export_interval_ms,
                )
            )
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=otlp_endpoint)))
            logger.info("OTLP exporters attached: %s", otlp_endpoint)

    # MeterProvider takes its readers up front, not via add_*().
    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)

    trace.set_tracer_provider(tracer_provider)
    otel_metrics.set_meter_provider(meter_provider)
    otel_logs.set_logger_provider(logger_provider)

    # Bridge Python logging -> OTel logs once; replace any prior handler we
    # installed so repeat calls with new providers point at the new ones.
    firefly_logger = logging.getLogger(_FIREFLY_LOGGER_NAME)
    if _state.handler is not None:
        firefly_logger.removeHandler(_state.handler)
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    firefly_logger.addHandler(handler)
    _state.handler = handler

    _state.signature = signature
    return ProviderBundle(tracer=tracer_provider, meter=meter_provider, log=logger_provider)
