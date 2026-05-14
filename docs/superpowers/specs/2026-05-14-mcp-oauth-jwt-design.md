# MCP server: OAuth 2.0 / OIDC authentication with App-Roles RBAC

Closes [#177](https://github.com/fireflyframework/fireflyframework-agentic/issues/177) and [#154](https://github.com/fireflyframework/fireflyframework-agentic/issues/154).

## Problem

The HTTP-exposed MCP server has no in-process authentication. The deployed instance currently relies on Azure Container Apps "Easy Auth" sitting in front of it. Easy Auth returns a bare `401` with no `WWW-Authenticate` header, which means standards-compliant MCP clients cannot discover how to authenticate and cannot run the OAuth bootstrap flow themselves. Today the only way to talk to the server is to obtain a bearer manually (`az account get-access-token`) and paste it into headers — friction that does not scale to multiple consultants and forces hourly token rotation.

In addition, there is no per-corpus authorization: any caller who passes the front gate can call every tool against every corpus.

The existing `CorpusAuthMiddleware` solves a different (and now obsolete) problem — per-corpus capability tokens stored in Key Vault. It does not carry user identity, does not validate JWTs, and cannot satisfy the OAuth discovery contract clients need.

## Goal

A consultant on any standards-compliant MCP client (Claude Code, Claude Desktop) connects to Firefly MCP with a single command:

```bash
claude mcp add firefly --transport http https://<host>/mcp/
```

The client discovers from server-published metadata that the resource is OAuth-protected, opens a browser, completes login against the configured OIDC provider (Entra ID in the Signature deployment), persists a refresh token, and silently renews access tokens for the lifetime of the refresh token. Once authenticated, the user can call only the corpora they have been granted access to, with separate read and write permissions.

## Non-goals

- Implementing Dynamic Client Registration (RFC 7591). Entra ID does not support it; operators must pre-register a public client app and document its `client_id`.
- Supporting symmetric-key (HS256) tokens at the MCP HTTP layer. Only asymmetric / JWKS-fronted issuers are supported.
- Token issuance, rotation, or revocation. Those are the IdP's job.
- Group-based authorization. The MVP uses App Roles. A future change can add a group-claim variant behind the same `OAuthConfig` if needed.

## Design

### Architecture

```
┌─ Client (Claude Code/Desktop) ──────────────────────┐
│  1. POST /mcp/                       → 401 + WWW-Authenticate │
│  2. GET /.well-known/oauth-protected-resource       │
│  3. OAuth 2.0 Authorization Code + PKCE             │
│  4. POST /mcp/ Authorization: Bearer <JWT>          │
└─────────────────────────────────────────────────────┘
                       │
                       ▼
┌─ firefly-mcp Container App (no Easy Auth) ──────────┐
│  FastAPI                                            │
│   ├─ /.well-known/oauth-protected-resource  (public)│
│   ├─ /.well-known/oauth-authorization-server (pub)  │
│   ├─ /healthz                              (public) │
│   └─ /mcp/* → OAuthJWTMiddleware → FastMCP app      │
└─────────────────────────────────────────────────────┘
```

### Provider-agnostic by construction

The framework code references only OAuth 2.0 / OIDC concepts (issuer, JWKS, audience, roles claim). Anything Azure-specific (Entra issuer URL shape, Entra App Registration) lives in `examples/corpus_search/`. The mechanism mirrors the existing pattern in `http_cli.py:64`, which already resolves `FIREFLY_MCP_TOKEN_STORE_FACTORY="module.path:callable"` for the legacy capability-token store. The same indirection is reused here.

### Components

| Path | New / modified | Purpose |
|---|---|---|
| `fireflyframework_agentic/exposure/mcp/oauth_jwt.py` | new | Generic OIDC JWT validator. Wraps `jwt.PyJWKClient` and `jwt.decode`. Takes `jwks_url`, `issuer`, `audience`. ~40 LOC. |
| `fireflyframework_agentic/exposure/mcp/oauth_metadata.py` | new | Mounts `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`. Returns JSON built from an `OAuthConfig`. ~30 LOC. |
| `fireflyframework_agentic/exposure/mcp/auth.py` | rewritten | Replaces `CorpusAuthMiddleware` with `OAuthJWTMiddleware`. Reuses the existing dispatch/mount-awareness/body-parsing structure. Authorization uses `RBACManager.has_permission`. |
| `fireflyframework_agentic/exposure/mcp/http_cli.py` | modified | Resolves `FIREFLY_MCP_OAUTH_CONFIG_FACTORY` (mirrors existing `_TOKEN_STORE_FACTORY` resolver) and installs the new middleware + metadata routes. Removes the legacy KV-token install path. |
| `examples/corpus_search/azure_security.py` | modified | Add `build_entra_oauth_config()` returning an `OAuthConfig` populated with Entra ID URLs. The existing `build_default_store` and KV helpers stay only as long as anything else references them; otherwise they are deleted in the same PR. |
| `fireflyframework_agentic/security/corpus_token.py` | deleted | No longer used. The capability-token model is retired. |
| `fireflyframework_agentic/security/__init__.py` | modified | Remove the `CorpusTokenCache` / `CorpusTokenStore` / `corpus_token_digest` re-exports and the matching `__all__` entries. |
| `tests/unit/security/test_corpus_token.py` | deleted | Tests for the deleted module. |
| `docs/deploy/mcp-corpus-auth.md` | rewritten | New operator guide for OAuth/JWT setup, both generic and Entra-specific sections. |

### Reused code

| Existing piece | Reuse |
|---|---|
| `security/rbac.py::RBACManager` | Constructed with `jwt_secret=None` (already supported per its docstring for "externally-issued tokens like Entra ID"). The middleware calls `has_permission(claims, "Corpus.<id>.Read"|".Write")`. The role-table the manager holds is the source of truth for what each App Role grants — wildcard and prefix matches already work. |
| `pyjwt[crypto]` (already in `[azure]` extra) | `PyJWKClient` fetches and caches JWKS automatically. `jwt.decode(token, key=..., audience=..., issuer=...)` validates signature, `aud`, `iss`, `exp`, `nbf`. No bespoke JWT code. |
| `exposure/mcp/auth.py` structural pieces | Mount-aware dispatch, `_EXCLUDED_PATHS`, `_LIFECYCLE_METHODS`, `_NO_CORPUS_TOOLS`, helpers `_extract_method` / `_extract_tool_name` / `_extract_corpus_id`, JSON-RPC error shape, fingerprint helpers. Kept verbatim. |
| `tools/builtins/corpus_rag.py::authorised_corpora_var` | Already filters `list_corpora`. The new middleware populates it from the caller's App Roles. Tool code unchanged. |
| `exposure/mcp/http_cli.py::_resolve_factory` | The factory-spec resolution helper is reused unchanged for the new `_OAUTH_CONFIG_FACTORY` env var. |

### Types and contracts

```python
# fireflyframework_agentic/exposure/mcp/oauth_jwt.py
@dataclass(frozen=True)
class OAuthConfig:
    jwks_url: str
    issuer: str
    audience: str
    roles_claim: str = "roles"
    scope: str = ""              # advertised in /.well-known/
    resource_uri: str = ""       # advertised in /.well-known/

OAuthConfigFactory = Callable[[], OAuthConfig]

class JWTValidator:
    """Process-wide JWT validator.

    Constructed once at app startup with the resolved `OAuthConfig`.
    Holds a `PyJWKClient` whose JWKS cache is reused across requests."""

    def __init__(self, config: OAuthConfig) -> None: ...
    def validate(self, token: str) -> dict[str, Any]:
        """Return claims dict. Raises ValueError on any validation
        failure (signature, audience, issuer, expiry). Callers map to 401."""
```

### Authorization rules

App Role naming convention (defined per deployment, advertised in operator docs):

- `Corpus.<corpus_id>.Read` — grants `corpus_query`, `knowledge_search`, and inclusion of `<corpus_id>` in `list_corpora` output.
- `Corpus.<corpus_id>.Write` — grants `ingest_corpus_filesystem`, `ingest_corpus_structured`, `discover_corpus_schema`.

`Write` implies `Read` for the same corpus. The implication is enforced by the middleware (not by Entra): when computing the required role for a read tool, the check passes if the caller has either `Corpus.<id>.Read` or `Corpus.<id>.Write` for that corpus. Operators therefore only need to assign the higher-privilege role.

App Role `value` strings in Entra are constrained to `[A-Za-z0-9._-]`. `corpus_id` values that violate this charset must be normalised (or the role naming convention must be revised) before assignment; the operator guide will document the constraint. Existing corpus_ids in production already conform.

Middleware logic on each `tools/call`:

1. Validate JWT → claims.
2. Extract `tool_name` and `corpus_id` from request body.
3. Compute the required role: read tools require `Corpus.<id>.Read`, write tools require `Corpus.<id>.Write`.
4. Call `RBACManager.has_permission(claims, required_role)`. If false → JSON-RPC error 403.
5. Compute `authorised_corpora` = set of `corpus_id` values for which the caller has at least `.Read` (parsed from the `roles` claim). Set the existing contextvar so `list_corpora` filtering keeps working unchanged.

Lifecycle methods (`initialize`, `tools/list`, `ping`, `notifications/*`) require a valid JWT but no per-corpus check. `list_corpora` requires a valid JWT and is filtered by the contextvar.

### Configuration

Framework env vars (no provider names):

| Var | Default | Notes |
|---|---|---|
| `FIREFLY_MCP_AUTH_ENABLED` | `false` | When false, middleware is not installed and metadata routes are not mounted. |
| `FIREFLY_MCP_OAUTH_CONFIG_FACTORY` | `examples.corpus_search.azure_security:build_entra_oauth_config` | `module.path:callable` returning an `OAuthConfig`. |

Example-side env vars (consumed by `build_entra_oauth_config`):

| Var | Required | Notes |
|---|---|---|
| `AZURE_TENANT_ID` | yes | Used to construct issuer and JWKS URLs. |
| `AZURE_CLIENT_ID` | yes | Used as `audience` (`api://<client_id>`) and as the scope prefix. |

The factory raises a clear `RuntimeError` if either is missing; mirroring the error-handling style of the existing `_resolve_factory`.

### Removal of Easy Auth

The Container App's Easy Auth configuration is disabled as part of the rollout (operationally, not in code). Without that step the new middleware never sees the raw request because Easy Auth strips the `Authorization` header and replaces it with `X-MS-CLIENT-PRINCIPAL`. The operator guide documents the disable command. The rollback path (re-enable Easy Auth) is one CLI call away.

### Error handling

| Condition | HTTP | JSON-RPC error code | Body message |
|---|---|---|---|
| No `Authorization` header | 401 | -32001 | `Missing or malformed Authorization header` |
| Token validation failure (bad signature, wrong `aud`, expired, wrong `iss`) | 401 | -32001 | `Invalid or expired token` (no detail leaked) |
| Body missing `corpus_id` for a corpus-scoped tool | 400 | -32001 | `Missing corpus_id in tool arguments` |
| Caller lacks the required App Role | 403 | -32001 | `Forbidden for this corpus` |
| JWKS endpoint unreachable on cold cache | 503 | -32001 | `Authorization service unavailable` |

All `401` responses MUST include:

```
WWW-Authenticate: Bearer resource_metadata="https://<host>/.well-known/oauth-protected-resource"
```

This is the breadcrumb that triggers OAuth discovery in the client.

### Testing

Unit tests under `tests/exposure/mcp/`:

- `test_oauth_jwt.py` — token validation: good token, bad signature, wrong `aud`, wrong `iss`, expired, missing claims. JWKS cache hit/miss. Uses a locally-generated RSA keypair and a fake JWKS document; no network.
- `test_oauth_metadata.py` — `/.well-known/*` endpoint shape and values.
- `test_auth_middleware.py` — replaces `test_auth.py`. Covers: anonymous → 401 with `WWW-Authenticate`; valid token with no roles → 403 on tools/call; valid token with `Corpus.foo.Read` → can call `corpus_query` on `foo`, denied on `bar`; write-required tool denied with only `.Read`; `list_corpora` filtered by contextvar; lifecycle methods pass with valid token regardless of roles.
- `test_http_cli_auth.py` — factory resolution: env var unset (default factory), env var set to alternative path, factory raising `RuntimeError`, factory returning bad shape.

Integration coverage: a manual checklist in the operator guide for the `claude mcp add` end-to-end flow against a real Entra tenant. Automating this requires a long-lived test tenant and is out of scope for the MVP.

### Migration / rollout

1. Deploy the new image with `FIREFLY_MCP_AUTH_ENABLED=false`. Verify health.
2. Set `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` env vars and flip `FIREFLY_MCP_AUTH_ENABLED=true`. Restart revision. Verify anonymous request returns 401 with the `WWW-Authenticate` header and `/.well-known/oauth-protected-resource` returns valid JSON.
3. Disable Easy Auth on the Container App.
4. Run `claude mcp add` from a test consultant machine and verify the browser flow completes.
5. Assign App Roles to a pilot user in the Enterprise Application blade. Verify they can only call tools for corpora they have a role on.

Rollback: re-enable Easy Auth (one command). The legacy capability-token middleware is deleted in this PR — there is no in-code rollback to it. Any deployment that still needs capability tokens should not upgrade.

## Open questions

- Should App Role assignment to users be required (`appRoleAssignmentRequired = true` on the Service Principal)? This would prevent any tenant user from authenticating at all without a role. The MVP leaves it `false`; the operator guide notes how to flip it.
- For multi-corpus operations (none today, but possible: cross-corpus search), the rule "one tool call → one required role" is insufficient. Out of scope; flagged for a future issue if/when such tools land.

## Out of scope

- Group-claim authorization mode.
- Token introspection (RFC 7662).
- Resource indicators (RFC 8707) beyond what `audience` already covers.
- Dynamic Client Registration.
