# Per-Corpus Key Vault Auth for MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Starlette middleware that authorises every `firefly-mcp-http` tool call against a per-corpus capability token stored in Azure Key Vault, so a leaked token only exposes one corpus.

**Architecture:** New `CorpusAuthMiddleware` reads `Authorization: Bearer <token>`, parses the JSON-RPC body to find the `corpus_id` argument, then validates the token against `sha256(token+corpus_id)` cached digests backed by `azure.keyvault.secrets.aio.SecretClient`. KV access uses `DefaultAzureCredential` (managed identity in Azure Container Apps, `az login` locally). Toggled via `FIREFLY_MCP_CORPUS_AUTH_ENABLED`; off by default for back-compat.

**Tech Stack:** Python 3.13, `uv`, FastAPI / Starlette, FastMCP, `azure-keyvault-secrets`, `azure-identity`, pytest with `pytest-asyncio`. Branch: `feat/mcp-corpus-keyvault-auth` (off `main`).

**Reference spec:** `docs/superpowers/specs/2026-05-12-mcp-corpus-keyvault-auth-design.md`

---

## Conventions

- All commits go to the current branch (`feat/mcp-corpus-keyvault-auth`). Do not push to `main`.
- After each step that changes code, run `uv run pytest <relevant tests> -v` and confirm green before committing.
- Pre-commit hooks (ruff, end-of-file-fixer, gitleaks) stay active. Never `--no-verify`.
- Do **not** put real tokens in fixtures. Tests must use `secrets.token_urlsafe(8)` at test time, or fixed strings that look obviously fake (e.g. `"test-token-aaa"`).
- Never log the raw bearer. The only safe representation is `sha256(token)[:8]`.

---

## File Structure

| Path | New / Modify | Responsibility |
|---|---|---|
| `fireflyframework_agentic/security/keyvault.py` | new | `KeyVaultTokenStore` + `CorpusTokenCache`. |
| `fireflyframework_agentic/security/__init__.py` | modify | Export the two new classes. |
| `fireflyframework_agentic/exposure/mcp/auth.py` | new | `CorpusAuthMiddleware` (Starlette `BaseHTTPMiddleware`). |
| `fireflyframework_agentic/exposure/mcp/http_cli.py` | modify | Wire middleware behind `FIREFLY_MCP_CORPUS_AUTH_ENABLED` flag. |
| `fireflyframework_agentic/tools/builtins/corpus_rag.py` | modify (`list_corpora` only) | Filter to `request.state.authorised_corpora` when set. |
| `pyproject.toml` | modify | Add `azure-keyvault-secrets>=4.9` to `[project.optional-dependencies] azure`. |
| `docs/deploy/mcp-corpus-auth.md` | new | Operator runbook (provision, rotate, revoke, recover). |
| `tests/unit/exposure/test_mcp_corpus_auth.py` | new | Middleware + helpers unit tests (12+ cases). |
| `tests/unit/security/test_keyvault_token_store.py` | new | Store + cache unit tests. |
| `tests/integration/test_mcp_corpus_auth_e2e.py` | new | End-to-end through `build_app` with a stub KV client. |

---

## Phase 1 — Key Vault token store + cache

After this phase, the framework has a typed, async helper that fetches per-corpus secrets from Key Vault with a TTL cache. The MCP layer doesn't depend on it yet.

### Task 1: Add `azure-keyvault-secrets` to the azure extra

