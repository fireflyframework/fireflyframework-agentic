# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for the MCP auth module: types, /.well-known/ routes, middleware."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fireflyframework_agentic.exposure.mcp.auth import (
    OAuthJWTMiddleware,
    OAuthMetadata,
    TokenVerifier,
    add_oauth_metadata_routes,
)

_METADATA_URL = "https://mcp.example.com/.well-known/oauth-protected-resource"


def _metadata() -> OAuthMetadata:
    return OAuthMetadata(
        issuer="https://login.example.com/v2.0",
        authorization_endpoint="https://login.example.com/authorize",
        token_endpoint="https://login.example.com/token",
        jwks_uri="https://login.example.com/keys",
        resource="https://mcp.example.com/mcp/",
        scopes_supported=("user_impersonation",),
    )


# ---------- types ----------------------------------------------------------


def test_metadata_holds_values() -> None:
    md = _metadata()
    assert md.issuer == "https://login.example.com/v2.0"
    assert md.scopes_supported == ("user_impersonation",)


def test_metadata_is_frozen() -> None:
    md = _metadata()
    with pytest.raises(dataclasses.FrozenInstanceError):
        md.issuer = "tampered"  # type: ignore[misc]


def test_token_verifier_protocol_runtime_checkable() -> None:
    class Stub:
        def validate_token(self, token: str) -> dict[str, Any]:
            return {"sub": token}

    assert isinstance(Stub(), TokenVerifier)


def test_non_verifier_fails_protocol_check() -> None:
    class NotAVerifier:
        pass

    assert not isinstance(NotAVerifier(), TokenVerifier)


# ---------- /.well-known/ routes -------------------------------------------


def _metadata_client() -> TestClient:
    app = FastAPI()
    add_oauth_metadata_routes(app, _metadata())
    return TestClient(app)


def test_protected_resource_endpoint_shape() -> None:
    body = _metadata_client().get("/.well-known/oauth-protected-resource").json()
    assert body["resource"] == "https://mcp.example.com/mcp/"
    assert body["authorization_servers"] == ["https://login.example.com/v2.0"]
    assert body["scopes_supported"] == ["user_impersonation"]
    assert body["bearer_methods_supported"] == ["header"]


def test_authorization_server_endpoint_shape() -> None:
    body = _metadata_client().get("/.well-known/oauth-authorization-server").json()
    assert body["issuer"] == "https://login.example.com/v2.0"
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")
    assert body["jwks_uri"].endswith("/keys")
    assert "code" in body["response_types_supported"]
    assert "S256" in body["code_challenge_methods_supported"]


def test_metadata_routes_are_public() -> None:
    """Metadata MUST be reachable without auth — clients fetch it before login."""
    client = _metadata_client()
    assert client.get("/.well-known/oauth-protected-resource").status_code == 200
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200


# ---------- middleware ----------------------------------------------------


class _StubVerifier:
    """Returns claims by token; raises ``ValueError`` on unknown token."""

    def __init__(self, claims_by_token: dict[str, dict[str, Any]]) -> None:
        self._claims_by_token = claims_by_token

    def validate_token(self, token: str) -> dict[str, Any]:
        try:
            return self._claims_by_token[token]
        except KeyError as exc:
            raise ValueError("Invalid token") from exc


def _required_role(tool_name: str, corpus_id: str) -> str | None:
    if tool_name in {"corpus_query", "knowledge_search"}:
        return f"Corpus.{corpus_id}.Read"
    if tool_name in {"ingest_corpus_filesystem", "ingest_corpus_structured", "discover_corpus_schema"}:
        return f"Corpus.{corpus_id}.Write"
    return None


def _make_app(*, verifier: _StubVerifier) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        OAuthJWTMiddleware,
        verifier=verifier,
        required_role_fn=_required_role,
        roles_claim="roles",
        mount_path="/mcp",
        metadata_url=_METADATA_URL,
    )

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


def _body(tool: str, corpus_id: str | None = "demo") -> dict[str, Any]:
    args: dict[str, Any] = {}
    if corpus_id is not None:
        args["corpus_id"] = corpus_id
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------- authn -----------------------------------------------------------


def test_anonymous_request_returns_401_with_www_authenticate() -> None:
    client = TestClient(_make_app(verifier=_StubVerifier({})))
    r = client.post("/mcp", json=_body("corpus_query"))
    assert r.status_code == 401
    auth = r.headers["www-authenticate"]
    assert auth.startswith("Bearer")
    assert 'realm="OAuth"' in auth
    assert f'resource_metadata="{_METADATA_URL}"' in auth
    assert 'error="invalid_token"' in auth
    body = r.json()
    assert body["error"] == "invalid_token"
    assert "error_description" in body


def test_missing_bearer_returns_401() -> None:
    client = TestClient(_make_app(verifier=_StubVerifier({})))
    r = client.post("/mcp", headers={"Authorization": "Basic xyz"}, json=_body("corpus_query"))
    assert r.status_code == 401


