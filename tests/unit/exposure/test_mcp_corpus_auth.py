# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for CorpusAuthMiddleware."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi", reason="middleware requires fastapi")
pytest.importorskip("starlette", reason="middleware requires starlette")
pytest.importorskip("azure.keyvault.secrets.aio", reason="middleware uses azure SDK types")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fireflyframework_agentic.exposure.mcp.auth import CORPUS_ID_HEADER


class _StubStore:
    """Stand-in for KeyVaultTokenStore."""

    def __init__(self, secrets: dict[str, str | None] | None = None) -> None:
        self._secrets = secrets or {}
        self.calls: list[str] = []
        self.exc: BaseException | None = None

    async def get_corpus_token(self, corpus_id: str) -> str | None:
        self.calls.append(corpus_id)
        if self.exc is not None:
            raise self.exc
        return self._secrets.get(corpus_id)


def _make_app(*, store: _StubStore, ttl: float = 60.0) -> FastAPI:
    from fireflyframework_agentic.exposure.mcp.auth import CorpusAuthMiddleware
    from fireflyframework_agentic.security.keyvault import CorpusTokenCache

    app = FastAPI()
    cache = CorpusTokenCache(ttl_seconds=ttl)
    app.add_middleware(CorpusAuthMiddleware, store=store, cache=cache, mount_path="/mcp")

    @app.post("/mcp")
    async def echo(payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "payload": payload}

    @app.get("/mcp")
    async def echo_get() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _h(token: str, corpus_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", CORPUS_ID_HEADER: corpus_id}


def _body(corpus_id: str, *, tool: str = "corpus_query") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": {"corpus_id": corpus_id, "question": "hi", "top_k": 3},
        },
    }


# ---------- happy path / negative authn ------------------------------------


def test_happy_path_forwards_request_when_bearer_matches() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post("/mcp", json=_body("demo"), headers=_h("secret-token", "demo"))
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert store.calls == ["demo"]


def test_missing_bearer_returns_401() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post("/mcp", json=_body("demo"), headers={CORPUS_ID_HEADER: "demo"})
    assert response.status_code == 401


def test_malformed_bearer_returns_401() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post(
        "/mcp",
        json=_body("demo"),
        headers={"Authorization": "Token nope", CORPUS_ID_HEADER: "demo"},
    )
    assert response.status_code == 401


def test_missing_corpus_id_header_returns_401() -> None:
    """No X-Firefly-Corpus-Id ⇒ 401 BEFORE any body / lifecycle inspection."""
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post(
        "/mcp",
        json=_body("demo"),
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 401


def test_healthz_is_not_gated() -> None:
    store = _StubStore({})
    client = TestClient(_make_app(store=store))
    response = client.get("/healthz")
    assert response.status_code == 200


# ---------- forbid paths ----------------------------------------------------


def test_wrong_token_returns_403() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post("/mcp", json=_body("demo"), headers=_h("wrong-bearer", "demo"))
    assert response.status_code == 403
    assert "wrong-bearer" not in response.text


def test_token_for_other_corpus_returns_403() -> None:
    """Bearer for corpus-a, header claims corpus-b ⇒ deny."""
    store = _StubStore({"corpus-a": "token-a", "corpus-b": "token-b"})
    client = TestClient(_make_app(store=store))
    response = client.post("/mcp", json=_body("corpus-b"), headers=_h("token-a", "corpus-b"))
    assert response.status_code == 403


def test_header_body_corpus_id_mismatch_returns_403() -> None:
    """Bearer valid for header corpus, but body asks for a different one."""
    store = _StubStore({"corpus-a": "token-a"})
    client = TestClient(_make_app(store=store))
    response = client.post("/mcp", json=_body("corpus-b"), headers=_h("token-a", "corpus-a"))
    assert response.status_code == 403


def test_unknown_corpus_returns_403_not_404() -> None:
    """Avoid enumeration: missing secret looks identical to wrong token."""
    store = _StubStore({})
    client = TestClient(_make_app(store=store))
    response = client.post("/mcp", json=_body("ghost"), headers=_h("anything", "ghost"))
    assert response.status_code == 403


# ---------- outage / cache / shape -----------------------------------------


def test_kv_outage_returns_503() -> None:
    from azure.core.exceptions import ServiceRequestError

    store = _StubStore({"demo": "secret-token"})
    store.exc = ServiceRequestError(message="boom")
    client = TestClient(_make_app(store=store))
    response = client.post("/mcp", json=_body("demo"), headers=_h("secret-token", "demo"))
    assert response.status_code == 503


def test_cache_avoids_repeat_kv_lookups() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store, ttl=60))
    h = _h("secret-token", "demo")
    for _ in range(3):
        assert client.post("/mcp", json=_body("demo"), headers=h).status_code == 200
    assert store.calls == ["demo"]


