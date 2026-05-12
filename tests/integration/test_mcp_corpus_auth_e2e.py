# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""End-to-end auth gating through ``build_app``.

These tests exercise the full FastAPI app produced by ``build_app()``
with the feature flag enabled, stubbing only the Key Vault store so the
test does not require live Azure credentials.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="MCP HTTP build_app requires fastapi")
pytest.importorskip("fastmcp", reason="MCP HTTP build_app requires fastmcp")
pytest.importorskip("azure.keyvault.secrets.aio", reason="auth requires azure SDK")

from fastapi.testclient import TestClient


class _StubStore:
    """Stand-in for KeyVaultTokenStore."""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    async def get_corpus_token(self, corpus_id: str) -> str | None:
        return self._secrets.get(corpus_id)


@pytest.fixture
def stub_kv(monkeypatch: pytest.MonkeyPatch):
    """Patch ``build_default_store`` so build_app does not require live KV."""
    from fireflyframework_agentic.security import keyvault as kv_mod

    def _factory(secrets: dict[str, str]):
        def _stub(*, vault_url: str, prefix: str = "firefly-mcp-corpus-token-") -> _StubStore:
            return _StubStore(secrets)

        monkeypatch.setattr(kv_mod, "build_default_store", _stub)

    return _factory


def _enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREFLY_MCP_CORPUS_AUTH_ENABLED", "true")
    monkeypatch.setenv("FIREFLY_MCP_KEYVAULT_URL", "https://stub.vault.azure.net")


def test_unauth_request_to_mcp_is_rejected(monkeypatch: pytest.MonkeyPatch, stub_kv) -> None:
    _enable_auth(monkeypatch)
    stub_kv({"demo": "secret-token"})

    from fireflyframework_agentic.exposure.mcp import http_cli

    app = http_cli.build_app()
    client = TestClient(app)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "corpus_query",
                "arguments": {"corpus_id": "demo", "question": "hi", "top_k": 3},
            },
        },
    )
    assert response.status_code == 401


def test_healthz_remains_public_with_auth_enabled(monkeypatch: pytest.MonkeyPatch, stub_kv) -> None:
    _enable_auth(monkeypatch)
    stub_kv({})

    from fireflyframework_agentic.exposure.mcp import http_cli

    app = http_cli.build_app()
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200


def test_auth_disabled_by_default_keeps_behaviour() -> None:
    from fireflyframework_agentic.exposure.mcp import http_cli

    app = http_cli.build_app()

    # CorpusAuthMiddleware must NOT be in the middleware stack when the
    # feature flag is off — otherwise stdio-only deployments would start
    # requiring Key Vault. Starlette stores user middleware on
    # ``app.user_middleware``.
    middleware_classes = {m.cls.__name__ for m in app.user_middleware}
    assert "CorpusAuthMiddleware" not in middleware_classes

    # /healthz still works.
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200


def test_auth_enabled_installs_middleware(monkeypatch: pytest.MonkeyPatch, stub_kv) -> None:
    _enable_auth(monkeypatch)
    stub_kv({"demo": "secret-token"})

    from fireflyframework_agentic.exposure.mcp import http_cli

    app = http_cli.build_app()
    middleware_classes = {m.cls.__name__ for m in app.user_middleware}
    assert "CorpusAuthMiddleware" in middleware_classes


def test_build_app_raises_when_flag_on_but_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIREFLY_MCP_CORPUS_AUTH_ENABLED", "true")
    monkeypatch.delenv("FIREFLY_MCP_KEYVAULT_URL", raising=False)

    from fireflyframework_agentic.exposure.mcp import http_cli

    with pytest.raises(RuntimeError, match="FIREFLY_MCP_KEYVAULT_URL"):
        http_cli.build_app()
