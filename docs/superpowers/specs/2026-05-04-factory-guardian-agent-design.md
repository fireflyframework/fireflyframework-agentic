# Spec 9 — Guardian Agent Split

**Date:** 2026-05-04
**Status:** Draft — MVP2 backlog (not approved)
**Owner:** Agentic Factory MVP2
**Depends on:** Spec 3 (codegen + Reflexion); a few real demo runs so we know which Reflexion checks miss in practice.
**Required by:** doc Phase-1 parity; regulatory-pack support; clear separation of concerns when codegen grows beyond pyfly.

---

## Context

In MVP1, codegen subsumes the architecture-document's "Guardian" role via `ReflexionPattern` — generate, critique, improve. That is the right shortcut for v1: one agent, one model, one budget. But it has three problems that surface as the factory matures:

1. **Codegen optimizes for "tests pass" + "code looks clean", not for compliance / dependency hygiene / SAST.** Those checks are different concerns; bundling them into the Reflexion loop dilutes both.
2. **Regulatory packs (PCI-DSS, GDPR, sector-specific) are reusable across stacks.** Pinning them to codegen-pyfly forces every new stack (Spec 12: Java) to re-import the same review skills.
3. **Guardian decisions belong on the PR**, where humans review them, not buried in codegen's internal critique log.

This spec extracts review into a dedicated `guardian` agent that runs as a separate workflow after codegen opens the PR.

## Non-goals

- A new SAST tool. Reuse the existing `dependency_audit` and `compliance_check` `BaseTool`s; this spec wires them into a dedicated agent, not new scanners.
- Replacing codegen's Reflexion loop. Codegen still does internal critique; guardian adds a second, external opinion.
- A blocking gate. Guardian comments on the PR; the QA loop is the source of truth for pass/fail.

## Sketch

- New agent `guardian` under `factory/agents/guardian.py`: Claude Opus, `ReflexionPattern` (review → critique own review → finalize), tools: `code_review`, `compliance_check`, `dependency_audit`, `knowledge_search`. Output: PR comment + `GuardianReport.json` artifact with `findings: list[Finding]` keyed by file/line and severity.
- New workflow `.github/workflows/factory-review.yml` triggered on `pull_request: opened/synchronize` for PRs labelled `factory:generated` (same trigger as `factory-qa.yml`, runs in parallel with CI).
- New action `.github/actions/guardian/`.
- Regulatory packs are markdown artifacts in `knowledge_base/regulatory_packs/<pack-name>/` with frontmatter `applies_when: <jq-on-prd>`. Guardian filters active packs by evaluating the jq against the run's PRD.
- The QA workflow's `decide` job reads `GuardianReport.json` alongside the QA report; if guardian flagged severity ≥ "high" findings, qa flips to fail even if functional tests pass.

## Verification

- A fixture PR introducing a hard-coded credential triggers guardian's `secrets_detected` finding and qa fails on it.
- A fixture PR introducing a GPL-licensed dependency under a regulatory pack that forbids it produces an explicit `compliance_check` failure.
- Guardian and QA run concurrently — the workflow file makes both depend on `pull_request: synchronize` independently, not in series.

## Open questions

- Should guardian be allowed to suggest patches, or only flag? Spec proposes **flag-only in MVP2**; auto-patching is a future enhancement once trust is established.
- Cost: Opus + Reflexion is expensive. Should guardian downgrade to Sonnet for trivial PRs? Probably yes — defer to a `ComplexityClassifier` middleware enhancement later.
- Regulatory packs may need versioning (legal compliance changes over time). The `effective_from` frontmatter from Spec 2 already covers this — confirm it's enforced.
