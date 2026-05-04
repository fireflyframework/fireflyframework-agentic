# Spec 2 — Factory Knowledge Base

**Date:** 2026-05-04
**Status:** Draft
**Owner:** Agentic Factory MVP1
**Depends on:** none (independent of Spec 1)
**Required by:** Spec 3 (agents consume the knowledge base via tools)

---

## Context

Every specialized agent in the factory needs a single, queryable surface of reusable knowledge: framework conventions, project archetypes, prompt templates, prior architectural decisions, prior product specifications. The architecture document calls this surface "Canon"; in code it is named `knowledge_base` per the project's functional-naming convention.

`fireflyframework-agentic` already provides every primitive needed: hybrid BM25+vector retrieval (`rag/`), 8 embedder backends (`embeddings/`), 5 vector-store backends (`vectorstores/`), the `BaseTool` interface (`tools/base.py`), and the `PromptRegistry` (`prompts/`). What is missing is the thin layer that wires them together as a knowledge surface — a content directory, an indexer, and four agent-facing tools.

This spec is intentionally minimal: no knowledge graph, no entity extraction, no PRD/ADR memory persistence. Those are MVP2 (Spec 8). What ships in MVP1 is enough to let the four agents (Spec 3) issue typed queries and receive relevant chunks.

## Non-goals

- Knowledge graph or entity/relation extraction → MVP2 Spec 8.
- Persistent storage of generated PRDs and ADRs across runs → MVP2 Spec 8. (MVP1 stores them only as workflow artifacts.)
- A separate `knowledge-base` git repo. The directory ships in `fireflyframework-agentic`. Promotion to its own repo is reversible later without API change.
- Editorial UI / admin console.

## Module layout

```
fireflyframework-agentic/
├── knowledge_base/                      # content (markdown + frontmatter)
│   ├── skills/
│   │   ├── pyfly-conventions.md
│   │   ├── testing-conventions.md
│   │   └── github-workflow-conventions.md
│   ├── archetypes/
│   │   └── pyfly-fastapi-microservice/
│   │       ├── archetype.md             # description + when to use
│   │       └── template/                # files copied verbatim by codegen
│   ├── prompts/
│   │   ├── product-owner.md
│   │   ├── architect.md
│   │   ├── codegen.md
│   │   └── qa.md
│   └── adrs/                            # seed ADRs (mostly empty in MVP1)
└── src/fireflyframework_agentic/factory/
    └── knowledge_base/
        ├── __init__.py                  # public surface
        ├── frontmatter.py               # parses YAML frontmatter, validates schema
        ├── indexer.py                   # walks the directory, chunks, embeds, upserts
        ├── store.py                     # thin wrapper over VectorStoreRegistry
        └── tools/
            ├── __init__.py
            ├── skill_lookup.py
            ├── knowledge_search.py
            ├── archetype_lookup.py
            └── prd_lookup.py            # MVP1: queries the same index; MVP2: structured PRD memory
```

Public API:

```python
from fireflyframework_agentic.factory.knowledge_base import (
    KnowledgeBase,            # facade: load(index_path) -> KnowledgeBase
    skill_lookup,             # BaseTool instances (already bound to a default KB)
    knowledge_search,
    archetype_lookup,
    prd_lookup,
)
```

## Frontmatter schema

Every markdown file in `knowledge_base/` declares minimal metadata:

```yaml
---
name: pyfly-conventions
type: skill | archetype | prompt | adr
version: "1.0"
domain: backend-python | sdlc | testing | ...
effective_from: 2026-05-04
tags: [pyfly, fastapi, conventions]
---
```

Validated by `frontmatter.py` using a Pydantic model `ArtifactMetadata`. The indexer skips files with invalid frontmatter and writes a clear error annotation; CI runs the validator on every PR touching `knowledge_base/` so bad metadata cannot land on main.

## Indexer

`indexer.py` walks `knowledge_base/`, chunks each file using the existing `MarkdownChunker` from `content/`, embeds each chunk with the configured embedder, and upserts into the configured vector store. Each chunk inherits the file's frontmatter as metadata so retrieval can filter by `type`, `domain`, `tags`.

Default embedder: `text-embedding-3-small` (OpenAI) — cheapest acceptable. Configurable via `FACTORY_EMBEDDER` env var.

Default vector store backend in MVP1: **`sqlite-vec`**. Rationale: file-based, single artifact, ships cleanly through GitHub artifacts to downstream agent actions, no infrastructure. Configurable via `FACTORY_VECTOR_BACKEND` env var (`sqlite-vec | chroma | qdrant | pinecone | inmem`).

