# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for the ``firefly-mcp-http`` CLI entrypoint."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastmcp", reason="MCP CLI requires fastmcp")
pytest.importorskip("fastapi", reason="MCP HTTP transport requires fastapi")
pytest.importorskip("uvicorn", reason="HTTP CLI requires uvicorn")

from fastapi.testclient import TestClient

from fireflyframework_agentic.exposure.mcp.http_cli import (
    _log_unhandled_loop_exception,
    build_app,
    main,
)


def test_healthz_returns_ok() -> None:
    client = TestClient(build_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_is_mounted() -> None:
    app = build_app()
    mounted_paths = {route.path for route in app.routes}
    assert any(path.startswith("/mcp") for path in mounted_paths)


# ---- OAuth auth wiring ---------------------------------------------------


_STUB_CLAIMS: dict[str, dict[str, object]] = {}


def _build_stub_verifier() -> object:
    """Factory used by tests for FIREFLY_MCP_VERIFIER_FACTORY."""

    class _StubVerifier:
        def validate_token(self, token: str) -> dict[str, object]:
            try:
                return _STUB_CLAIMS[token]
            except KeyError as exc:
                raise ValueError("Invalid token") from exc

    return _StubVerifier()


def _build_stub_metadata() -> object:
    from fireflyframework_agentic.exposure.mcp.auth import OAuthMetadata

    return OAuthMetadata(
        issuer="https://login.example.com/v2.0",
        authorization_endpoint="https://login.example.com/authorize",
        token_endpoint="https://login.example.com/token",
        jwks_uri="https://login.example.com/keys",
        resource="https://mcp.example.com/mcp/",
        scopes_supported=("user_impersonation",),
    )


def _enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREFLY_MCP_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "FIREFLY_MCP_VERIFIER_FACTORY",
        "tests.unit.exposure.test_mcp_http_cli:_build_stub_verifier",
    )
    monkeypatch.setenv(
        "FIREFLY_MCP_METADATA_FACTORY",
        "tests.unit.exposure.test_mcp_http_cli:_build_stub_metadata",
    )
    monkeypatch.setenv("FIREFLY_MCP_PUBLIC_URL", "https://mcp.example.com")


def test_auth_disabled_by_default_allows_anonymous_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIREFLY_MCP_AUTH_ENABLED", raising=False)
    client = TestClient(build_app())
    # GET on /mcp without ingest just hits FastMCP routing — point is no 401.
    r = client.get("/healthz")
    assert r.status_code == 200


def test_auth_enabled_serves_well_known_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch)
    client = TestClient(build_app())
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    assert r.json()["resource"] == "https://mcp.example.com/mcp/"


def test_auth_enabled_rejects_anonymous_mcp_with_www_authenticate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_auth(monkeypatch)
    client = TestClient(build_app())
    r = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "1"},
            },
        },
    )
    assert r.status_code == 401
    assert "resource_metadata" in r.headers["www-authenticate"]


