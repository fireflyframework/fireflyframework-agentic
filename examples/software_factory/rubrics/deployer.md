# Rubric — Deployer (`deployer`)

The deployer agent minimises the gap between a built artifact and a
live, verifiable deployment. It is provider-agnostic: the same rubric
applies whether the target is Azure SWA, Container Apps, AKS, or
any other runtime.

## Hard criteria (must pass)

- [ ] **Deployment URL returned**: `DeployResult.url` is a non-empty
  HTTPS URL.
- [ ] **Smoke test passes**: HTTP GET on `DeployResult.url` returns
  HTTP 200 within 10 seconds.
- [ ] **Environment matches**: `DeployResult.environment` matches the
  requested environment name (e.g. `staging`, `production`).
- [ ] **Idempotent**: deploying the same artifact twice to the same
  environment produces the same URL and a 200 response (no side-effect
  accumulation).

## Soft criteria

- **Deploy time**: deployment completes in ≤ 5 minutes for static
  bundles, ≤ 10 minutes for container workloads.
- **Rollback available**: the previous deployment remains accessible
  at a versioned URL or slot.
- **Metadata captured**: `DeployResult.metadata` includes at minimum
  the artifact reference and the deployment timestamp.

## Loss function

```
loss = (url_missing × ∞) + (smoke_failed × 10) + (env_mismatch × 5)
       + deploy_time_over_budget
```

`url_missing` and `smoke_failed` are hard failures that raise
`ActionRuntimeError`. The rest are logged as warnings.

## Output schema

```
deploy_result.json:
  {
    "url": "https://...",
    "environment": "production",
    "provider": "azure-swa",
    "artifact_ref": "...",
    "smoke_passed": true,
    "metadata": {}
  }
$GITHUB_OUTPUT:
  deploy_url     — string
  smoke_passed   — true|false
  deploy_provider — string
```
