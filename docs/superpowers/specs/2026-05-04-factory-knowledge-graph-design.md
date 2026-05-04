# Spec 8 — Knowledge Graph + PRD/ADR Memory

**Date:** 2026-05-04
**Status:** Draft — MVP2 backlog (not approved)
**Owner:** Agentic Factory MVP2
**Depends on:** Spec 2 (knowledge_base) implemented and stable; ideally one full corpus-search demo run in production so we have real PRD/ADR artifacts to learn from.
**Required by:** higher-quality `product_owner` and `architect` decisions; doc Phase-1 parity for the "ADR Memory" capability.

---

## Context

In MVP1 the knowledge base is hybrid BM25 + vector retrieval over markdown. That is enough for skill / archetype / prompt lookup but it is **not** enough for two things the architecture document calls out:

1. **PRD / ADR memory.** When the `product_owner` agent receives a new intent, the most useful prior context is "the PRD for the most similar past intent". With a flat vector index over markdown chunks, the agent retrieves *fragments* of past PRDs, not the whole document with structured metadata. That degrades the elicitation quality.
2. **Cross-document relations.** The `architect` agent benefits from queries like "which existing services depend on the auth module?" or "which archetypes implement the Saga pattern?" — graph queries over typed entities and relations, not vector similarity.

This spec adds two artifacts: a structured PRD/ADR store and a knowledge graph layer over the existing markdown content.

## Non-goals

- A standalone graph database service. Use `networkx` (in-process) or DuckDB property-graph extensions; no Neo4j.
- Real-time graph updates from arbitrary writes. The graph is rebuilt by the same indexer that builds the vector store.
- A formal ontology. Entities and relations are extracted heuristically + LLM-assisted; the schema can evolve.

## Sketch

### Structured PRD/ADR memory

- New module `factory.knowledge_base.memory` with two SQLAlchemy models: `PRDRecord` (intent_hash, intent_text, prd_markdown, spec_yaml, run_id, created_at) and `ADRRecord` (prd_id, adr_markdown, architecture_yaml, archetype, decision_drivers).
- Backed by SQLite (file under `knowledge_base/.memory.db`) for MVP2; pluggable to Postgres in Spec 13.
- New tools: `prd_lookup_structured` and `adr_lookup` replace the MVP1 placeholder `prd_lookup`. Both filter by `intent_hash` exact match first, fall back to vector similarity over `intent_text`.
- The `factory-define.yml` and `factory-design.yml` workflows are extended to write a record after a successful run.

### Knowledge graph

- New module `factory.knowledge_base.graph` with a `KnowledgeGraph` class wrapping a `networkx.MultiDiGraph` persisted as JSON Lines under `knowledge_base/.graph.jsonl`.
- Entities: `Service`, `API`, `Pattern`, `Module`, `Archetype`, `Skill`, `Team`, `Domain`, `Tag`. Relations: `depends-on`, `implements`, `uses`, `extends`, `owned-by`, `documents`.
- Extraction pipeline: a small `entity_extractor` agent (Claude Haiku, single-pass) walks each markdown artifact at index time and emits typed (entity, relation, entity) triples. Heuristics run first; LLM fills the gaps.
- New tool: `graph_traverse(start: str, relation: str, depth: int = 2) -> list[Entity]`.

## Verification

- A test corpus of 5 fake services with documented dependencies → after indexing, `graph_traverse("payments-service", "depends-on", depth=2)` returns the correct closure.
- A test of 10 fake intents → identical-intent detection via `intent_hash` returns the prior PRD record exactly; near-identical (paraphrased) returns it via vector fallback.
- The `architect` agent's behavior on a known intent improves measurably when the graph + PRD memory are available (compared via the lab/evaluator harness).

## Open questions

- LLM-assisted extraction is non-deterministic. Do we lock seed + temperature to make the graph reproducible across runs, or accept drift and rely on `effective_from` stamps? Spec proposes seed-locking for MVP2 and revisiting after a quarter of usage.
- The graph and the vector store can drift. The indexer must rebuild both atomically; the existing `knowledge-base-index` action becomes a multi-output action.
- For SaaS (Spec 13) the graph likely needs to move to Postgres + Apache AGE or DuckDB property graph. Defer that decision; SQLite/JSONL is fine for single-tenant.
