# OAuth 2.0 authentication for `firefly-mcp-http`

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The MCP HTTP server can require an OAuth 2.0 bearer token on every tool
call, validated against any OIDC-compliant identity provider. App-Roles
embedded in the token control per-corpus read/write access. The framework
ships with default factories for Microsoft Entra ID; other IdPs (Okta,
Auth0, Cognito, Keycloak) plug in by swapping two factory env vars.

## Enable

Three env vars are required at minimum:

```bash
FIREFLY_MCP_AUTH_ENABLED=true

# Defaults shown — override to use a non-Entra IdP.
FIREFLY_MCP_VERIFIER_FACTORY=examples.corpus_search.azure_security:build_entra_verifier
FIREFLY_MCP_METADATA_FACTORY=examples.corpus_search.azure_security:build_entra_metadata

# Canonical public URL of this MCP server (no trailing slash).
FIREFLY_MCP_PUBLIC_URL=https://mcp.example.com
```

Optional:

| Var | Default | Notes |
|---|---|---|
| `FIREFLY_MCP_ROLES_CLAIM` | `roles` | JWT claim that holds App Roles. Entra: `roles`. Okta: `groups`. Auth0: `permissions`. |

## How it works

Anonymous request to `/mcp/*` returns `401 Unauthorized` with
`WWW-Authenticate: Bearer resource_metadata="<url>"`, which is the
contract MCP clients use to bootstrap OAuth login. The two public
endpoints mounted alongside the middleware:

* `GET /.well-known/oauth-protected-resource` (RFC 9728) — tells the
  client which authorization server protects this resource.
* `GET /.well-known/oauth-authorization-server` (RFC 8414) — minimal
  authorization-server metadata, pre-baked from the IdP's values so
  clients only need to fetch one well-known URL.

On a valid bearer the middleware verifies signature (JWKS), `aud`,
`iss`, `exp`, extracts the roles claim, and checks
`Corpus.<corpus_id>.Read|Write` against the called tool.

## App Roles convention

The default `required_role_fn` enforces:

| Tool | Required role |
|---|---|
| `corpus_query`, `knowledge_search` | `Corpus.<corpus_id>.Read` |
| `ingest_corpus_filesystem`, `ingest_corpus_structured`, `discover_corpus_schema` | `Corpus.<corpus_id>.Write` |
| `list_corpora`, `initialize`, `tools/list`, … | (none — token only) |

`.Write` implies `.Read` for the same corpus, enforced server-side; assign
the higher-privilege role only.

App Role `value` strings in Entra are constrained to `[A-Za-z0-9._-]` —
`corpus_id` values must conform.

## Microsoft Entra ID quickstart

### One-time setup

```bash
# 1. Create the App Registration
az ad app create --display-name firefly-mcp --sign-in-audience AzureADMyOrg

APPID=$(az ad app list --display-name firefly-mcp --query "[0].appId" -o tsv)

# 2. Create the Service Principal
az ad sp create --id $APPID

# 3. Set the identifier URI
az ad app update --id $APPID --identifier-uris "api://$APPID"

# 4. Define the user_impersonation scope (via Azure Portal, or `az rest`
#    against MS Graph PATCH /v1.0/applications/<objectId>).

# 5. Pre-authorize Azure CLI (well-known appId 04b07795-8ddb-461a-bbee-02f9e1bf7b46)
#    so consultants can run `az account get-access-token` without consent prompts.
```

### Define App Roles

In **App registrations → firefly-mcp → App roles**, add one role per
`(corpus_id, access level)` pair. Examples:

| Display name | Value | Allowed member types |
|---|---|---|
| Corpus acme — Read | `Corpus.acme.Read` | Users, Groups |
| Corpus acme — Write | `Corpus.acme.Write` | Users, Groups |

### Assign users / groups

In **Enterprise applications → firefly-mcp → Users and groups**, assign
each consultant (or a group) to the App Roles they need. To require
explicit assignment for *any* access, set
**Properties → Assignment required = Yes**.

### Container App env vars

```bash
az containerapp update -n firefly-mcp -g rg-firefly --set-env-vars \
  FIREFLY_MCP_AUTH_ENABLED=true \
  FIREFLY_MCP_PUBLIC_URL=https://mcp.example.com \
  AZURE_TENANT_ID=<tenant-guid> \
  AZURE_CLIENT_ID=<app-id>
```

### Disable Easy Auth

If the Container App had Easy Auth enabled (legacy), turn it off — the
in-process middleware now owns authentication and Easy Auth strips the
`Authorization` header that the middleware needs to see.

```bash
az containerapp auth update -n firefly-mcp -g rg-firefly --enabled false
```

## Local development

Two modes, pick whichever fits the task.

### Mode A — auth disabled (default, fastest)

`FIREFLY_MCP_AUTH_ENABLED` is `false` by default, so the local server runs
with no authentication and accepts any request. Use this for almost all
day-to-day work on tools, retrieval, and agent code.

```bash
firefly-mcp-http
# in another shell:
curl -X POST http://localhost:8000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### Mode B — full OAuth against your real tenant

Use this only to validate the auth path itself (middleware, role checks,
discovery metadata) end-to-end before deploying.

```bash
export FIREFLY_MCP_AUTH_ENABLED=true
export AZURE_TENANT_ID=<tenant-guid>
export AZURE_CLIENT_ID=<app-id>
export FIREFLY_MCP_PUBLIC_URL=http://localhost:8000
firefly-mcp-http
```

Then drive it as a real client would:

```bash
TOKEN=$(az account get-access-token --resource api://<app-id> --query accessToken -o tsv)

curl -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Assign yourself the App Roles you want to exercise (in
**Enterprise applications → Users and groups**) before running the
request — your token's `roles` claim is what the middleware checks. A
new role assignment is reflected in the next token you mint with
`az account get-access-token`.

The previous capability-token operator CLI (`firefly-mcp-token`) is no
longer shipped — Entra emits all tokens now, so there is nothing to
mint locally.

## Connecting a client

### Claude Code / Claude Desktop

```bash
claude mcp add firefly --transport http https://mcp.example.com/mcp/
```

The client follows the `WWW-Authenticate` breadcrumb, reads
`/.well-known/oauth-protected-resource`, opens a browser to Entra,
completes login, and persists a refresh token. Subsequent calls renew
silently for the lifetime of the refresh token (~90 days of inactivity).

### Manual curl probe

```bash
TOKEN=$(az account get-access-token --resource api://<app-id> --query accessToken -o tsv)

curl -sS -X POST https://mcp.example.com/mcp/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2024-11-05","capabilities":{},
                 "clientInfo":{"name":"probe","version":"1"}}}'
```

## Rollback

**Soft rollback (disable in-process auth, re-enable Easy Auth):**

```bash
az containerapp update -n firefly-mcp -g rg-firefly --set-env-vars FIREFLY_MCP_AUTH_ENABLED=false
az containerapp auth update -n firefly-mcp -g rg-firefly --enabled true
```

**Hard rollback (downgrade image):** deploy the previous tag. The
legacy per-corpus capability-token model is no longer in the codebase —
operators who still need it must stay on the previous release.

## Non-Entra IdPs

Implement a `TokenVerifier` subclass (or any object with
`validate_token(token: str) -> dict[str, Any]`) and a factory that
returns it, plus a metadata factory returning an `OAuthMetadata`. Point
the two `FIREFLY_MCP_*_FACTORY` env vars at your `"module.path:callable"`
specs. The framework imports and calls them at startup.