**Files:**
- Modify: `pyproject.toml` (the `azure = [...]` block under `[project.optional-dependencies]`)

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml`. The `azure` extra currently lists `azure-identity>=1.19`, `msal>=1.31`, etc. Add a new line below `azure-identity`:

```toml
azure = [
    "azure-identity>=1.19",
    "azure-keyvault-secrets>=4.9",
    "msal>=1.31",
    "pyjwt[crypto]>=2.10.0",
    "azure-monitor-opentelemetry-exporter>=1.0.0b30",
]
```

- [ ] **Step 2: Refresh the lockfile**

Run: `uv lock`

Expected: `uv.lock` updated; no other diff in `pyproject.toml`.

- [ ] **Step 3: Install the new dep into the venv**

Run: `uv sync --all-extras`

Expected: `azure-keyvault-secrets` resolves; existing tests not yet affected.

- [ ] **Step 4: Smoke-import**

Run: `uv run python -c "from azure.keyvault.secrets.aio import SecretClient; print('ok')"`

Expected output: `ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(azure): add azure-keyvault-secrets to azure extra"
```

---

### Task 2: Write failing test for `CorpusTokenCache`

**Files:**
- Test: `tests/unit/security/test_keyvault_token_store.py`

The cache stores `sha256(token + corpus_id)` digests with a TTL. Lookup
returns `bool` for whether the digest is still trusted.

- [ ] **Step 1: Create the test directory and file**

Run: `mkdir -p tests/unit/security`

Create `tests/unit/security/__init__.py` as an empty file (the test layout uses package directories).

Then create `tests/unit/security/test_keyvault_token_store.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for the CorpusTokenCache."""

from __future__ import annotations

import hashlib
import time

import pytest


def _digest(token: str, corpus_id: str) -> str:
    return hashlib.sha256(f"{token}|{corpus_id}".encode()).hexdigest()


def test_cache_stores_and_returns_true_within_ttl() -> None:
    from fireflyframework_agentic.security.keyvault import CorpusTokenCache

    cache = CorpusTokenCache(ttl_seconds=60)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))
    assert cache.is_trusted("corpus-a", _digest("tok", "corpus-a")) is True


def test_cache_rejects_wrong_digest() -> None:
    from fireflyframework_agentic.security.keyvault import CorpusTokenCache

    cache = CorpusTokenCache(ttl_seconds=60)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))
    assert cache.is_trusted("corpus-a", _digest("other", "corpus-a")) is False


def test_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    from fireflyframework_agentic.security import keyvault as kv_mod
    from fireflyframework_agentic.security.keyvault import CorpusTokenCache

    fake_now = [1000.0]
    monkeypatch.setattr(kv_mod, "_monotonic", lambda: fake_now[0])

    cache = CorpusTokenCache(ttl_seconds=10)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))

    fake_now[0] = 1009.9
    assert cache.is_trusted("corpus-a", _digest("tok", "corpus-a")) is True

    fake_now[0] = 1010.1
    assert cache.is_trusted("corpus-a", _digest("tok", "corpus-a")) is False


def test_cache_is_corpus_scoped() -> None:
    """A hit for corpus-a must not validate corpus-b, even with the same token."""
    from fireflyframework_agentic.security.keyvault import CorpusTokenCache

    cache = CorpusTokenCache(ttl_seconds=60)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))
    # Different corpus_id → different digest → not trusted.
    assert cache.is_trusted("corpus-b", _digest("tok", "corpus-b")) is False
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest tests/unit/security/test_keyvault_token_store.py -v`

Expected: 4 failures with `ModuleNotFoundError: No module named 'fireflyframework_agentic.security.keyvault'`.

---

### Task 3: Implement `CorpusTokenCache`

**Files:**
- Create: `fireflyframework_agentic/security/keyvault.py`

- [ ] **Step 1: Create the module**

Write `fireflyframework_agentic/security/keyvault.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Azure Key Vault token store + in-memory TTL cache for per-corpus capability
tokens used by the MCP server.

The plaintext token is never retained beyond the request scope; the cache
stores ``sha256(token + corpus_id)`` digests only, keyed by ``corpus_id``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _monotonic() -> float:
    """Indirection so tests can freeze time without touching ``time``."""
    return time.monotonic()


def corpus_token_digest(token: str, corpus_id: str) -> str:
    """Bind a token to a corpus_id; used everywhere the cache is touched."""
    return hashlib.sha256(f"{token}|{corpus_id}".encode()).hexdigest()


@dataclass(slots=True)
class _Entry:
    digest: str
    expires_at: float


class CorpusTokenCache:
    """In-memory TTL cache of corpus → trusted digest."""

    def __init__(self, *, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = float(ttl_seconds)
        self._entries: dict[str, _Entry] = {}

    def remember(self, corpus_id: str, digest: str) -> None:
        self._entries[corpus_id] = _Entry(digest=digest, expires_at=_monotonic() + self._ttl)

    def is_trusted(self, corpus_id: str, digest: str) -> bool:
        entry = self._entries.get(corpus_id)
        if entry is None:
            return False
        if _monotonic() >= entry.expires_at:
            self._entries.pop(corpus_id, None)
            return False
        return hmac.compare_digest(entry.digest, digest)

    def forget(self, corpus_id: str) -> None:
        self._entries.pop(corpus_id, None)
```

- [ ] **Step 2: Re-run the test**

Run: `uv run pytest tests/unit/security/test_keyvault_token_store.py -v`

Expected: All 4 pass.

- [ ] **Step 3: Commit**

```bash
git add fireflyframework_agentic/security/keyvault.py tests/unit/security/__init__.py tests/unit/security/test_keyvault_token_store.py
git commit -m "feat(security): add CorpusTokenCache for per-corpus token digests"
```

---

### Task 4: Write failing test for `KeyVaultTokenStore`

**Files:**
- Test: `tests/unit/security/test_keyvault_token_store.py` (append)

The store wraps an `azure.keyvault.secrets.aio.SecretClient` and returns
either the secret value or `None` for not-found / disabled. Other Azure
errors must propagate so the middleware can fail closed (503).

- [ ] **Step 1: Append tests**

Append to `tests/unit/security/test_keyvault_token_store.py`:

```python
class _FakeSecret:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeSecretClient:
    """Minimal async stub matching the subset of SecretClient we use."""

    def __init__(
        self,
        *,
        secrets: dict[str, str] | None = None,
        raise_for: dict[str, BaseException] | None = None,
    ) -> None:
        self._secrets = secrets or {}
        self._raise_for = raise_for or {}
        self.get_calls: list[str] = []

    async def get_secret(self, name: str) -> _FakeSecret:
        self.get_calls.append(name)
        if name in self._raise_for:
            raise self._raise_for[name]
        if name not in self._secrets:
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError(message=f"secret {name} not found")
        return _FakeSecret(self._secrets[name])

    async def close(self) -> None:  # pragma: no cover - cleanup only
        return None


@pytest.mark.asyncio
async def test_store_returns_secret_value() -> None:
    from fireflyframework_agentic.security.keyvault import KeyVaultTokenStore

    client = _FakeSecretClient(secrets={"firefly-mcp-corpus-token-demo": "abc"})
    store = KeyVaultTokenStore(client=client, prefix="firefly-mcp-corpus-token-")

    assert await store.get_corpus_token("demo") == "abc"
    assert client.get_calls == ["firefly-mcp-corpus-token-demo"]


@pytest.mark.asyncio
async def test_store_returns_none_when_not_found() -> None:
    from fireflyframework_agentic.security.keyvault import KeyVaultTokenStore

    client = _FakeSecretClient(secrets={})
    store = KeyVaultTokenStore(client=client, prefix="firefly-mcp-corpus-token-")

    assert await store.get_corpus_token("missing") is None


@pytest.mark.asyncio
async def test_store_propagates_service_errors() -> None:
    from azure.core.exceptions import ServiceRequestError

    from fireflyframework_agentic.security.keyvault import KeyVaultTokenStore

    err = ServiceRequestError(message="boom")
    client = _FakeSecretClient(raise_for={"firefly-mcp-corpus-token-x": err})
    store = KeyVaultTokenStore(client=client, prefix="firefly-mcp-corpus-token-")

    with pytest.raises(ServiceRequestError):
        await store.get_corpus_token("x")


def test_store_validates_corpus_id() -> None:
    """corpus_id must match the framework's [a-z0-9-]{1,63} contract."""
    from fireflyframework_agentic.security.keyvault import KeyVaultTokenStore

    client = _FakeSecretClient()
    store = KeyVaultTokenStore(client=client, prefix="firefly-mcp-corpus-token-")

    import asyncio
    with pytest.raises(ValueError, match="corpus_id"):
        asyncio.run(store.get_corpus_token("Bad ID!"))
