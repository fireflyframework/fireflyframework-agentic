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
