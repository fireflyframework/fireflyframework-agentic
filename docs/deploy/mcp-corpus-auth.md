# Per-corpus auth tokens for `firefly-mcp-http`

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The MCP HTTP server can require a per-corpus capability token on every
tool call. Tokens live in Azure Key Vault; the running container's
managed identity reads them with `get` permission only. A leaked token
exposes one corpus, not the whole server.

## Enable

Set on the Container App:

| Env var | Required | Value |
|---|---|---|
| `FIREFLY_MCP_CORPUS_AUTH_ENABLED` | yes | `true` |
| `FIREFLY_MCP_KEYVAULT_URL` | yes | `https://<vault>.vault.azure.net` |
| `FIREFLY_MCP_TOKEN_CACHE_TTL_SECONDS` | no | `300` (default) |
| `FIREFLY_MCP_TOKEN_SECRET_PREFIX` | no | `firefly-mcp-corpus-token-` (default) |

Grant the Container App's managed identity **Key Vault Secrets User**
on the vault. No `set` / `list` / `delete` is required: the running
server only reads. Granting more would make a compromised replica able
to mint or destroy tokens — keep it least-privilege.

## Provision a token

```bash
TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
az keyvault secret set \
    --vault-name "$KV" \
    --name "firefly-mcp-corpus-token-$CORPUS_ID" \
    --value "$TOKEN"
echo "Token for $CORPUS_ID: $TOKEN"
```

The plaintext value never leaves Key Vault again. Store it in the
caller's secret manager (1Password, Vault, etc.) and never commit it.

## Rotate a token

```bash
TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
az keyvault secret set \
    --vault-name "$KV" \
    --name "firefly-mcp-corpus-token-$CORPUS_ID" \
    --value "$TOKEN"
```

Old tokens stop working after at most
`FIREFLY_MCP_TOKEN_CACHE_TTL_SECONDS` seconds (default 300). For a hard
cut-over restart the Container App revision.

## Revoke a token

```bash
az keyvault secret set-attributes \
    --vault-name "$KV" \
    --name "firefly-mcp-corpus-token-$CORPUS_ID" \
    --enabled false
```

The server denies new calls for that corpus after the cache TTL window.

## Recovery — Key Vault unreachable

If Key Vault is unreachable, the server returns `503` for **un-cached**
corpora. Already-cached corpora keep working until their TTL expires.
There is no local fallback: this is intentional (fail closed). If you
must operate without Key Vault, set
`FIREFLY_MCP_CORPUS_AUTH_ENABLED=false` and rely on the ingress auth
alone.

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

## What this layer does not do

- It does not replace ingress auth. The ingress JWT (when present)
  identifies the *caller*; this token authorises the *resource*. Run
  both for defence in depth.
- It does not distinguish read from write. A corpus token grants every
  MCP tool call against that corpus. A read-only / write split would
  need two tokens per corpus; flagged as future work.
- It does not gate the stdio transport. Local Claude Desktop / Claude
  Code clients spawn the MCP server as a subprocess and rely on the
  user's own credentials.

## Failure-mode reference

| Condition | HTTP status |
|---|---|
| No `Authorization` header | `401` |
| `Authorization` not `Bearer ...` | `401` |
| Tool args have no `corpus_id` | `400` |
| Bearer does not match KV secret for `corpus_id` | `403` |
| Secret missing / disabled in KV | `403` (deliberately indistinguishable) |
| KV unreachable (un-cached corpus) | `503` |
