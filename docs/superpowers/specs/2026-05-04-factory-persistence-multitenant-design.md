# Spec 13 — Persistence + Multi-Tenant + Audit

**Date:** 2026-05-04
**Status:** Draft — MVP2 backlog (not approved)
**Owner:** Agentic Factory MVP2
**Depends on:** Specs 6 + 7 (programmatic pipeline + REST entry); ideally Specs 8–11 too, since multi-tenancy is most useful when the factory is feature-complete.
**Required by:** any deployment of the factory as a SaaS to multiple customer organizations.

---

## Context

MVP1 ships a single-tenant, GitHub-native factory. That is the right shape to validate the loop with one or two pilot customers. Beyond that, the factory needs the SaaS plumbing the architecture document calls out: persistent run state, workspace isolation per tenant, RBAC with 30+ permissions, append-only audit trail, billing hooks. None of those is needed to prove the agentic loop; all of them are needed to operate it.

This spec is deliberately the last in the MVP2 backlog. It only makes sense to invest after the agentic core (factory + GitHub + programmatic + knowledge graph + builder/deployer) is producing value.

## Non-goals

- A new IAM / IdP. Reuse existing OIDC / Entra ID / Okta integrations from `fireflyframework_agentic.security.rbac`.
- A new billing system. Surface usage via OpenTelemetry / `UsageTracker`; integrate with whatever subscription system the host application uses.
- Cross-region replication. One Postgres + one object store per region.

## Sketch

### Persistence

- New module `factory.persistence` with SQLAlchemy 2 models:
  - `WorkspaceRecord` (id, slug, owner, created_at, settings_json).
  - `RunRecord` (id, workspace_id, intent_text, status, started_at, finished_at, cost_usd_total).
  - `StageRecord` (id, run_id, stage, status, agent, model, tokens_in, tokens_out, cost_usd, started_at, finished_at, payload_pointer).
  - `ArtifactRecord` (id, stage_id, name, content_hash, size_bytes, storage_uri).
  - `AuditEntry` (id, workspace_id, actor, action, target, details_json, created_at) — append-only.
- Backed by Postgres (production) or SQLite (dev). The existing `[postgres]` extra is sufficient.
- Artifact bodies live in object storage (S3-compatible); the DB stores pointers + content hashes.

### Multi-tenant

- Every API call (Spec 7) carries a `workspace_id` derived from the authenticated principal.
- The `PipelineContext` (Spec 6) gains a `workspace` attribute; agent tools read it to scope every operation.
- The knowledge base (Spec 2) is shared by default with workspace-overlay support: a workspace can ship its own `knowledge_base_overlay/` with skills/archetypes/prompts/ADRs that override or extend the global set.
- The structured PRD/ADR memory (Spec 8) is per-workspace. The graph layer is global by default; tenants can opt into a workspace-local graph.

### RBAC

- Reuse the existing `RBACManager` + `@require_permission` decorator.
- 30+ discrete permissions, grouped: `project.*`, `build.*`, `deploy.*`, `infra.*`, `vcs.*`, `knowledge.*`, `admin.*`. Concrete list lives in `factory.security.permissions`.
- Default roles: `viewer`, `developer`, `architect`, `owner`. Customers can define custom roles via the API.

### Audit

- Every state-changing API call (run start, stage transition, deploy) writes one `AuditEntry`.
- Append-only, tamper-evident: each entry stores `prev_hash = hash(prev_entry)`, forming a chain. Periodic checkpoint signed by an external timestamping service (out of scope here — emit a hook).
- PII sanitization: free-text fields run through `OutputGuard` before persistence.

## Verification

- A two-tenant smoke test: tenant A's run does not see tenant B's PRDs / ADRs / runs / audit entries.
- An RBAC test: a `viewer` token cannot dispatch a run; an `owner` can; a `developer` can dispatch but not deploy to production.
- An audit-trail test: tampering with one row in `audit_entry` makes subsequent hash-chain validation fail.
- Migration story: `alembic` migrations exist for every model; running them against an empty DB yields the live schema.

## Open questions

- Where does object storage live? Customer-provided S3-compatible bucket? Provider-managed? Spec proposes both: a `StorageBackend` Protocol with S3 + GCS + Azure Blob + local-disk implementations; per-workspace config.
- The audit hash chain is single-writer. Multi-region eventually-consistent audit needs a different shape (e.g., per-region chains + reconciliation). Out of scope for v1.
- Does the deployer agent (Spec 10) write audit entries about the *generated* app's deployments, or only about factory-internal events? Spec proposes both, with separate `audit_entry.scope` values (`factory` vs `app`).
- Token cost attribution to tenants depends on accurate per-call accounting. The existing `UsageTracker` already records this; needs a `workspace_id` tag added.