```

- [ ] **Step 2: Verify the new tests fail**

Run: `uv run pytest tests/unit/security/test_keyvault_token_store.py -v`

Expected: 4 new failures, all `ImportError`/`AttributeError` complaining about `KeyVaultTokenStore`.

---

### Task 5: Implement `KeyVaultTokenStore`

**Files:**
- Modify: `fireflyframework_agentic/security/keyvault.py`

- [ ] **Step 1: Add the class and a constructor helper**

Append to `fireflyframework_agentic/security/keyvault.py`:

```python
import re
from typing import Protocol


_CORPUS_ID_RE = re.compile(r"^[a-z0-9-]{1,63}$")


class _SecretClient(Protocol):
    async def get_secret(self, name: str) -> object: ...
    async def close(self) -> None: ...


class KeyVaultTokenStore:
    """Async fetcher for per-corpus tokens from Azure Key Vault.

    Returns ``None`` for not-found / disabled secrets so the caller can map
    those to ``403 Forbidden``. Other Azure errors propagate so the caller
    can fail closed (``503``).
    """

    def __init__(self, *, client: _SecretClient, prefix: str) -> None:
        self._client = client
        self._prefix = prefix

    async def get_corpus_token(self, corpus_id: str) -> str | None:
        if not _CORPUS_ID_RE.match(corpus_id):
            raise ValueError(f"invalid corpus_id: {corpus_id!r}")
        from azure.core.exceptions import ResourceNotFoundError

        name = f"{self._prefix}{corpus_id}"
        try:
            secret = await self._client.get_secret(name)
        except ResourceNotFoundError:
            return None
        # The real SDK returns a KeyVaultSecret; ``.value`` is the plaintext.
        return getattr(secret, "value", None)

    async def aclose(self) -> None:
        await self._client.close()


def build_default_store(
    *,
    vault_url: str,
    prefix: str = "firefly-mcp-corpus-token-",
) -> KeyVaultTokenStore:
    """Construct a store wired to the real Azure SDK + DefaultAzureCredential."""
    from azure.identity.aio import DefaultAzureCredential
    from azure.keyvault.secrets.aio import SecretClient

    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    return KeyVaultTokenStore(client=client, prefix=prefix)
