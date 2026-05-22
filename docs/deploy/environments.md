# MCP environments: pre and prod

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The `firefly-mcp` Container App is deployed in two environments inside
`rg-firefly`, sharing the same Container Apps environment, ACR, Entra
App Registration and Key Vault.

| Environment | Container App | URL |
|---|---|---|
| Pre | `firefly-mcp-pre` | `https://firefly-mcp-pre.mangosmoke-5d24814d.spaincentral.azurecontainerapps.io` |
| Prod | `firefly-mcp` | `https://firefly-mcp.mangosmoke-5d24814d.spaincentral.azurecontainerapps.io` |

## Deploy model

Driven by `.github/workflows/deploy-mcp.yml`:

- **Push to `main`** → builds the image and deploys to `firefly-mcp-pre`.
- **Push of a `v*` tag** → deploys that tag to `firefly-mcp` (prod).
- **`workflow_dispatch`** → choose `pre` or `prod` as the target.

There is no `pre` branch. Merging a PR is "ship to pre"; tagging a
commit on `main` is "promote to prod".

To promote pre to prod:

```bash
git checkout main && git pull --ff-only
git tag vYY.MM.DD              # e.g. v26.05.22
git push origin vYY.MM.DD
```

## What pre and prod share

- **Entra App Registration** (`api://e62669f2-…`): consultants' OAuth
  tokens validate against both environments.
- **Key Vault** `kv-firefly-signature`: same secret references
  (`ANTHROPIC-API-KEY`, `EMBEDDING-BINDING-*`, `firefly-mcp-static-api-key`,
  `APPLICATIONINSIGHTS-CONNECTION-STRING`).
- **Managed identity** `firefly-mcp-mi` (ACR pull, Key Vault read,
  SharePoint access).
- **ACR** `fireflysignature.azurecr.io/firefly-mcp` — pre and prod pull
  by commit SHA tag; the workflow also publishes a moving `pre` / `prod`
  tag per environment.

## What pre and prod do *not* share

- **Container App resource** (revisions, scaling, logs are independent).
- **`FIREFLY_MCP_PUBLIC_URL`** — each app advertises its own URL via the
  OAuth discovery endpoints.
- **Corpus storage volume.** Prod's `corpus_rag` state lives on an Azure
  Files share (see `corpus-persistence.md`); pre is not mounting one and
  uses ephemeral `/tmp` storage. Re-ingest on pre after a cold start.

## Granting deploy access on a new pre/prod app

The GitHub deploy service principal `firefly-github-actions-deploy`
(`de69fe49-c714-4e28-a356-f04446424138`) needs `Container App Image
Updater` scoped to each app it must update:

```bash
az role assignment create \
  --assignee de69fe49-c714-4e28-a356-f04446424138 \
  --role "Container App Image Updater" \
  --scope /subscriptions/<sub>/resourceGroups/rg-firefly/providers/Microsoft.App/containerapps/<app>
```

Without this, the workflow's `Build & push image` step succeeds but
`Update Container App` fails with `the containerapp '<name>' does not exist`.
