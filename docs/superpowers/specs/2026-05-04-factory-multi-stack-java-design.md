# Spec 12 — Multi-Stack Support: Java / `fireflyframework`

**Date:** 2026-05-04
**Status:** Draft — MVP2 backlog (not approved)
**Owner:** Agentic Factory MVP2
**Depends on:** Specs 1–4 stable; the Java `fireflyframework` having a usable archetype + skill set.
**Required by:** doc Phase-1 parity; reaching customers whose stack is JVM, not Python.

---

## Context

MVP1 generates pyfly services. The architecture document explicitly lists four stacks (Java, Python, frontend, infrastructure) and treats stack-pluggability as a core capability. This spec adds the Java stack — Spring Boot 3 + Java 21 on `fireflyframework` — without rewriting the agents.

The mechanism is dispatch at the `codegen` agent's stack-selection step. The product_owner / architect / qa agents are stack-agnostic: a PRD is a PRD; an ADR is an ADR. Only codegen and (transitively) the archetypes + skills need stack-specific implementations.

## Non-goals

- Frontend stack. That depends on `fireflyframework-front` reaching v1; MVP2 is JVM-only.
- Polyglot single services (Java backend + Python ML sidecar). One stack per generated service.
- Re-implementing `fireflyframework`. The factory consumes its conventions; building it is out of scope.

## Sketch

- `architect` agent's output `architecture.yaml` gains a `stack: pyfly | fireflyframework` discriminator (today it's hardcoded `pyfly`).
- `codegen` agent gains two sub-agents under `factory/agents/codegen/`: `python_codegen.py` (existing) and `java_codegen.py` (new). The parent `codegen` dispatches by stack.
- `knowledge_base/skills/` adds:
  - `firefly-conventions.md` (5-module Maven, Spring Boot 3 idioms, R2DBC patterns).
  - `cqrs-saga-conventions.md`.
  - `eda-conventions.md`.
- `knowledge_base/archetypes/` adds `firefly-5-module-maven/` with a working `pom.xml` parent + 5 module skeletons.
- The base Dockerfile (Spec 1) gains `openjdk-21-jdk` + `maven` for Java codegen runs. Image size grows; cost-amortize over an actions/cache step.
- The qa agent's `parse_test_results` tool already handles JUnit XML — no change needed.
- Builder + deployer (Spec 10) need a build profile per stack: Maven for Java, uv/pip for Python.

## Verification

- A demo intent ("microservice that exposes /balances endpoints with R2DBC and Saga compensation") routed to the Java stack produces a working Spring Boot project with all five Maven modules, passing `mvn verify`.
- The product_owner / architect prompts are unchanged between Java and Python runs (verified by snapshot tests of system prompts).
- A regression test runs the corpus-search demo on Python after this PR and asserts no regression.

## Open questions

- Build cache: Maven downloads a lot. Self-hosted runner with persistent local repo? Or `actions/cache` keyed on `pom.xml` hash? Spec proposes the latter for hosted runners; self-hosted is a deployment-time choice.
- The Java archetype is a 5-module Maven project — opinionated. Does it match what the `fireflyframework` team actually ships? Cross-check before implementation.
- Spec 9's guardian regulatory packs are language-agnostic in design but test-checked only against pyfly today. Add Java fixtures during this work.