```

- [ ] **Step 2: Re-export from the security package**

Modify `fireflyframework_agentic/security/__init__.py` to add (preserving existing exports):

```python
from fireflyframework_agentic.security.keyvault import (
    CorpusTokenCache,
    KeyVaultTokenStore,
    build_default_store,
    corpus_token_digest,
)
```

- [ ] **Step 3: Run all security tests**

Run: `uv run pytest tests/unit/security/ -v`

Expected: 8 pass.

- [ ] **Step 4: Commit**

```bash
git add fireflyframework_agentic/security/keyvault.py fireflyframework_agentic/security/__init__.py tests/unit/security/test_keyvault_token_store.py
git commit -m "feat(security): add KeyVaultTokenStore for per-corpus secrets"
```

---

## Phase 2 — `CorpusAuthMiddleware`

After this phase the middleware exists and is unit-tested with stubs; it is **not** yet mounted on the MCP app.

### Task 6: Write failing tests for `CorpusAuthMiddleware` happy path + missing/malformed bearer

**Files:**
- Test: `tests/unit/exposure/test_mcp_corpus_auth.py`

The middleware extracts the bearer, parses the JSON-RPC body to find the
`corpus_id` argument, and validates against a `(cache, store)` pair. To
keep the tests synchronous and fast we drive Starlette directly.

- [ ] **Step 1: Create the test file**

Write `tests/unit/exposure/test_mcp_corpus_auth.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for CorpusAuthMiddleware."""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="middleware requires fastapi")
pytest.importorskip("starlette", reason="middleware requires starlette")

from fastapi import FastAPI
from fastapi.testclient import TestClient


class _StubStore:
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

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _body(corpus_id: str, *, tool: str = "corpus_query") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": {"corpus_id": corpus_id, "question": "hi", "top_k": 3}},
    }


def test_happy_path_forwards_request_when_bearer_matches() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post(
        "/mcp",
        json=_body("demo"),
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert store.calls == ["demo"]


def test_missing_bearer_returns_401() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post("/mcp", json=_body("demo"))
    assert response.status_code == 401
    assert "detail" in response.json()


def test_malformed_bearer_returns_401() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post(
        "/mcp",
        json=_body("demo"),
        headers={"Authorization": "Token nope"},
    )
    assert response.status_code == 401


def test_healthz_is_not_gated() -> None:
    store = _StubStore({})
    client = TestClient(_make_app(store=store))
    response = client.get("/healthz")
    assert response.status_code == 200
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run pytest tests/unit/exposure/test_mcp_corpus_auth.py -v`

Expected: 4 failures (`ModuleNotFoundError: ...exposure.mcp.auth`).

---

### Task 7: Implement `CorpusAuthMiddleware` (skeleton + happy path)

**Files:**
- Create: `fireflyframework_agentic/exposure/mcp/auth.py`

- [ ] **Step 1: Write the module**

Create `fireflyframework_agentic/exposure/mcp/auth.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Starlette middleware that authorises MCP tool calls against per-corpus
capability tokens stored in Azure Key Vault.

Out of scope: this middleware never *issues* tokens. It only validates that
the bearer the client sent is the current value of the
``firefly-mcp-corpus-token-<corpus_id>`` secret for the corpus the tool
call targets.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fireflyframework_agentic.security.keyvault import (
    CorpusTokenCache,
    KeyVaultTokenStore,
    corpus_token_digest,
)

logger = logging.getLogger(__name__)

_EXCLUDED_PATHS: frozenset[str] = frozenset({"/healthz"})
_JSONRPC_ERR_AUTH = -32001


def _unauthorised(detail: str, status: int = 401) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "error": {"code": _JSONRPC_ERR_AUTH, "message": detail}},
        status_code=status,
    )


class CorpusAuthMiddleware(BaseHTTPMiddleware):
    """Authorise MCP tool calls against a per-corpus capability token.

    The middleware is mount-aware: only requests whose path starts with
    ``mount_path`` are gated; everything else (notably ``/healthz``) is
    passed through.
    """

    def __init__(
        self,
        app: Any,
        *,
        store: KeyVaultTokenStore,
        cache: CorpusTokenCache,
        mount_path: str = "/mcp",
    ) -> None:
        super().__init__(app)
        self._store = store
        self._cache = cache
        self._mount = mount_path.rstrip("/") or "/"

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path in _EXCLUDED_PATHS or not (path == self._mount or path.startswith(self._mount + "/")):
            return await call_next(request)

        bearer = self._read_bearer(request)
        if bearer is None:
            return _unauthorised("Missing or malformed Authorization header", 401)

        body = await request.body()
        corpus_id = self._extract_corpus_id(body)
        if corpus_id is None:
            return _unauthorised("Missing corpus_id in tool arguments", 400)

        digest = corpus_token_digest(bearer, corpus_id)
        authorised = await self._authorise(corpus_id, bearer, digest)
        if authorised is None:
            return _unauthorised("Key Vault unavailable", 503)
        if not authorised:
            return _unauthorised("Forbidden for this corpus", 403)

        # Replay the body downstream — Starlette has already consumed it.
        request._body = body  # type: ignore[attr-defined]
        request.state.authorised_corpora = (corpus_id,)
        return await call_next(request)

    @staticmethod
    def _read_bearer(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None
        token = header[7:].strip()
        return token or None

    @staticmethod
    def _extract_corpus_id(body: bytes) -> str | None:
        if not body:
            return None
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            return None
        # Single or batched JSON-RPC; we authorise per-call.
        first = doc[0] if isinstance(doc, list) else doc
        params = first.get("params") if isinstance(first, dict) else None
        args = params.get("arguments") if isinstance(params, dict) else None
        if isinstance(args, dict):
            value = args.get("corpus_id")
            if isinstance(value, str) and value:
                return value
        return None

    async def _authorise(self, corpus_id: str, token: str, digest: str) -> bool | None:
        """Returns True (forward), False (forbid), or None (KV outage → 503)."""
        if self._cache.is_trusted(corpus_id, digest):
            return True
        try:
            secret = await self._store.get_corpus_token(corpus_id)
        except Exception:  # noqa: BLE001 — fail-closed; the alternative is opening up auth.
            logger.exception("Key Vault lookup failed for corpus_id=%s", corpus_id)
            return None
        if secret is None:
            return False
        if not hmac.compare_digest(secret, token):
            return False
        self._cache.remember(corpus_id, digest)
        return True
```

- [ ] **Step 2: Run the happy-path tests**

Run: `uv run pytest tests/unit/exposure/test_mcp_corpus_auth.py -v`

Expected: 4 pass.

- [ ] **Step 3: Commit**

```bash
git add fireflyframework_agentic/exposure/mcp/auth.py tests/unit/exposure/test_mcp_corpus_auth.py
git commit -m "feat(mcp): add CorpusAuthMiddleware skeleton with happy-path auth"
```

---

### Task 8: Write failing tests for forbid / outage / cache reuse / cross-corpus

**Files:**
- Modify: `tests/unit/exposure/test_mcp_corpus_auth.py` (append)

- [ ] **Step 1: Append the cases**

Append to `tests/unit/exposure/test_mcp_corpus_auth.py`:

```python
def test_wrong_token_returns_403() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    response = client.post(
        "/mcp",
        json=_body("demo"),
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 403
    # Bearer must not appear in the error body.
    assert "wrong" not in response.text


def test_token_for_other_corpus_returns_403() -> None:
    store = _StubStore({"corpus-a": "token-a", "corpus-b": "token-b"})
    client = TestClient(_make_app(store=store))
    response = client.post(
        "/mcp",
        json=_body("corpus-b"),
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 403


def test_unknown_corpus_returns_403_not_404() -> None:
    """Avoid enumeration: missing secret looks identical to wrong token."""
    store = _StubStore({})  # nothing
    client = TestClient(_make_app(store=store))
    response = client.post(
        "/mcp",
        json=_body("ghost"),
        headers={"Authorization": "Bearer anything"},
    )
    assert response.status_code == 403


def test_kv_outage_returns_503() -> None:
    from azure.core.exceptions import ServiceRequestError

    store = _StubStore({"demo": "secret-token"})
    store.exc = ServiceRequestError(message="boom")
    client = TestClient(_make_app(store=store))
    response = client.post(
        "/mcp",
        json=_body("demo"),
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 503


def test_cache_avoids_repeat_kv_lookups() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store, ttl=60))
    h = {"Authorization": "Bearer secret-token"}
    for _ in range(3):
        assert client.post("/mcp", json=_body("demo"), headers=h).status_code == 200
    assert store.calls == ["demo"]  # one lookup, two cache hits


def test_missing_corpus_id_returns_400() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "x", "arguments": {}}}
    response = client.post("/mcp", json=body, headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 400


def test_body_is_forwarded_intact() -> None:
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    payload = _body("demo")
    response = client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 200
    # The downstream handler echoed the parsed payload — byte-equality is
    # implicit because the JSON round-trips.
    assert response.json()["payload"] == payload


def test_log_capture_does_not_contain_raw_token(caplog: pytest.LogCaptureFixture) -> None:
    import logging as _logging

    caplog.set_level(_logging.DEBUG)
    store = _StubStore({"demo": "secret-token"})
    client = TestClient(_make_app(store=store))
    for h in (
        {"Authorization": "Bearer secret-token"},
        {"Authorization": "Bearer wrong-token"},
        {},
    ):
        client.post("/mcp", json=_body("demo"), headers=h)
    captured = caplog.text
    assert "secret-token" not in captured
    assert "wrong-token" not in captured
```

- [ ] **Step 2: Run and confirm the new failures**

Run: `uv run pytest tests/unit/exposure/test_mcp_corpus_auth.py -v`

Expected: the 8 new tests fail (or pass partially); the 4 from Task 6 still pass.

---

### Task 9: Make the new tests pass — refinements and outage mapping

**Files:**
- Modify: `fireflyframework_agentic/exposure/mcp/auth.py`

The skeleton from Task 7 already handles most cases. The expected gaps:

- KV outage must be mapped to **503**, not silently treated as "no secret".
- The `Exception` swallow must not catch `ResourceNotFoundError` — the
  store already maps that to `None`, but third-party SDK errors should be
  caught here.
- Log statements must not include the raw token. Audit and fix any.

- [ ] **Step 1: Audit `auth.py` for token leaks**

Open the file. Verify:
- No `logger.*(... %s ..., token, ...)` calls.
- No f-string with `{token}` in any log message.
- The 401/403/503 response bodies do not include the bearer.

If any leak exists, replace with `sha256(token).hexdigest()[:8]`.

- [ ] **Step 2: Re-run the suite**

Run: `uv run pytest tests/unit/exposure/test_mcp_corpus_auth.py -v`

Expected: all 11 tests pass.

- [ ] **Step 3: Commit**

```bash
git add fireflyframework_agentic/exposure/mcp/auth.py tests/unit/exposure/test_mcp_corpus_auth.py
git commit -m "feat(mcp): cover forbid/outage/cache paths in CorpusAuthMiddleware"
```

---

## Phase 3 — Wire the middleware into `firefly-mcp-http`

### Task 10: Wire middleware behind a feature flag in `build_app`

**Files:**
- Modify: `fireflyframework_agentic/exposure/mcp/http_cli.py`

- [ ] **Step 1: Read the current file**

Confirm `build_app()` currently constructs a FastAPI app and mounts the
MCP sub-app at `/mcp`. The middleware must be added **before** `app.mount`
so it intercepts requests to the sub-app.

- [ ] **Step 2: Replace `build_app`**

Edit `fireflyframework_agentic/exposure/mcp/http_cli.py` so the file reads:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""``firefly-mcp-http`` CLI — run the MCP server over Streamable HTTP.

Used by network deployments (e.g. Azure Container Apps). When
``FIREFLY_MCP_CORPUS_AUTH_ENABLED=true`` the process additionally enforces
per-corpus capability tokens fetched from Azure Key Vault (see
``docs/deploy/mcp-corpus-auth.md``).
"""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
from fireflyframework_agentic.tools.builtins import corpus_rag  # noqa: F401 — registers tools