The indexer is idempotent: it computes a content hash per chunk and skips upserts when the hash already exists in the store. Full re-index is forced by `--rebuild`.

CLI form:

```
python -m fireflyframework_agentic.factory.knowledge_base.indexer \
    --root knowledge_base/ \
    --output $RUNNER_TEMP/factory/kb-index.sqlite \
    [--rebuild]
```

## Tools

Four tools, all `BaseTool` subclasses, all surfaced via the existing `ToolRegistry`. Each takes a `KnowledgeBase` instance at construction and a query string at call time. None of them are LLM-backed — they are deterministic retrieval over the index.

| Tool | Inputs | Behavior | Output |
|---|---|---|---|
| `skill_lookup` | `query: str`, `top_k: int = 3` | Filter by `type=skill`, hybrid BM25+vector retrieval, RRF fusion. | List of `{name, version, content, score}`. |
| `knowledge_search` | `query: str`, `top_k: int = 5`, `domain: str | None = None` | Unfiltered search across all artifacts (or `type` is unconstrained). Optional domain filter. | List of `{name, type, content, score}`. |
| `archetype_lookup` | `query: str`, `top_k: int = 1` | Filter by `type=archetype`. Returns the archetype description + path to its `template/` directory. | `{name, description, template_path}`. |
| `prd_lookup` | `query: str`, `top_k: int = 3` | MVP1: filter by `type=adr` (PRDs not stored persistently yet). MVP2: switches to a structured PRD store. | List of `{name, content, score}`. |

Tools are exposed in two ways:

1. **Programmatic** — agents (Spec 3) declare them in their `tools=[...]` list when constructed.
2. **As `BaseTool` instances in the global `ToolRegistry`** — so any agent registered later, or the MCP server, can use them without code changes.

Caching: each tool is wrapped in `CachedTool` (5-minute TTL keyed on `(tool_name, query, top_k, filters)`). The TTL is short enough that an in-flight knowledge-base update is reflected by the next workflow run.

## How agents consume it inside an Action

The workflow downloads the knowledge-base index artifact built by `factory-knowledge-base-index.yml` (Spec 4) before invoking the agent action. The agent action's container reads `FACTORY_KNOWLEDGE_BASE_INDEX` (path to the SQLite-Vec file) at start, opens it read-only, and passes the resulting `KnowledgeBase` instance to the tools. The index itself is never written to during an agent run.

## Seed content

MVP1 ships these artifacts so the factory can produce something useful on day one:

- **Skills (3):**
  - `skills/pyfly-conventions.md` — module layout, dependency injection, async patterns, error model.
  - `skills/testing-conventions.md` — `test_*.py` naming, plain-function pytest (no classes), fixture conventions.
  - `skills/github-workflow-conventions.md` — workflow naming, secret usage, concurrency keys, OIDC.
- **Archetypes (1):**
  - `archetypes/pyfly-fastapi-microservice/` — `pyproject.toml`, `app/main.py`, `app/api/`, `app/core/config.py`, `tests/test_smoke.py`. Used as a starting point by codegen.
- **Prompts (4):**
  - `prompts/product-owner.md` — system prompt skeleton for the product_owner agent.
  - `prompts/architect.md` — for architect.
  - `prompts/codegen.md` — for codegen, with explicit Reflexion review/critique instructions.
  - `prompts/qa.md` — for qa, with the QAReport JSON schema reference.

All seed content is itself markdown with frontmatter, indexed by the same indexer.

## Verification

- `python -m fireflyframework_agentic.factory.knowledge_base.indexer --root knowledge_base/ --output /tmp/kb.sqlite` produces a non-empty SQLite-Vec file.
- `pytest tests/factory/knowledge_base/` covers: frontmatter validation (good and bad), chunking determinism, idempotent re-index, hybrid retrieval correctness on a fixture corpus, each of the four tools.
- A trivial integration test loads the produced index and asserts that `skill_lookup("how do I structure a pyfly app")` returns `pyfly-conventions` as the top hit.
- A CI lint job validates frontmatter on every PR that touches `knowledge_base/`.

## Open questions

- Should archetype `template/` files be embedded into the index, or kept out of retrieval (only the `archetype.md` is searchable; codegen reads templates by path)? Spec proposes the latter — embedding templates pollutes results. Confirm during implementation.
- For the corpus-search demo (Spec 5), do we ship a second archetype (`pyfly-rag-service`) or have codegen extend `pyfly-fastapi-microservice`? Spec proposes extension to keep MVP1 seed content small.