def test_missing_body_corpus_id_returns_400() -> None:
    """tools/call against a corpus-scoped tool with no body corpus_id ⇒ 400."""
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "corpus_query", "arguments": {}},
    }
    response = client.post("/mcp", json=body, headers=_h("secret-token", "demo"))
    assert response.status_code == 400


def test_body_is_forwarded_intact() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    payload = _body("demo")
    response = client.post("/mcp", json=payload, headers=_h("secret-token", "demo"))
    assert response.status_code == 200
    assert response.json()["payload"] == payload


def test_log_capture_does_not_contain_raw_token(caplog: pytest.LogCaptureFixture) -> None:
    import logging as _logging

    caplog.set_level(_logging.DEBUG)
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    for h in (
        _h("secret-token", "demo"),
        _h("wrong-token", "demo"),
        {CORPUS_ID_HEADER: "demo"},
    ):
        client.post("/mcp", json=_body("demo"), headers=h)
    captured = caplog.text
    assert "secret-token" not in captured
    assert "wrong-token" not in captured


# ---------- pass-through paths still require valid bearer ------------------


def test_list_corpora_requires_valid_bearer() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    # No header ⇒ 401, NOT a free pass.
    body = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "list_corpora", "arguments": {}},
    }
    no_corpus_hdr = client.post("/mcp", json=body, headers={"Authorization": "Bearer secret-token"})
    assert no_corpus_hdr.status_code == 401

    # Bad token ⇒ 403.
    bad_token = client.post("/mcp", json=body, headers=_h("wrong", "demo"))
    assert bad_token.status_code == 403

    # Valid header-bound bearer ⇒ 200.
    ok = client.post("/mcp", json=body, headers=_h("secret-token", "demo"))
    assert ok.status_code == 200


def test_initialize_requires_valid_bearer() -> None:
    """The MCP handshake also needs a valid header-bound bearer now."""
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    body = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "x", "version": "0"}},
    }
    # No header → 401.
    assert client.post("/mcp", json=body).status_code == 401
    # Wrong bearer → 403.
    assert client.post("/mcp", json=body, headers=_h("nope", "demo")).status_code == 403
    # Valid → 200.
    assert client.post("/mcp", json=body, headers=_h("secret-token", "demo")).status_code == 200


def test_tools_list_requires_valid_bearer() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    assert client.post("/mcp", json=body).status_code == 401
    assert client.post("/mcp", json=body, headers=_h("secret-token", "demo")).status_code == 200


def test_notifications_require_valid_bearer() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    body = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    assert client.post("/mcp", json=body).status_code == 401
    assert client.post("/mcp", json=body, headers=_h("secret-token", "demo")).status_code == 200


def test_get_for_sse_requires_valid_bearer() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    # No header → 401.
    assert client.get("/mcp").status_code == 401
    # Wrong bearer → 403.
    assert client.get("/mcp", headers=_h("nope", "demo")).status_code == 403
    # Valid → downstream handler runs (200/404/200 are all non-deny).
    response = client.get("/mcp", headers=_h("secret-token", "demo"))
    assert response.status_code not in (400, 401, 403)


def test_authorised_corpora_contextvar_is_set() -> None:
    """The middleware must populate the contextvar list_corpora reads."""
    from fastapi import FastAPI

    from fireflyframework_agentic.exposure.mcp.auth import CorpusAuthMiddleware
    from fireflyframework_agentic.security.keyvault import CorpusTokenCache
    from fireflyframework_agentic.tools.builtins import corpus_rag as cr

    captured: list[tuple[str, ...] | None] = []

    store = _StubStore({"demo": "secret-token"})
    app = FastAPI()
    app.add_middleware(
        CorpusAuthMiddleware,
        store=store,
        cache=CorpusTokenCache(ttl_seconds=60),
        mount_path="/mcp",
    )

    @app.post("/mcp")
    async def handler(payload: dict[str, Any]) -> dict[str, Any]:
        captured.append(cr.authorised_corpora_var.get())
        return {"ok": True}

    client = TestClient(app)
    client.post("/mcp", json=_body("demo"), headers=_h("secret-token", "demo"))
    assert captured == [("demo",)]
