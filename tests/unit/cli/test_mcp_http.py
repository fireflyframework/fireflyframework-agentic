# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for the ``firefly-mcp-http`` CLI entrypoint."""

from __future__ import annotations

import pytest

pytest.importorskip("fastmcp", reason="MCP CLI requires fastmcp")
pytest.importorskip("fastapi", reason="MCP HTTP transport requires fastapi")
pytest.importorskip("uvicorn", reason="HTTP CLI requires uvicorn")

from fastapi.testclient import TestClient

from fireflyframework_agentic.cli.mcp_http import build_app


def test_healthz_returns_ok() -> None:
    client = TestClient(build_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_is_mounted() -> None:
    app = build_app()
    mounted_paths = {route.path for route in app.routes}
    assert any(path.startswith("/mcp") for path in mounted_paths)


