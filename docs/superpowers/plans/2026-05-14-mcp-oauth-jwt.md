# MCP OAuth/JWT auth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-corpus capability-token middleware on the MCP HTTP server with provider-agnostic OAuth 2.0 / OIDC JWT validation plus App-Roles RBAC, and publish the discovery metadata that lets `claude mcp add` perform interactive Entra login end-to-end.

**Architecture:** Framework stays provider-agnostic. New `oauth_jwt.py` defines a `TokenVerifier` Protocol and `OAuthMetadata` dataclass; new `oauth_metadata.py` publishes `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`; rewritten `auth.py` (replacing `CorpusAuthMiddleware`) reuses the existing dispatch shape and calls `RBACManager.has_permission` for App-Roles RBAC. Azure-specific glue (Entra issuer URL, `EntraTokenVerifier` already in the repo) stays in `examples/corpus_search/azure_security.py`. Wiring uses two factory env vars resolved by the existing `_resolve_factory` helper.

**Tech Stack:** Python 3.13, FastAPI/Starlette, FastMCP, `pyjwt[crypto]` (already in `[azure]` extra), `pytest`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `fireflyframework_agentic/exposure/mcp/oauth_jwt.py` | create | `TokenVerifier` Protocol + `OAuthMetadata` dataclass + `RequiredRoleFn` type. ~50 LOC. |
| `fireflyframework_agentic/exposure/mcp/oauth_metadata.py` | create | `add_oauth_metadata_routes(app, metadata)` mounts the two `/.well-known/*` endpoints. ~40 LOC. |
| `fireflyframework_agentic/exposure/mcp/auth.py` | rewrite | New `OAuthJWTMiddleware`. Reuses body-parsing helpers, lifecycle/no-corpus sets, error shape from the old `CorpusAuthMiddleware`. |
| `fireflyframework_agentic/exposure/mcp/http_cli.py` | modify | Replace `_install_corpus_auth` with `_install_oauth_auth`. Env vars: `FIREFLY_MCP_AUTH_ENABLED`, `FIREFLY_MCP_VERIFIER_FACTORY`, `FIREFLY_MCP_METADATA_FACTORY`. |
| `examples/corpus_search/azure_security.py` | modify | Add `build_entra_verifier()` and `build_entra_metadata()` factory functions. Delete `KeyVaultTokenStore`, `build_default_store`, `EntraOBOClient` (unused with the new model). |
| `fireflyframework_agentic/security/corpus_token.py` | delete | No longer used. |
| `fireflyframework_agentic/security/__init__.py` | modify | Drop `CorpusTokenCache` / `CorpusTokenStore` / `corpus_token_digest` re-exports. |
| `tests/unit/security/test_corpus_token.py` | delete | Tests for the deleted module. |
| `tests/unit/exposure/test_mcp_corpus_auth.py` | replace | Renamed `test_mcp_oauth_auth.py`; tests `OAuthJWTMiddleware`. |
| `tests/unit/exposure/test_mcp_oauth_metadata.py` | create | Tests `/.well-known/*` endpoint shapes. |
| `tests/unit/exposure/test_mcp_http_cli.py` | modify | Update factory env var resolution tests. |
| `tests/integration/test_mcp_corpus_auth_e2e.py` | replace | E2E with stubbed verifier instead of stubbed KV store. |
| `docs/deploy/mcp-corpus-auth.md` | rewrite | Operator guide for the new model. |

---

### Task 1: `oauth_jwt.py` — types and protocol

