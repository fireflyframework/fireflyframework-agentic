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
    """Point ``FIREFLY_MCP_TOKEN_STORE_FACTORY`` at an in-process stub
    factory so ``build_app`` does not require live Azure credentials.
    The factory itself lives on the test module so the spec
    ``"…:_build_stub_store"`` resolves via the normal import path the
    framework uses in production.
    """

    def _factory(secrets: dict[str, str]):
        # The factory callable is stateless; it closes over the secrets
        # map via a module-level holder so the resolver can find it by
        # name.
        global _STUB_SECRETS
        _STUB_SECRETS = secrets
        monkeypatch.setenv(
            "FIREFLY_MCP_TOKEN_STORE_FACTORY",
            "tests.integration.test_mcp_corpus_auth_e2e:_build_stub_store",
        )

    return _factory


_STUB_SECRETS: dict[str, str] = {}


def _build_stub_store(*, vault_url: str, prefix: str = "firefly-mcp-corpus-token-") -> _StubStore:
    """Factory the e2e tests point ``FIREFLY_MCP_TOKEN_STORE_FACTORY`` at."""
    return _StubStore(_STUB_SECRETS)


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