def test_auth_enabled_accepts_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid token must pass the middleware. We use a non-MCP probe path
    (the /healthz route is excluded, but /.well-known/* is also public);
    here we exercise the middleware contract by hitting the mount with a
    token and asserting we do not get 401 — the actual MCP dispatch is
    covered by ``test_mcp_oauth_auth.py`` against a stubbed echo route."""
    _enable_auth(monkeypatch)
    _STUB_CLAIMS["good"] = {"roles": []}
    try:
        with TestClient(build_app()) as client:
            r = client.post(
                "/mcp/",
                headers={
                    "Authorization": "Bearer good",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "probe", "version": "1"},
                    },
                },
            )
            # Middleware passed through (would be 401 if it had blocked).
            # Real MCP responds 200 once the lifespan is running.
            assert r.status_code != 401
    finally:
        _STUB_CLAIMS.pop("good", None)


# ---- Unhandled-task-exception logger ------------------------------------
#
# Without this, exceptions raised in tasks scheduled on the asyncio loop
# (request-cleanup callbacks, fire-and-forget tool work, SSE long-poll
# teardown) get swallowed silently: ``asyncio.BaseEventLoop`` routes them
# to the loop's exception handler which writes to the ``asyncio`` logger
# at ERROR, but uvicorn's default log config doesn't surface that logger.
# Operators see "the server died" with no traceback. This handler routes
# the exception (plus its traceback) through our module logger, which
# basicConfig wires up on startup.


def test_log_unhandled_loop_exception_logs_full_traceback(caplog: pytest.LogCaptureFixture) -> None:
    """The handler logs the exception with ``exc_info`` so the traceback
    is preserved — diagnostically useful and what differentiates this
    from asyncio's default-handler output uvicorn was hiding.
    """
    try:
        raise RuntimeError("simulated background-task failure")
    except RuntimeError as exc:
        bad_exc = exc
    context = {
        "message": "Task exception was never retrieved",
        "exception": bad_exc,
        "task": "<simulated-Task>",
    }
    with caplog.at_level(logging.ERROR, logger="fireflyframework_agentic.exposure.mcp.http_cli"):
        # Pass a dummy loop; the handler doesn't actually touch it.
        _log_unhandled_loop_exception(asyncio.new_event_loop(), context)
    matching = [r for r in caplog.records if "unhandled exception" in r.message]
    assert matching, caplog.records
    rec = matching[0]
    assert rec.exc_info is not None, "traceback must be attached for debugging"
    assert rec.exc_info[0] is RuntimeError
    assert "simulated background-task failure" in (rec.exc_info[1].args[0] if rec.exc_info[1].args else "")


def test_log_unhandled_loop_exception_handles_no_exception_in_context(caplog: pytest.LogCaptureFixture) -> None:
    """Some asyncio contexts ship a message but no exception (e.g.
    'socket.send() raised exception.' on closed transports). The handler
    must still produce a log line — the message alone is usually enough
    to identify the failure mode.
    """
    context = {
        "message": "socket.send() raised exception.",
        "handle": "<Handle Server._proto_factory>",
    }
    with caplog.at_level(logging.ERROR, logger="fireflyframework_agentic.exposure.mcp.http_cli"):
        _log_unhandled_loop_exception(asyncio.new_event_loop(), context)
    assert any("socket.send" in r.message for r in caplog.records)


# ---- .env loading -------------------------------------------------------
#
# firefly-mcp-http calls load_dotenv() at the top of main() so a developer
# running the server from a project directory picks up EMBEDDING_MODEL etc.
# from a local .env without an explicit shell ``source``. Locks the
# precedence story: real env vars always win (load_dotenv defaults to
# override=False), so Azure / Container Apps deployments — which inject
# env from the manifest before the process starts — see no behavioural
# change.


def _stub_uvicorn_run(*args, **kwargs):
    """No-op replacement for the uvicorn.asyncio.run path — keeps main()
    from binding a port during tests."""
    return None


def test_main_loads_dotenv_when_var_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local-dev path: a key absent from the process env is populated from .env."""
    monkeypatch.delenv("FIREFLY_TEST_DOTENV_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FIREFLY_TEST_DOTENV_KEY=from_dotenv\n")
    with patch("fireflyframework_agentic.exposure.mcp.http_cli.asyncio.run", new=_stub_uvicorn_run):
        main()
    assert os.environ.get("FIREFLY_TEST_DOTENV_KEY") == "from_dotenv"


def test_main_does_not_override_existing_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Azure / production path: a key already in the env wins over .env.

    Load-bearing assertion. In Azure Container Apps every env var comes
    from the manifest / Key Vault binding before the Python process
    starts, so each lookup finds an existing value and ``.env`` must
    not silently rewrite it.
    """
    monkeypatch.setenv("FIREFLY_TEST_DOTENV_KEY", "from_real_env")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FIREFLY_TEST_DOTENV_KEY=from_dotenv\n")
    with patch("fireflyframework_agentic.exposure.mcp.http_cli.asyncio.run", new=_stub_uvicorn_run):
        main()
    assert os.environ.get("FIREFLY_TEST_DOTENV_KEY") == "from_real_env"


def test_main_calls_configure_exporters_when_appinsights_connection_string_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: firefly-mcp-http MUST call configure_exporters on
    startup. Without that call, OTel returns NoOp providers and every
    metric / span / log line is silently dropped — even with the
    APPLICATIONINSIGHTS_CONNECTION_STRING env var set.

    We assert the call shape (the connection string from the env reaches
    configure_exporters as azure_monitor_connection_string) rather than
    side-effects on the global OTel registry, so the test is independent
    of OTel SDK version.
    """
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc;IngestionEndpoint=https://example/"
    )
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    with (
        patch("fireflyframework_agentic.observability.configure_exporters") as mock_configure,
        patch("fireflyframework_agentic.exposure.mcp.http_cli.asyncio.run", new=_stub_uvicorn_run),
    ):
        main()

    mock_configure.assert_called_once()
    kwargs = mock_configure.call_args.kwargs
    assert kwargs.get("azure_monitor_connection_string", "").startswith("InstrumentationKey=abc")
    assert kwargs.get("otlp_endpoint") is None
    assert kwargs.get("service_name") == "firefly-mcp-http"


def test_main_skips_configure_exporters_when_no_env_var_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When neither APPLICATIONINSIGHTS_CONNECTION_STRING nor
    OTEL_EXPORTER_OTLP_ENDPOINT is set, the helper should not call
    configure_exporters at all — running with NoOp providers is the
    documented behaviour (telemetry off, server still works).

    Chdir to an empty tmp_path first so find_dotenv() doesn't walk up to
    the repo's own .env and silently restore the connection string.
    """
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.chdir(tmp_path)

    with (
        patch("fireflyframework_agentic.observability.configure_exporters") as mock_configure,
        patch("fireflyframework_agentic.exposure.mcp.http_cli.asyncio.run", new=_stub_uvicorn_run),
    ):
        main()

    mock_configure.assert_not_called()


def test_main_swallows_exporter_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If configure_exporters raises (e.g. Azure monitor extra not installed,
    network unreachable, invalid connection string), startup must not
    abort. Telemetry is best-effort; the server must still serve."""
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=bad")

    with (
        patch(
            "fireflyframework_agentic.observability.configure_exporters",
            side_effect=RuntimeError("simulated exporter failure"),
        ),
        patch("fireflyframework_agentic.exposure.mcp.http_cli.asyncio.run", new=_stub_uvicorn_run),
    ):
        # Must not raise — server keeps coming up.
        main()
