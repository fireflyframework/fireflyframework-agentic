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

## Provision / rotate / revoke tokens

Two equivalent paths: the framework ships a small CLI
(`firefly-mcp-token`) for the common operations, or you can drive
`az keyvault` directly.

### Option A — the `firefly-mcp-token` CLI (recommended)

Authenticates via `DefaultAzureCredential` (managed identity in Azure,
`az login` locally). The minted token is printed to **stdout**; status /
errors go to **stderr**, so you can pipe it straight into a password
manager.

```bash
export FIREFLY_MCP_KEYVAULT_URL=https://<vault>.vault.azure.net

# Create — refuses if the secret already exists (use rotate instead).
firefly-mcp-token create real-data > /secure/store/real-data.token

# Rotate — old tokens stop working after the cache TTL (default 300 s).
firefly-mcp-token rotate real-data > /secure/store/real-data.token

# Revoke — disable the current version. Re-run with --yes to confirm.
firefly-mcp-token revoke real-data --yes

# List — show every corpus_id that has a token in the vault.
firefly-mcp-token list

# Compose a secret name without any network call (handy in shell scripts).
firefly-mcp-token show-name real-data
# → firefly-mcp-corpus-token-real-data
```

Flags:

- `--vault-url`: overrides `$FIREFLY_MCP_KEYVAULT_URL`.
- `--prefix`: must match `FIREFLY_MCP_TOKEN_SECRET_PREFIX` on the server.
- `create --bytes N`: token entropy in bytes (default 32 → ~256 bits;
  minimum 16).
- `create --force`: overwrite an existing secret value.

The CLI never prints the token to stderr, never logs it, and refuses
short entropy.

### Option B — raw `az keyvault`

```bash
TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
az keyvault secret set \
    --vault-name "$KV" \
    --name "firefly-mcp-corpus-token-$CORPUS_ID" \
    --value "$TOKEN"
echo "Token for $CORPUS_ID: $TOKEN"

# Rotate: same command, new value.
# Revoke:
az keyvault secret set-attributes \
    --vault-name "$KV" \
    --name "firefly-mcp-corpus-token-$CORPUS_ID" \
    --enabled false
```

In both paths the plaintext value never leaves Key Vault again — store
it immediately in your secret manager (1Password, Vault, etc.) and
never commit it.

## Recovery — Key Vault unreachable

If Key Vault is unreachable, the server returns `503` for **un-cached**
corpora. Already-cached corpora keep working until their TTL expires.
There is no local fallback: this is intentional (fail closed). If you
must operate without Key Vault, set
`FIREFLY_MCP_CORPUS_AUTH_ENABLED=false` and rely on the ingress auth
alone.

## Caller usage

Every request must carry **two** headers:

- `Authorization: Bearer <token-from-keyvault>`
- `X-Firefly-Corpus-Id: <corpus_id>`

The middleware validates the bearer against `firefly-mcp-corpus-token-<X-Firefly-Corpus-Id>`
**before** looking at the body. This way the JSON-RPC handshake
(`initialize`, `tools/list`) and cross-corpus tools (`list_corpora`) are
also gated — an outsider without a valid corpus token cannot even
enumerate the tool schemas or learn which corpora exist on the server.

```http
POST /mcp HTTP/1.1
Authorization: Bearer <token-from-keyvault>
X-Firefly-Corpus-Id: demo
Content-Type: application/json

{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"corpus_query",
           "arguments":{"corpus_id":"demo","question":"hi","top_k":3}}}
```

If `arguments.corpus_id` is present, it **must match** the header value;
mismatch is a hard `403` so a token for corpus A cannot be used to
target corpus B by smuggling a different ID into the body. For tools
without a `corpus_id` argument (e.g. `list_corpora`), the header alone
provides the binding and the response is filtered to that corpus.

### Claude Desktop / `mcp-remote`

Add the second header to the entry's `args`:

```json
{
  "mcpServers": {
    "firefly-real-data": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://<host>/mcp/",
        "--header", "Authorization: Bearer <token-for-real-data>",
        "--header", "X-Firefly-Corpus-Id: real-data"
      ]
    }
  }
}
```

A user who needs access to two corpora gets two entries — one per
corpus — each with its own bearer and `X-Firefly-Corpus-Id`. The pair
is what authorises the request; there is no way to mix tokens between
entries.

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
| No `X-Firefly-Corpus-Id` header | `401` |
| Bearer does not match KV secret for the header's `corpus_id` | `403` |
| Header `corpus_id` differs from `arguments.corpus_id` in body | `403` |
| `tools/call` against a corpus-scoped tool, no body `corpus_id` | `400` |
| Secret missing / disabled in KV | `403` (deliberately indistinguishable from wrong token) |
| KV unreachable (un-cached corpus) | `503` |
