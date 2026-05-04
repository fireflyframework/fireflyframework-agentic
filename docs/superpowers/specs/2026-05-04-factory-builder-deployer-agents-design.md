# Spec 10 — Builder + Deployer Agents (GitOps)

**Date:** 2026-05-04
**Status:** Draft — MVP2 backlog (not approved)
**Owner:** Agentic Factory MVP2
**Depends on:** Specs 1–4 (MVP1 stable); access to a target Kubernetes cluster (or equivalent) for the demo.
**Required by:** doc Phase-1 parity for "deploy + verify in real env"; the QA loop's stronger guarantees.

---

## Context

MVP1's deliverable is "a green PR". That proves the codegen + qa loop end-to-end, but it does **not** prove the generated app survives in a real environment: real database, real network policies, real IAM, real observability. The architecture document treats "deployed and verified" as the actual definition of done; MVP1 punts on that to keep the loop bounded.

This spec adds two agents — `builder` (artifacts) and `deployer` (deploy + smoke) — and the GitOps wiring that lets the QA loop run against a deployed environment, not just unit tests.

## Non-goals

- Building `fireflyframework-infra` itself. This spec assumes IaC primitives are reusable (or shells out to existing Helm/Crossplane charts maintained elsewhere).
- Multi-region or multi-cloud. MVP2 targets one cluster.
- Production rollouts. Deployer ships to a `staging` environment; production promotion stays human-gated.

## Sketch

### `builder` agent

- Role: dispatch the generated repo's `build.yml`, parse JUnit/pytest/coverage outputs into a `BuildReport`, hand off the OCI image reference to deployer.
- Reasoning: `ReActPattern` (cheap, deterministic). Model: Claude Haiku.
- Tools: `github_dispatch` (trigger build.yml), `github_status` (poll), `parse_test_results`, `oci_inspect` (read the published image manifest).
- Output: `BuildReport.json` + `image_ref` workflow output.
- New action `.github/actions/builder/`.

### `deployer` agent

- Role: render Kubernetes manifests from `architecture.yaml`, commit them to an `environments/` repo (single source of truth for cluster state), wait for Argo CD or Flux reconciliation, smoke-test the deployment.
- Reasoning: `PlanAndExecutePattern`. Model: Claude Sonnet.
- Tools: `manifest_render` (Helm/jsonnet template lookup), `git_commit` (against `environments/`), `argocd_sync_status` (or `flux_status`), `http_probe` (post-deploy smoke).
- Output: `DeployReport.json` with `endpoint_url` + `deployed_sha` + `smoke_passed`.
- New action `.github/actions/deployer/`.

### Workflow changes

`factory-qa.yml` is split into:

- `factory-build.yml` (triggered after `factory-generate.yml`, runs builder)
- `factory-deploy.yml` (triggered after build green, runs deployer)
- `factory-qa.yml` (triggered after deploy, runs qa against `endpoint_url`)

The QA loop's failure path (Spec 4) loops back to `factory-generate.yml`, regenerating, rebuilding, redeploying, retesting — same iteration counter, same 3-iteration budget.

## Sync waves

Generated apps follow the doc's three-wave model:

- **Wave 1** — core (config, secrets, datastores).
- **Wave 2** — domain services (the generated app itself).
- **Wave 3** — experience layer (BFF, gateway).

A single-service demo only uses Wave 2. Multi-service intents (a future capability) use all three.

## Verification

- A demo run of corpus-search lands a green deploy in a `staging` cluster; `endpoint_url` is reachable; smoke probes pass; `qa.yml` runs against the live endpoint.
- A perturbation test: hand-edit a generated config to fail health probes. Deployer reports failure; QA loop returns to codegen with the deploy logs.
- Image and manifest provenance: each release tag links to the OCI image (signed via `cosign`) and the GitOps commit SHA.

## Open questions

- Where does the `environments/` repo live? Per-customer? One global? Spec proposes per-customer for MVP2 (each demo run targets one customer cluster); SaaS (Spec 13) revisits.
- Argo CD vs Flux: the spec is reconciler-agnostic (`argocd_sync_status` and `flux_status` are alternative tools); the workflow picks one based on a customer-config value.
- IaC primitives: do we vendor Crossplane XRs or generate Terraform? Spec proposes Crossplane (matches doc §3.2) but defers a final pick until `fireflyframework-infra` has a v1.
- Cost guard: a deploy is expensive (cluster resources, image pulls). The `decide` step in the QA loop must consider deploy cost when choosing whether to retry — not just LLM cost.