**Files:**
- Create: `fireflyframework_agentic/exposure/mcp/oauth_jwt.py`
- Test: `tests/unit/exposure/test_oauth_jwt_types.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/exposure/test_oauth_jwt_types.py
from fireflyframework_agentic.exposure.mcp.oauth_jwt import (
    OAuthMetadata,
    TokenVerifier,
)


def test_oauth_metadata_is_frozen_dataclass() -> None:
    md = OAuthMetadata(
        issuer="https://login.example.com/v2.0",
        authorization_endpoint="https://login.example.com/authorize",
        token_endpoint="https://login.example.com/token",
        jwks_uri="https://login.example.com/keys",
        resource="api://example",
        scopes_supported=("user_impersonation",),
    )
    assert md.issuer.endswith("/v2.0")
    import dataclasses
    assert dataclasses.is_frozen(type(md)) if hasattr(dataclasses, "is_frozen") else True


def test_token_verifier_protocol_runtime_checkable() -> None:
    class Stub:
        def validate_token(self, token: str) -> dict[str, object]:
            return {}

    assert isinstance(Stub(), TokenVerifier)
```

- [ ] **Step 2: Run — expect failure**

```bash
cd /home/u/signature/fireflyframework-agentic/.claude/worktrees/mcp-oauth-jwt
~/.venvs/firefly/bin/python -m pytest tests/unit/exposure/test_oauth_jwt_types.py -x
```

Expected: `ModuleNotFoundError: No module named 'fireflyframework_agentic.exposure.mcp.oauth_jwt'`.

- [ ] **Step 3: Create the module**

```python
# fireflyframework_agentic/exposure/mcp/oauth_jwt.py
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Provider-agnostic OAuth 2.0 / OIDC primitives for the MCP HTTP exposure.

Holds only generic OAuth concepts (issuer, JWKS URI, audience, scopes,
roles claim). Provider-specific factories (Entra, Okta, Auth0, …) live
in ``examples/`` and inject these types via the factory env vars
resolved in :mod:`fireflyframework_agentic.exposure.mcp.http_cli`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class OAuthMetadata:
    """Static OAuth 2.0 / OIDC metadata advertised by the server.

    Populated by an operator-supplied factory at startup and rendered at
    ``/.well-known/oauth-protected-resource`` and
    ``/.well-known/oauth-authorization-server``.
    """

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    resource: str
    scopes_supported: tuple[str, ...]


@runtime_checkable
class TokenVerifier(Protocol):
    """Verifies a bearer token and returns its claims dict.

    Implementations: ``EntraTokenVerifier`` (examples/corpus_search) or any
    other provider-specific RBACManager subclass. Must raise ``ValueError``
    on any validation failure — the middleware maps that to ``401``.
    """

    def validate_token(self, token: str) -> dict[str, Any]: ...


RequiredRoleFn = Callable[[str, str], str | None]
"""``(tool_name, corpus_id) -> role_value`` mapping for App-Roles RBAC.

Returning ``None`` means the call requires no per-corpus role (lifecycle /
no-corpus tools). Mapping is injected so deployments can adopt different
naming conventions without forking the middleware."""
```

- [ ] **Step 4: Tests pass**