def test_invalid_token_returns_401() -> None:
    client = TestClient(_make_app(verifier=_StubVerifier({})))
    r = client.post("/mcp", headers=_auth("bad"), json=_body("corpus_query"))
    assert r.status_code == 401


# ---------- authz -----------------------------------------------------------


def test_valid_token_without_required_role_returns_403() -> None:
    v = _StubVerifier({"t1": {"roles": []}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("corpus_query"))
    assert r.status_code == 403


def test_valid_token_with_read_role_passes_read_tool() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Read"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("corpus_query"))
    assert r.status_code == 200


def test_read_role_denied_on_write_tool() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Read"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("ingest_corpus_filesystem"))
    assert r.status_code == 403


def test_write_role_implies_read() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Write"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("corpus_query"))
    assert r.status_code == 200


def test_write_role_passes_write_tool() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Write"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("ingest_corpus_filesystem"))
    assert r.status_code == 200


def test_role_for_one_corpus_does_not_grant_another() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.alpha.Read"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("corpus_query", corpus_id="beta"))
    assert r.status_code == 403


def test_wildcard_write_role_grants_any_corpus_write() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.*.Write"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("ingest_corpus_filesystem", corpus_id="never-seen"))
    assert r.status_code == 200


def test_wildcard_write_role_grants_any_corpus_read() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.*.Write"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("corpus_query", corpus_id="never-seen"))
    assert r.status_code == 200


def test_wildcard_read_role_grants_read_only() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.*.Read"]}})
    client = TestClient(_make_app(verifier=v))
    assert client.post("/mcp", headers=_auth("t1"), json=_body("corpus_query", corpus_id="anything")).status_code == 200
    # Write tool must NOT be granted by ``Corpus.*.Read``.
    assert (
        client.post("/mcp", headers=_auth("t1"), json=_body("ingest_corpus_filesystem", corpus_id="anything")).status_code
        == 403
    )


def test_wildcard_role_publishes_none_authorised_corpora() -> None:
    """list_corpora must see no corpus filter when the caller has the wildcard role."""
    from fireflyframework_agentic.tools.builtins.corpus_rag import (
        authorised_corpora_var,
    )

    captured: dict[str, tuple[str, ...] | None] = {}

    v = _StubVerifier({"t1": {"roles": ["Corpus.*.Write"]}})
    app = _make_app(verifier=v)

    @app.post("/mcp/capture")
    async def capture() -> dict[str, Any]:
        captured["val"] = authorised_corpora_var.get()
        return {"ok": True}

    client = TestClient(app)
    r = client.post(
        "/mcp",
        headers=_auth("t1"),
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_corpora", "arguments": {}}},
    )
    assert r.status_code == 200


# ---------- lifecycle / no-corpus -------------------------------------------


def test_lifecycle_method_passes_with_valid_token_no_roles() -> None:
    v = _StubVerifier({"t1": {"roles": []}})
    client = TestClient(_make_app(verifier=v))
    r = client.post(
        "/mcp",
        headers=_auth("t1"),
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 200


def test_lifecycle_method_still_requires_valid_token() -> None:
    client = TestClient(_make_app(verifier=_StubVerifier({})))
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_list_corpora_passes_with_any_role_and_sets_contextvar() -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import (
        authorised_corpora_var,
    )

    captured: dict[str, tuple[str, ...] | None] = {}

    v = _StubVerifier({"t1": {"roles": ["Corpus.alpha.Read", "Corpus.beta.Write"]}})
    app = _make_app(verifier=v)

    @app.post("/mcp/capture")
    async def capture() -> dict[str, Any]:
        captured["val"] = authorised_corpora_var.get()
        return {"ok": True}

    client = TestClient(app)
    r = client.post(
        "/mcp",
        headers=_auth("t1"),
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_corpora", "arguments": {}}},
    )
    assert r.status_code == 200


# ---------- body shape edge cases ------------------------------------------


def test_missing_corpus_id_returns_400_for_corpus_scoped_tool() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Read"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers=_auth("t1"), json=_body("corpus_query", corpus_id=None))
    assert r.status_code == 400


# ---------- excluded paths --------------------------------------------------


def test_healthz_passes_without_auth() -> None:
    client = TestClient(_make_app(verifier=_StubVerifier({})))
    assert client.get("/healthz").status_code == 200


# ---------- custom roles claim ---------------------------------------------


def test_custom_roles_claim() -> None:
    """A deployment can configure a non-standard roles claim (e.g. Okta's
    'groups')."""
    from fireflyframework_agentic.exposure.mcp.auth import OAuthJWTMiddleware

    app = FastAPI()
    v = _StubVerifier({"t1": {"groups": ["Corpus.demo.Read"]}})
    app.add_middleware(
        OAuthJWTMiddleware,
        verifier=v,
        required_role_fn=_required_role,
        roles_claim="groups",
        mount_path="/mcp",
        metadata_url=_METADATA_URL,
    )

    @app.post("/mcp")
    async def echo(payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    r = TestClient(app).post("/mcp", headers=_auth("t1"), json=_body("corpus_query"))
    assert r.status_code == 200
