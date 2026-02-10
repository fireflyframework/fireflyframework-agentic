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

"""OpenTelemetry exporter configuration helpers.

Provides a one-call :func:`configure_exporters` that sets up span
exporters based on framework configuration.
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

logger = logging.getLogger(__name__)


def configure_exporters(
    *,
    service_name: str = "fireflyframework_genai",
    otlp_endpoint: str | None = None,
    console: bool = False,
) -> TracerProvider:
    """Set up and return a :class:`TracerProvider` with the requested exporters.

    Parameters:
        service_name: The OTel service name attribute.
        otlp_endpoint: If provided, a gRPC OTLP exporter is added.
        console: If *True*, a console exporter is added (useful for development).

    Returns:
        The configured :class:`TracerProvider`.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
                OTLPSpanExporter,
            )

            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info("OTLP exporter configured: %s", otlp_endpoint)
        except ImportError:
            logger.warning(
                "opentelemetry-exporter-otlp-proto-grpc is not installed; "
                "OTLP export is disabled. Install the package to enable it."
            )

    if console:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        logger.info("Console span exporter configured")

    trace.set_tracer_provider(provider)
    return provider
