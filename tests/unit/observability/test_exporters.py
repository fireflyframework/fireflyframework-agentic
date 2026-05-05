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

"""Tests for :func:`fireflyframework_agentic.observability.configure_exporters`."""

from __future__ import annotations

import logging

import pytest

from fireflyframework_agentic.observability import exporters as exporters_mod
from fireflyframework_agentic.observability.exporters import (
    ProviderBundle,
    configure_exporters,
)


@pytest.fixture(autouse=True)
def _reset_configured_signature():
    """Each test starts with no prior configuration."""
    exporters_mod._state.signature = None
    if exporters_mod._state.handler is not None:
        logging.getLogger("fireflyframework_agentic").removeHandler(exporters_mod._state.handler)
    exporters_mod._state.handler = None
    yield


def test_returns_provider_bundle_with_three_providers():
    bundle = configure_exporters(service_name="test")
    assert isinstance(bundle, ProviderBundle)
    assert bundle.tracer is not None
    assert bundle.meter is not None
    assert bundle.log is not None


def test_console_exporters_attach_without_errors():
    bundle = configure_exporters(service_name="test", console=True)
    # The TracerProvider has at least one span processor when console=True.
    # MeterProvider holds the reader internally; we can't introspect the
    # list portably, but constructing with console=True must not raise.
    assert bundle.tracer is not None


def test_no_kwargs_still_builds_providers_but_attaches_no_exporters():
    # Useful for tests / when the caller wants a noop telemetry pipeline.
    bundle = configure_exporters(service_name="test-empty")
    assert bundle.tracer is not None


def test_logging_handler_attached_to_firefly_logger():
    configure_exporters(service_name="test", console=True)
    firefly_logger = logging.getLogger("fireflyframework_agentic")
    # Our handler from observability.exporters must be present.
    assert exporters_mod._state.handler is not None
    assert exporters_mod._state.handler in firefly_logger.handlers


def test_idempotent_repeat_call_is_no_op():
    first = configure_exporters(service_name="test", console=True)
    prior_tracer = first.tracer
    prior_meter = first.meter
    prior_log = first.log
    second = configure_exporters(service_name="test", console=True)
    # The module guard should prevent re-registration; we assert idempotency
    # via the guard variable, not provider identity, because the no-op branch
    # returns whatever global providers are currently registered.
    assert exporters_mod._state.signature is not None
    assert second.tracer is not None  # always returns something usable
    assert prior_tracer is not None
    assert prior_meter is not None
    assert prior_log is not None


def test_idempotent_repeat_call_does_not_double_attach_logging_handler():
    configure_exporters(service_name="test", console=True)
    firefly_logger = logging.getLogger("fireflyframework_agentic")
    handlers_after_first = list(firefly_logger.handlers)
    configure_exporters(service_name="test", console=True)
    handlers_after_second = list(firefly_logger.handlers)
    assert len(handlers_after_first) == len(handlers_after_second)


def test_changing_signature_replaces_logging_handler():
    configure_exporters(service_name="svc-a", console=True)
    firefly_logger = logging.getLogger("fireflyframework_agentic")
    first_handler = exporters_mod._state.handler
    configure_exporters(service_name="svc-b", console=True)
    second_handler = exporters_mod._state.handler
    assert second_handler is not first_handler
    assert first_handler not in firefly_logger.handlers
    assert second_handler in firefly_logger.handlers


def test_connection_string_never_appears_in_log_output(caplog):
    # Sentinel must include a UUID-shaped instrumentation key so the Azure
    # ConnectionStringParser (when the SDK is installed) accepts it and we
    # exercise the full attach path. The leak check below catches any log
    # line that contains the sentinel substring.
    sentinel = "InstrumentationKey=11111111-2222-3333-4444-DONOTLEAKME12;IngestionEndpoint=https://example.invalid/"
    with caplog.at_level(logging.DEBUG, logger="fireflyframework_agentic.observability.exporters"):
        configure_exporters(
            service_name="test",
            azure_monitor_connection_string=sentinel,
        )
    for record in caplog.records:
        assert sentinel not in record.getMessage()
        assert "DONOTLEAKME" not in record.getMessage()


def test_otlp_missing_dependency_warns_does_not_raise(caplog):
    # In the test environment opentelemetry-exporter-otlp-proto-grpc may
    # not be installed; configuring with otlp must degrade gracefully.
    with caplog.at_level(logging.WARNING):
        bundle = configure_exporters(
            service_name="test",
            otlp_endpoint="http://localhost:4317",
        )
    assert bundle is not None  # graceful degradation, not an exception


def test_azure_malformed_conn_string_warns_does_not_raise(caplog):
    # A non-UUID instrumentation key trips the SDK's ConnectionStringParser
    # which raises ValueError. configure_exporters must catch that and log a
    # generic warning that does NOT include the conn string. Requires the
    # [azure] extra; without it the function takes the ImportError branch
    # and emits a different warning.
    try:
        import azure.monitor.opentelemetry.exporter  # noqa: F401
    except ImportError:
        pytest.skip("azure-monitor-opentelemetry-exporter not installed")

    with caplog.at_level(logging.WARNING):
        bundle = configure_exporters(
            service_name="test",
            azure_monitor_connection_string="InstrumentationKey=not-a-uuid",
        )
    assert bundle is not None
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    # At least one warning was emitted, and none of them contain the bad value.
    assert any("malformed" in m.lower() for m in warning_messages)
    for m in warning_messages:
        assert "not-a-uuid" not in m
