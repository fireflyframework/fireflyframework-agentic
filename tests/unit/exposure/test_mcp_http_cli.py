# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for the ``firefly-mcp-http`` CLI entrypoint."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastmcp", reason="MCP CLI requires fastmcp")
pytest.importorskip("fastapi", reason="MCP HTTP transport requires fastapi")
pytest.importorskip("uvicorn", reason="HTTP CLI requires uvicorn")

from fastapi.testclient import TestClient

from fireflyframework_agentic.exposure.mcp.http_cli import build_app, main


def test_healthz_returns_ok() -> None:
    client = TestClient(build_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_is_mounted() -> None:
    app = build_app()
    mounted_paths = {route.path for route in app.routes}
    assert any(path.startswith("/mcp") for path in mounted_paths)


# ---- main() dotenv loading -----------------------------------------------
#
# Locks the precedence story the docstring asserts: real env vars always win
# over .env, so Azure / Container Apps deployments (which inject env before
# the process starts) see no behavioural change, while local dev gets the
# .env load for free.


def _stub_uvicorn_run(*args, **kwargs):
    """No-op replacement for uvicorn.run — keeps main() from binding a port."""
    return None


def test_main_loads_dotenv_when_var_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local-dev path: a key absent from the process env is populated from .env."""
    pytest.importorskip("dotenv", reason="needs python-dotenv installed (the corpus-search / dev extra)")
    monkeypatch.delenv("FIREFLY_TEST_DOTENV_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FIREFLY_TEST_DOTENV_KEY=from_dotenv\n")
    with patch("fireflyframework_agentic.exposure.mcp.http_cli.uvicorn.run", new=_stub_uvicorn_run):
        main()
    assert os.environ.get("FIREFLY_TEST_DOTENV_KEY") == "from_dotenv"


def test_main_does_not_override_existing_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Azure / production path: a key already in the env wins over .env.

    This is the load-bearing assertion: in Azure Container Apps every env
    var comes from the manifest / Key Vault binding before the Python
    process starts, so each lookup finds an existing value and ``.env``
    must not silently rewrite it.
    """
    pytest.importorskip("dotenv", reason="needs python-dotenv installed (the corpus-search / dev extra)")
    monkeypatch.setenv("FIREFLY_TEST_DOTENV_KEY", "from_real_env")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FIREFLY_TEST_DOTENV_KEY=from_dotenv\n")
    with patch("fireflyframework_agentic.exposure.mcp.http_cli.uvicorn.run", new=_stub_uvicorn_run):
        main()
    assert os.environ.get("FIREFLY_TEST_DOTENV_KEY") == "from_real_env"


def test_main_tolerates_missing_dotenv_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hardened-install path: when python-dotenv isn't installed, the CLI
    still starts. The guarded import inside main() turns ImportError into a
    silent no-op so a slim deploy without the corpus-search / dev extras
    doesn't break on startup.
    """
    import builtins

    real_import = builtins.__import__

    def _import(name: str, *args, **kwargs):
        if name == "dotenv":
            raise ImportError("simulated missing dotenv")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    with patch("fireflyframework_agentic.exposure.mcp.http_cli.uvicorn.run", new=_stub_uvicorn_run):
        main()  # would have raised before the ImportError guard