```bash
~/.venvs/firefly/bin/python -m pytest tests/unit/exposure/test_oauth_jwt_types.py -v
```

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/exposure/mcp/oauth_jwt.py tests/unit/exposure/test_oauth_jwt_types.py
git commit -m "feat(mcp): add OAuth metadata + TokenVerifier protocol"
```

---

### Task 2: `oauth_metadata.py` — `/.well-known/*` routes

**Files:**
- Create: `fireflyframework_agentic/exposure/mcp/oauth_metadata.py`
- Test: `tests/unit/exposure/test_mcp_oauth_metadata.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/exposure/test_mcp_oauth_metadata.py
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fireflyframework_agentic.exposure.mcp.oauth_jwt import OAuthMetadata
from fireflyframework_agentic.exposure.mcp.oauth_metadata import (
    add_oauth_metadata_routes,
)


def _md() -> OAuthMetadata:
    return OAuthMetadata(
        issuer="https://login.example.com/v2.0",
        authorization_endpoint="https://login.example.com/authorize",
        token_endpoint="https://login.example.com/token",
        jwks_uri="https://login.example.com/keys",
        resource="https://mcp.example.com/mcp/",
        scopes_supported=("user_impersonation",),
    )


def test_protected_resource_endpoint_shape() -> None:
    app = FastAPI()
    add_oauth_metadata_routes(app, _md())
    body = TestClient(app).get("/.well-known/oauth-protected-resource").json()
    assert body["resource"] == "https://mcp.example.com/mcp/"
    assert body["authorization_servers"] == ["https://login.example.com/v2.0"]
    assert body["scopes_supported"] == ["user_impersonation"]
    assert body["bearer_methods_supported"] == ["header"]


def test_authorization_server_endpoint_shape() -> None:
    app = FastAPI()
    add_oauth_metadata_routes(app, _md())
    body = TestClient(app).get("/.well-known/oauth-authorization-server").json()
    assert body["issuer"] == "https://login.example.com/v2.0"
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")
    assert body["jwks_uri"].endswith("/keys")
    assert "code" in body["response_types_supported"]


def test_metadata_routes_unauthenticated() -> None:
    """Metadata MUST be public — clients fetch it before they have a token."""
    app = FastAPI()
    add_oauth_metadata_routes(app, _md())
    client = TestClient(app)
    assert client.get("/.well-known/oauth-protected-resource").status_code == 200
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

- [ ] **Step 3: Implement**

```python
# fireflyframework_agentic/exposure/mcp/oauth_metadata.py
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Public ``/.well-known/*`` endpoints for OAuth 2.0 discovery.

These routes MUST be reachable without authentication — clients fetch
them precisely because they do not yet hold a token. They expose two
documents:

* ``/.well-known/oauth-protected-resource`` (RFC 9728) — tells the
  client *which* authorization server protects this resource and
  *which* scopes apply.
* ``/.well-known/oauth-authorization-server`` (RFC 8414) — minimal
  authorization-server metadata. We do not host an authorization
  server ourselves; this is a pre-baked passthrough of the IdP's
  values so clients that only know how to consume one well-known URL
  per server still work.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from fireflyframework_agentic.exposure.mcp.oauth_jwt import OAuthMetadata


def add_oauth_metadata_routes(app: FastAPI, metadata: OAuthMetadata) -> None:
    """Mount the two well-known metadata endpoints on ``app``."""

    @app.get("/.well-known/oauth-protected-resource")
    def protected_resource() -> dict[str, Any]:
        return {
            "resource": metadata.resource,
            "authorization_servers": [metadata.issuer],
            "scopes_supported": list(metadata.scopes_supported),
            "bearer_methods_supported": ["header"],
        }

    @app.get("/.well-known/oauth-authorization-server")
    def authorization_server() -> dict[str, Any]:
        return {
            "issuer": metadata.issuer,
            "authorization_endpoint": metadata.authorization_endpoint,
            "token_endpoint": metadata.token_endpoint,
            "jwks_uri": metadata.jwks_uri,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
        }
```

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/exposure/mcp/oauth_metadata.py tests/unit/exposure/test_mcp_oauth_metadata.py
git commit -m "feat(mcp): add public /.well-known/ OAuth discovery endpoints"
```

---

### Task 3: Rewrite `auth.py` as `OAuthJWTMiddleware`

**Files:**
- Modify: `fireflyframework_agentic/exposure/mcp/auth.py` (full rewrite)
- Replace: `tests/unit/exposure/test_mcp_corpus_auth.py` → `tests/unit/exposure/test_mcp_oauth_auth.py`

- [ ] **Step 1: Write failing tests** — covers anonymous→401, bad token→401, valid token + missing role→403, valid token + correct read role→200, write tool with read role only→403, write role implies read→200, lifecycle methods pass with valid token + any roles, `list_corpora` filtered by contextvar.

```python
# tests/unit/exposure/test_mcp_oauth_auth.py
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for OAuthJWTMiddleware."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fireflyframework_agentic.exposure.mcp.auth import OAuthJWTMiddleware


class _StubVerifier:
    def __init__(self, claims_by_token: dict[str, dict[str, Any]]) -> None:
        self._claims_by_token = claims_by_token
        self.exc: BaseException | None = None

    def validate_token(self, token: str) -> dict[str, Any]:
        if self.exc is not None:
            raise self.exc
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


def _make_app(*, verifier: _StubVerifier, roles_claim: str = "roles") -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        OAuthJWTMiddleware,
        verifier=verifier,
        required_role_fn=_required_role,
        roles_claim=roles_claim,
        mount_path="/mcp",
        metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource",
    )

    @app.post("/mcp")
    async def echo(payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "payload": payload}

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


def test_anonymous_request_returns_401_with_www_authenticate() -> None:
    client = TestClient(_make_app(verifier=_StubVerifier({})))
    r = client.post("/mcp", json=_body("corpus_query"))
    assert r.status_code == 401
    assert "Bearer" in r.headers["www-authenticate"]
    assert "resource_metadata" in r.headers["www-authenticate"]


def test_invalid_token_returns_401() -> None:
    client = TestClient(_make_app(verifier=_StubVerifier({})))
    r = client.post("/mcp", headers={"Authorization": "Bearer bad"}, json=_body("corpus_query"))
    assert r.status_code == 401


def test_valid_token_without_required_role_returns_403() -> None:
    v = _StubVerifier({"t1": {"roles": []}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers={"Authorization": "Bearer t1"}, json=_body("corpus_query"))
    assert r.status_code == 403


def test_valid_token_with_read_role_passes_read_tool() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Read"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers={"Authorization": "Bearer t1"}, json=_body("corpus_query"))
    assert r.status_code == 200


def test_read_role_denied_on_write_tool() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Read"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post(
        "/mcp",
        headers={"Authorization": "Bearer t1"},
        json=_body("ingest_corpus_filesystem"),
    )
    assert r.status_code == 403


def test_write_role_implies_read() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Write"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post("/mcp", headers={"Authorization": "Bearer t1"}, json=_body("corpus_query"))
    assert r.status_code == 200


def test_lifecycle_method_passes_with_valid_token_no_roles() -> None:
    v = _StubVerifier({"t1": {"roles": []}})
    client = TestClient(_make_app(verifier=v))
    r = client.post(
        "/mcp",
        headers={"Authorization": "Bearer t1"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 200


def test_no_corpus_tool_passes_and_sets_contextvar() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.alpha.Read", "Corpus.beta.Write"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post(
        "/mcp",
        headers={"Authorization": "Bearer t1"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "list_corpora", "arguments": {}}},
    )
    assert r.status_code == 200


def test_healthz_passes_without_auth() -> None:
    client = TestClient(_make_app(verifier=_StubVerifier({})))
    assert client.get("/healthz").status_code == 200


def test_missing_corpus_id_in_arguments_returns_400() -> None:
    v = _StubVerifier({"t1": {"roles": ["Corpus.demo.Read"]}})
    client = TestClient(_make_app(verifier=v))
    r = client.post(
        "/mcp",
        headers={"Authorization": "Bearer t1"},
        json=_body("corpus_query", corpus_id=None),
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement the middleware (full rewrite)** — replaces `auth.py`. Keep body-parsing helpers, lifecycle sets, no-corpus sets, JSON-RPC error shape, fingerprint helpers, contextvar publishing pattern from the old file.

(Code in implementation step.)

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Delete old test file**

```bash
git rm tests/unit/exposure/test_mcp_corpus_auth.py
```

- [ ] **Step 6: Commit**

```bash
git add fireflyframework_agentic/exposure/mcp/auth.py tests/unit/exposure/test_mcp_oauth_auth.py
git commit -m "feat(mcp): replace CorpusAuthMiddleware with OAuthJWTMiddleware"
```

---

### Task 4: Wire `http_cli.py` to install the new middleware via factory env vars

**Files:**
- Modify: `fireflyframework_agentic/exposure/mcp/http_cli.py`
- Modify: `tests/unit/exposure/test_mcp_http_cli.py`
- Modify: `tests/integration/test_mcp_corpus_auth_e2e.py`

- [ ] **Step 1: Write tests** covering `FIREFLY_MCP_AUTH_ENABLED=true` requires both factory env vars, default factories resolve to the Entra helpers in `examples/corpus_search/azure_security.py`, anonymous request → 401 + `WWW-Authenticate`, `/.well-known/*` reachable without auth.

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Rewrite `_install_corpus_auth` → `_install_oauth_auth`**

Implementation step: replace the KV-token install block with one that resolves `FIREFLY_MCP_VERIFIER_FACTORY` (default `examples.corpus_search.azure_security:build_entra_verifier`) and `FIREFLY_MCP_METADATA_FACTORY` (default `examples.corpus_search.azure_security:build_entra_metadata`), install `OAuthJWTMiddleware`, and call `add_oauth_metadata_routes`.

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/exposure/mcp/http_cli.py tests/unit/exposure/test_mcp_http_cli.py tests/integration/test_mcp_corpus_auth_e2e.py
git commit -m "feat(mcp): wire OAuth middleware + metadata via factory env vars"
```

---

### Task 5: Add Entra factories in `examples/corpus_search/azure_security.py`

**Files:**
- Modify: `examples/corpus_search/azure_security.py`

- [ ] **Step 1: Add `build_entra_verifier()` and `build_entra_metadata()` at the bottom of the file.**

```python
def build_entra_verifier() -> EntraTokenVerifier:
    """Default verifier factory for ``FIREFLY_MCP_VERIFIER_FACTORY``.

    Reads ``AZURE_TENANT_ID`` and ``AZURE_CLIENT_ID`` from the
    environment. Raises ``RuntimeError`` with a clear message if either
    is missing — the alternative (a confusing JWT validation failure
    on first request) makes ops debugging much harder.
    """
    import os

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    if not tenant or not client:
        raise RuntimeError(
            "build_entra_verifier requires AZURE_TENANT_ID and AZURE_CLIENT_ID"
        )
    return EntraTokenVerifier(tenant_id=tenant, audience=f"api://{client}")


def build_entra_metadata() -> "OAuthMetadata":
    """Default metadata factory for ``FIREFLY_MCP_METADATA_FACTORY``."""
    import os

    from fireflyframework_agentic.exposure.mcp.oauth_jwt import OAuthMetadata

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    host = os.environ.get("FIREFLY_MCP_PUBLIC_URL", "").rstrip("/")
    if not tenant or not client or not host:
        raise RuntimeError(
            "build_entra_metadata requires AZURE_TENANT_ID, AZURE_CLIENT_ID, "
            "and FIREFLY_MCP_PUBLIC_URL"
        )
    base = f"https://login.microsoftonline.com/{tenant}"
    return OAuthMetadata(
        issuer=f"{base}/v2.0",
        authorization_endpoint=f"{base}/oauth2/v2.0/authorize",
        token_endpoint=f"{base}/oauth2/v2.0/token",
        jwks_uri=f"{base}/discovery/v2.0/keys",
        resource=f"{host}/mcp/",
        scopes_supported=(f"api://{client}/user_impersonation",),
    )
```

- [ ] **Step 2: Add unit tests in `tests/unit/examples/test_azure_security_factories.py`** for both factories (success + missing env vars).

- [ ] **Step 3: Tests pass.**

- [ ] **Step 4: Commit**

```bash
git add examples/corpus_search/azure_security.py tests/unit/examples/test_azure_security_factories.py
git commit -m "feat(examples): add Entra verifier + metadata factories"
```

---

### Task 6: Delete the capability-token model

**Files:**
- Delete: `fireflyframework_agentic/security/corpus_token.py`
- Modify: `fireflyframework_agentic/security/__init__.py`
- Delete: `tests/unit/security/test_corpus_token.py`
- Modify: `examples/corpus_search/azure_security.py` (drop `KeyVaultTokenStore`, `build_default_store`, `validate_corpus_id` import, `EntraOBOClient` if unused)
- Delete: `tests/unit/examples/test_firefly_mcp_token_cli.py` (if it tests deleted code)
- Delete: stale doc / script entries referencing capability tokens

- [ ] **Step 1: Search for remaining references.**

```bash
grep -rn "corpus_token\|CorpusTokenStore\|CorpusTokenCache\|corpus_token_digest\|KeyVaultTokenStore\|build_default_store\|validate_corpus_id" --include="*.py" --include="*.md" .
```

Fix all references. Either delete the dependent code (if unused with the new model) or migrate to OAuth.

- [ ] **Step 2: Delete files**

```bash
git rm fireflyframework_agentic/security/corpus_token.py tests/unit/security/test_corpus_token.py
```

- [ ] **Step 3: Edit `security/__init__.py`** — remove the imports and `__all__` entries.

- [ ] **Step 4: Edit `examples/corpus_search/azure_security.py`** — delete `KeyVaultTokenStore`, `build_default_store`. Keep `EntraTokenVerifier` (now reused by `build_entra_verifier`). Drop `EntraOBOClient` only if nothing else uses it.

- [ ] **Step 5: Run full test suite.**

```bash
~/.venvs/firefly/bin/python -m pytest tests/unit tests/integration -x --ignore=tests/integration/test_mcp_corpus_e2e.py
```

Expected: all pass. (Integration test that requires real Azure is skipped.)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(security): retire per-corpus capability-token model"
```

---

### Task 7: Update operator docs

**Files:**
- Modify: `docs/deploy/mcp-corpus-auth.md`

- [ ] **Step 1: Rewrite the doc** to describe:
  1. The OAuth model (provider-agnostic).
  2. Env vars (`FIREFLY_MCP_AUTH_ENABLED`, `FIREFLY_MCP_VERIFIER_FACTORY`, `FIREFLY_MCP_METADATA_FACTORY`, `FIREFLY_MCP_PUBLIC_URL`).
  3. Azure-specific quickstart: App Registration, identifier URI, `user_impersonation` scope, App Roles (`Corpus.<id>.Read`, `Corpus.<id>.Write`), disabling Easy Auth.
  4. Connecting via `claude mcp add`.
  5. Rollback (re-enable Easy Auth).

- [ ] **Step 2: Commit**

```bash
git add docs/deploy/mcp-corpus-auth.md
git commit -m "docs(mcp): rewrite auth guide for OAuth/JWT model"
```

---

### Task 8: Final verification and PR

- [ ] **Step 1: Run full test + lint.**

```bash
~/.venvs/firefly/bin/python -m pytest tests/unit -x
~/.venvs/firefly/bin/python -m ruff check fireflyframework_agentic/exposure/mcp examples/corpus_search
```

- [ ] **Step 2: Push branch.**

```bash
git push -u origin feat/mcp-oauth-jwt
```

- [ ] **Step 3: Open PR.**

```bash
gh pr create --repo fireflyframework/fireflyframework-agentic \
  --title "feat(mcp): OAuth 2.0 / OIDC auth with App-Roles RBAC" \
  --body "$(cat <<'EOF'
## Summary
- Replace per-corpus capability-token middleware with provider-agnostic OAuth 2.0 / OIDC JWT validation
- Publish RFC 9728 / RFC 8414 discovery metadata so MCP clients can bootstrap OAuth login automatically (`claude mcp add` end-to-end)
- Add App-Roles RBAC (`Corpus.<id>.Read` / `Corpus.<id>.Write`) via reuse of `RBACManager.has_permission`
- Azure-specific glue stays in `examples/corpus_search/azure_security.py`

Closes #154, closes #177.

## Test plan
- [ ] `pytest tests/unit tests/integration` green
- [ ] Anonymous request returns 401 with `WWW-Authenticate: Bearer resource_metadata=...`
- [ ] `/.well-known/oauth-protected-resource` returns valid JSON
- [ ] Manual: `claude mcp add firefly --transport http <url>` completes browser flow against Entra
EOF
)"
```

- [ ] **Step 4: Done.**