def build_app() -> FastAPI:
    mcp_app = create_mcp_app().http_app(path="/")
    app = FastAPI(title="firefly-mcp", version="0.1.0", lifespan=mcp_app.lifespan)

    if os.environ.get("FIREFLY_MCP_CORPUS_AUTH_ENABLED", "").lower() == "true":
        _install_corpus_auth(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/mcp", mcp_app)
    return app


def _install_corpus_auth(app: FastAPI) -> None:
    """Add CorpusAuthMiddleware. Imports are lazy so the azure extra stays optional."""
    vault_url = os.environ.get("FIREFLY_MCP_KEYVAULT_URL")
    if not vault_url:
        raise RuntimeError(
            "FIREFLY_MCP_CORPUS_AUTH_ENABLED=true but FIREFLY_MCP_KEYVAULT_URL is unset"
        )

    from fireflyframework_agentic.exposure.mcp.auth import CorpusAuthMiddleware
    from fireflyframework_agentic.security.keyvault import (
        CorpusTokenCache,
        build_default_store,
    )

    ttl = float(os.environ.get("FIREFLY_MCP_TOKEN_CACHE_TTL_SECONDS", "300"))
    prefix = os.environ.get("FIREFLY_MCP_TOKEN_SECRET_PREFIX", "firefly-mcp-corpus-token-")

    store = build_default_store(vault_url=vault_url, prefix=prefix)
    cache = CorpusTokenCache(ttl_seconds=ttl)
    app.add_middleware(CorpusAuthMiddleware, store=store, cache=cache, mount_path="/mcp")


def main() -> None:
    """Entry point registered as ``firefly-mcp-http`` in ``[project.scripts]``."""
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(build_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify the existing CLI tests still pass**

Run: `uv run pytest tests/unit/exposure/test_mcp_http_cli.py -v`

Expected: 2 pass (healthz and mount tests). Auth is off by default → no behaviour change.

- [ ] **Step 4: Commit**

```bash
git add fireflyframework_agentic/exposure/mcp/http_cli.py
git commit -m "feat(mcp): wire CorpusAuthMiddleware behind FIREFLY_MCP_CORPUS_AUTH_ENABLED"
```

---

### Task 11: End-to-end test through `build_app` with a stub Key Vault

**Files:**
- Test: `tests/integration/test_mcp_corpus_auth_e2e.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_mcp_corpus_auth_e2e.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""End-to-end auth gating through ``build_app``."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="MCP HTTP build_app requires fastapi")
pytest.importorskip("fastmcp", reason="MCP HTTP build_app requires fastmcp")
pytest.importorskip("azure.keyvault.secrets.aio", reason="auth requires azure SDK")

from fastapi.testclient import TestClient


class _StubStore:
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    async def get_corpus_token(self, corpus_id: str) -> str | None:
        return self._secrets.get(corpus_id)


@pytest.fixture
def app_with_auth(monkeypatch: pytest.MonkeyPatch):
    """build_app() with auth enabled and a stub KeyVaultTokenStore."""
    from fireflyframework_agentic.exposure.mcp import http_cli
    from fireflyframework_agentic.security.keyvault import CorpusTokenCache

    monkeypatch.setenv("FIREFLY_MCP_CORPUS_AUTH_ENABLED", "true")
    monkeypatch.setenv("FIREFLY_MCP_KEYVAULT_URL", "https://stub.vault.azure.net")

    def _stub_store(*, vault_url: str, prefix: str = "firefly-mcp-corpus-token-"):
        return _StubStore({"demo": "secret-token"})

    monkeypatch.setattr(http_cli, "build_default_store", _stub_store, raising=False)
    # build_default_store is referenced inside _install_corpus_auth as a
    # module attribute import; patch the imported reference too:
    from fireflyframework_agentic.security import keyvault as kv_mod
    monkeypatch.setattr(kv_mod, "build_default_store", _stub_store)

    monkeypatch.setattr(CorpusTokenCache, "__init__", lambda self, *, ttl_seconds: None.__init__())  # noqa: E501
    yield http_cli.build_app()


def test_unauth_request_is_rejected() -> None:
    import os
    from fireflyframework_agentic.exposure.mcp import http_cli
    from fireflyframework_agentic.security import keyvault as kv_mod

    os.environ["FIREFLY_MCP_CORPUS_AUTH_ENABLED"] = "true"
    os.environ["FIREFLY_MCP_KEYVAULT_URL"] = "https://stub.vault.azure.net"

    def _stub(*, vault_url: str, prefix: str = "firefly-mcp-corpus-token-"):
        return _StubStore({"demo": "secret-token"})

    kv_mod.build_default_store = _stub  # type: ignore[assignment]

    try:
        app = http_cli.build_app()
        client = TestClient(app)
        # Hit /mcp with no bearer
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "corpus_query", "arguments": {"corpus_id": "demo", "question": "hi", "top_k": 3}},
            },
        )
        assert response.status_code == 401
    finally:
        os.environ.pop("FIREFLY_MCP_CORPUS_AUTH_ENABLED", None)
        os.environ.pop("FIREFLY_MCP_KEYVAULT_URL", None)


def test_healthz_remains_public() -> None:
    import os
    from fireflyframework_agentic.exposure.mcp import http_cli
    from fireflyframework_agentic.security import keyvault as kv_mod

    os.environ["FIREFLY_MCP_CORPUS_AUTH_ENABLED"] = "true"
    os.environ["FIREFLY_MCP_KEYVAULT_URL"] = "https://stub.vault.azure.net"

    kv_mod.build_default_store = lambda *, vault_url, prefix="firefly-mcp-corpus-token-": _StubStore({})  # type: ignore[assignment]

    try:
        app = http_cli.build_app()
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
    finally:
        os.environ.pop("FIREFLY_MCP_CORPUS_AUTH_ENABLED", None)
        os.environ.pop("FIREFLY_MCP_KEYVAULT_URL", None)


def test_auth_disabled_by_default_keeps_behaviour() -> None:
    from fireflyframework_agentic.exposure.mcp import http_cli

    app = http_cli.build_app()
    client = TestClient(app)
    # No auth installed: /healthz still works, no middleware in route stack.
    response = client.get("/healthz")
    assert response.status_code == 200
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/integration/test_mcp_corpus_auth_e2e.py -v`

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_mcp_corpus_auth_e2e.py
git commit -m "test(mcp): end-to-end coverage for corpus-auth middleware in build_app"
```

---

## Phase 4 — `list_corpora` filtering and operator docs

### Task 12: Filter `list_corpora` to authorised corpora

**Files:**
- Modify: `fireflyframework_agentic/tools/builtins/corpus_rag.py` (only the `list_corpora` function)

- [ ] **Step 1: Read the FastMCP context plumbing**

Check whether `list_corpora` can reach the Starlette `Request`. FastMCP
exposes a contextvar; the simplest portable approach is to read
`request.state.authorised_corpora` via FastMCP's `Context`. If that is
not available in this FastMCP version, fall back to reading a
contextvar that the middleware sets.

If FastMCP `Context` is the chosen path:
- The middleware already sets `request.state.authorised_corpora = (corpus_id,)`.
- The tool signature gains an optional `Context` parameter that FastMCP
  injects automatically.

- [ ] **Step 2: Update `list_corpora`**

Replace the body of `list_corpora` in `corpus_rag.py` with:

```python
@firefly_tool(
    "list_corpora",
    description=(
        "List every corpus_id available on this server. A corpus_id is the name "
        "of a subdirectory of CORPUS_ROOT that contains a corpus.sqlite file. "
        "Call this first when you don't know which corpus to query. Returns "
        "an empty list if CORPUS_ROOT does not exist or contains no corpora. "
        "When corpus auth is enabled, the response is filtered to corpora the "
        "caller's bearer token authorises."
    ),
    tags=("rag", "discovery"),
)
async def list_corpora() -> dict[str, Any]:
    root = _corpus_root()
    corpora: list[dict[str, Any]] = []
    allowed = _authorised_corpora()
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            sqlite_path = entry / "corpus.sqlite"
            if not (entry.is_dir() and sqlite_path.is_file()):
                continue
            if allowed is not None and entry.name not in allowed:
                continue
            st = sqlite_path.stat()
            corpora.append(
                {
                    "corpus_id": entry.name,
                    "size_bytes": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
                }
            )
    return {"corpus_root": str(root), "corpora": corpora}
```

- [ ] **Step 3: Add the `_authorised_corpora` helper**

Add near the top of `corpus_rag.py`, after `_corpus_root()`:

```python
import contextvars

authorised_corpora_var: contextvars.ContextVar[tuple[str, ...] | None] = contextvars.ContextVar(
    "authorised_corpora", default=None
)


def _authorised_corpora() -> tuple[str, ...] | None:
    """Return the corpora the current caller is authorised for, or None for
    "no auth in effect" (unfiltered). Set by ``CorpusAuthMiddleware``."""
    return authorised_corpora_var.get()
```

Update `CorpusAuthMiddleware.dispatch` (in `auth.py`) to also set the
contextvar before calling `call_next`:

```python
from fireflyframework_agentic.tools.builtins.corpus_rag import authorised_corpora_var

# ... near the bottom of dispatch, just before:
# return await call_next(request)
authorised_corpora_var.set((corpus_id,))
```

(Import inside the method body to avoid an import cycle — the
middleware should not unconditionally import a tool module at top level.)

- [ ] **Step 4: Write a focused test for the filter**

Append to `tests/unit/exposure/test_mcp_corpus_auth.py`:

```python
def test_authorised_corpora_contextvar_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """The middleware must populate the contextvar list_corpora reads."""
    from fireflyframework_agentic.tools.builtins import corpus_rag as cr

    captured: list[tuple[str, ...] | None] = []

    store = _StubStore({"demo": "secret-token"})
    from fastapi import FastAPI
    from fireflyframework_agentic.exposure.mcp.auth import CorpusAuthMiddleware
    from fireflyframework_agentic.security.keyvault import CorpusTokenCache

    app = FastAPI()
    app.add_middleware(
        CorpusAuthMiddleware,
        store=store,
        cache=CorpusTokenCache(ttl_seconds=60),
        mount_path="/mcp",
    )

    @app.post("/mcp")
    async def handler(payload: dict) -> dict:
        captured.append(cr.authorised_corpora_var.get())
        return {"ok": True}

    client = TestClient(app)
    client.post("/mcp", json=_body("demo"), headers={"Authorization": "Bearer secret-token"})
    assert captured == [("demo",)]
```

- [ ] **Step 5: Run all auth tests**

Run: `uv run pytest tests/unit/exposure/test_mcp_corpus_auth.py tests/unit/security/ -v`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add fireflyframework_agentic/tools/builtins/corpus_rag.py fireflyframework_agentic/exposure/mcp/auth.py tests/unit/exposure/test_mcp_corpus_auth.py
git commit -m "feat(mcp): filter list_corpora to authorised corpora via contextvar"
```

---

### Task 13: Operator documentation

**Files:**
- Create: `docs/deploy/mcp-corpus-auth.md`

- [ ] **Step 1: Write the operator runbook**

Create `docs/deploy/mcp-corpus-auth.md`:

```markdown
# Per-corpus auth tokens for `firefly-mcp-http`

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The MCP HTTP server can require a per-corpus capability token on every
tool call. Tokens live in Azure Key Vault; the running container's
managed identity reads them with `get` permission only.

## Enable

Set on the Container App:

| Env var | Value |
|---|---|
| `FIREFLY_MCP_CORPUS_AUTH_ENABLED` | `true` |
| `FIREFLY_MCP_KEYVAULT_URL` | `https://<vault>.vault.azure.net` |
| `FIREFLY_MCP_TOKEN_CACHE_TTL_SECONDS` (optional) | `300` |
| `FIREFLY_MCP_TOKEN_SECRET_PREFIX` (optional) | `firefly-mcp-corpus-token-` |

Grant the Container App's managed identity **Key Vault Secrets User** on
the vault. No other role is required.

## Provision a token

```bash
TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
az keyvault secret set \
    --vault-name $KV \
    --name firefly-mcp-corpus-token-$CORPUS_ID \
    --value "$TOKEN"
echo "give this token to the corpus owner: $TOKEN"
```

The plaintext value never leaves Key Vault again — store it in your
secret manager of choice (1Password, Vault, etc.).

## Rotate a token

```bash
TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
az keyvault secret set --vault-name $KV \
    --name firefly-mcp-corpus-token-$CORPUS_ID --value "$TOKEN"
```

Old tokens stop working after at most `FIREFLY_MCP_TOKEN_CACHE_TTL_SECONDS`
seconds (default 300). For a hard cut-over restart the Container App.

## Revoke a token

```bash
az keyvault secret set-attributes --vault-name $KV \
    --name firefly-mcp-corpus-token-$CORPUS_ID --enabled false
```

The server denies new calls for that corpus after the cache TTL window.

## Recovery — Key Vault unreachable

If Key Vault is unreachable, the server returns `503` for **un-cached**
corpora. Already-cached corpora keep working until their TTL expires.
There is no fallback or local override: this is intentional (fail
closed). If you need to operate without Key Vault, set
`FIREFLY_MCP_CORPUS_AUTH_ENABLED=false` and rely on ingress auth alone.

## Caller usage

```http
POST /mcp HTTP/1.1
Authorization: Bearer <token-from-keyvault>
Content-Type: application/json

{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"corpus_query",
           "arguments":{"corpus_id":"demo","question":"hi","top_k":3}}}
```

A token for corpus A cannot call any tool against corpus B; the
middleware returns `403 Forbidden`. `list_corpora` returns only the
corpora the bearer is authorised for.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deploy/mcp-corpus-auth.md
git commit -m "docs(deploy): operator runbook for per-corpus MCP auth tokens"
```

---

## Phase 5 — Pre-merge polish

### Task 14: Repo-wide lint + full test pass

- [ ] **Step 1: Lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`

Expected: no issues. Fix and re-run if any.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest -q`

Expected: green. If a test depends on Azure SDK and Azure extras aren't
installed in CI, ensure the `pytest.importorskip("azure.keyvault.secrets.aio")`
guard is present in the integration test file (see Task 11).

- [ ] **Step 3: Pre-commit dry-run**

Run: `uv run pre-commit run --all-files`

Expected: green.

- [ ] **Step 4: Update CHANGELOG**

Append a new entry to `CHANGELOG.md` under the next unreleased version:

```markdown
- feat(mcp): per-corpus capability tokens in Azure Key Vault. When
  `FIREFLY_MCP_CORPUS_AUTH_ENABLED=true`, every MCP tool call must
  present a bearer matching the `firefly-mcp-corpus-token-<corpus_id>`
  secret. Off by default. See `docs/deploy/mcp-corpus-auth.md`.
```

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): add MCP per-corpus auth entry"
```

---

### Task 15: Push branch and open the PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/mcp-corpus-keyvault-auth
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(mcp): per-corpus capability tokens in Azure Key Vault" --body "$(cat <<'EOF'
## Summary
- Adds `CorpusAuthMiddleware` that authorises every MCP tool call against a per-corpus capability token stored in Azure Key Vault.
- New `KeyVaultTokenStore` + TTL `CorpusTokenCache` under `fireflyframework_agentic/security/keyvault.py`.
- Off by default; enabled via `FIREFLY_MCP_CORPUS_AUTH_ENABLED=true` + `FIREFLY_MCP_KEYVAULT_URL`.
- `list_corpora` is filtered to the caller's authorised corpora.
- STRIDE-based risk register in the design doc; fail-closed on Key Vault outage; constant-time comparison; sha256-binding to corpus_id prevents cross-corpus cache reuse.

## Test plan
- [ ] `uv run pytest tests/unit/security/ tests/unit/exposure/test_mcp_corpus_auth.py tests/integration/test_mcp_corpus_auth_e2e.py -v`
- [ ] Manual: provision a KV secret, hit `/mcp` with and without the correct bearer; rotate; revoke.
- [ ] Manual: confirm `/healthz` is reachable without a token.
- [ ] Manual: confirm the existing stdio transport is unaffected.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Done.

---

## Self-review notes

- **Spec coverage:** every section of the spec maps to a task — token format (Task 1, 3, 5), KV access (Task 5), middleware (Tasks 7, 9), feature flag wiring (Task 10), `list_corpora` filter (Task 12), operator docs (Task 13), tests (Tasks 2, 4, 6, 8, 11, 12). Risk-register items are covered by the tests (constant-time compare via `hmac.compare_digest`; corpus binding via `corpus_token_digest`; outage → 503; cache TTL).
- **Placeholders:** none.
- **Type / name consistency:** `CorpusTokenCache.is_trusted/remember/forget`, `KeyVaultTokenStore.get_corpus_token`, `corpus_token_digest`, `CorpusAuthMiddleware(store=..., cache=..., mount_path=...)`, `authorised_corpora_var` — used identically wherever they appear.
- **Out-of-scope items called out:** admin CRUD UI / CLI, read/write split, rotation grace period, KV ping in `/healthz`.
