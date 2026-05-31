# Vector Stores Guide

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The Vector Stores module provides pluggable storage and retrieval backends for
embedding vectors. It ships **seven** backends -- in-memory, ChromaDB, Pinecone,
Qdrant, PostgreSQL/pgvector, and sqlite-vec -- behind a unified API for upserting,
searching, and deleting documents, plus a tenant/workspace-scoped wrapper that
makes any backend multi-tenant.

---

## Architecture

```mermaid
graph TD
    VP[VectorStoreProtocol] --> BVS[BaseVectorStore]
    BVS --> IM[InMemoryVectorStore]
    BVS --> CH[ChromaVectorStore]
    BVS --> PC[PineconeVectorStore]
    BVS --> QD[QdrantVectorStore]
    BVS --> PG[PgVectorVectorStore]
    BVS --> SV[SqliteVecVectorStore]
    REG[VectorStoreRegistry] --> VP
    BVS --> |auto-embed| EMB[EmbeddingProtocol]
    TS[TenantScopedVectorStore] --> |wraps| VP
```

- **VectorStoreProtocol** -- Duck-typed protocol with `upsert()`, `search()`, `search_text()`, `delete()`.
- **BaseVectorStore** -- Abstract base providing auto-embedding, `search_text` convenience, and error wrapping.
- **Concrete Backends** -- Backend-specific implementations that override `_upsert()`, `_search()`, `_delete()`.
- **VectorStoreRegistry** -- Named registry for managing multiple store instances.
- **TenantScopedVectorStore** -- Wraps any backend with mandatory `(tenant_id, workspace_id)` isolation.

---

## Quick Start

```python
from fireflyframework_agentic.embeddings.providers import OpenAIEmbedder
from fireflyframework_agentic.vectorstores import InMemoryVectorStore, VectorDocument

# Create a store with auto-embedding
embedder = OpenAIEmbedder()
store = InMemoryVectorStore(embedder=embedder)

# Upsert documents (auto-embeds if embedding is None)
docs = [
    VectorDocument(id="1", text="Python is great for AI"),
    VectorDocument(id="2", text="JavaScript runs in browsers"),
    VectorDocument(id="3", text="Rust is fast and safe"),
]
await store.upsert(docs)

# Search by text (embeds the query, then searches)
results = await store.search_text("programming languages for machine learning", top_k=2)
for r in results:
    print(f"{r.document.text} (score: {r.score:.3f})")
```

---

## Backends

### In-Memory

Zero-dependency, brute-force cosine similarity. Ideal for development and testing.

```python
from fireflyframework_agentic.vectorstores import InMemoryVectorStore

store = InMemoryVectorStore(embedder=my_embedder)
```

No extra install required.

### ChromaDB

```python
from fireflyframework_agentic.vectorstores import ChromaVectorStore

# Ephemeral (in-process)
store = ChromaVectorStore(collection_name="my_docs", embedder=my_embedder)

# With a persistent/remote client
import chromadb
client = chromadb.HttpClient(host="localhost", port=8000)
store = ChromaVectorStore(collection_name="my_docs", client=client, embedder=my_embedder)
```

Install: `pip install fireflyframework-agentic[vectorstores-chroma]`

### Pinecone

```python
from fireflyframework_agentic.vectorstores import PineconeVectorStore

store = PineconeVectorStore(
    index_name="my-index",
    api_key="...",           # falls back to PINECONE_API_KEY env var
    embedder=my_embedder,
)
```

Install: `pip install fireflyframework-agentic[vectorstores-pinecone]`

### Qdrant

```python
from fireflyframework_agentic.vectorstores import QdrantVectorStore

store = QdrantVectorStore(
    collection_name="my_collection",
    url="http://localhost:6333",    # default
    api_key="...",                  # for Qdrant Cloud
    vector_size=1536,               # must match your embedder dimensions
    embedder=my_embedder,
)
```

Install: `pip install fireflyframework-agentic[vectorstores-qdrant]`

### PostgreSQL / pgvector

A PostgreSQL-backed store using the `pgvector` extension, so production
deployments can co-locate vectors with an existing Postgres instance instead of
operating a separate vector database. ANN search uses an HNSW index over cosine
distance.

```python
from fireflyframework_agentic.vectorstores import PgVectorVectorStore

store = PgVectorVectorStore(
    "postgresql://user:pass@host/db",  # connection string (first positional)
    dimension=1536,                    # must match your embedder; sizes the vector column
    table_name="vector_documents",     # default
    hnsw_m=16,                         # HNSW build params
    hnsw_ef_construction=64,
    hnsw_ef_search=200,                # set per query for recall/latency tuning
    pool_min_size=1,
    pool_max_size=10,
    embedder=my_embedder,
)

await store.initialise()  # opens the asyncpg pool and creates the table/indexes (idempotent)
await store.upsert(docs)
results = await store.search_text("query")
await store.close()       # closes the connection pool
```

The store owns one table (created on first use) and supports all seven
`SearchFilter` operators on metadata. `_prepare_session(conn, *, namespace)` is an
overridable per-transaction hook (default no-op) for callers that need
`SET LOCAL` session setup -- e.g. Postgres Row-Level Security GUCs. Connection
and pool failures raise `VectorStoreConnectionError`.

Install: `pip install fireflyframework-agentic[vectorstores-pgvector]`

### sqlite-vec

A sqlite-vec (`vec0` virtual table) backend that co-resides inside an existing
SQLite file via the `storage` module's `DatabaseStore`. Useful for embedded,
file-based deployments.

```python
from fireflyframework_agentic.vectorstores import SqliteVecVectorStore

# From a path (wrapped in a DatabaseStore/LocalBackend automatically)
store = SqliteVecVectorStore("vectors.db", dimension=1536, embedder=my_embedder)

# Or from a pre-built DatabaseStore (to share a SQLite file with other data)
from fireflyframework_agentic.storage import DatabaseStore, LocalBackend
db = DatabaseStore(LocalBackend("app.db"), store_id="local:app.db")
store = SqliteVecVectorStore(db, dimension=1536, table_name="vec_chunks", embedder=my_embedder)

await store.upsert(docs)
results = await store.search_text("query")
await store.close()
```

`upsert()` and `delete()` accept an optional keyword-only `session: WriteSession`
to enlist the operation in a coordinated `DatabaseStore` write batch. `search()`
returns results carrying only the document `id` and `score` (text/metadata are not
stored by this backend).

Install: `pip install fireflyframework-agentic[vectorstores-sqlite-vec]`

---

## Core Types

### VectorDocument

```python
from fireflyframework_agentic.vectorstores import VectorDocument

doc = VectorDocument(
    id="unique-id",              # required
    text="The document text",    # required
    embedding=[0.1, 0.2, ...],  # optional (auto-embedded if None)
    metadata={"source": "web"}, # optional key-value metadata
    namespace="default",        # optional namespace scoping
)
```

### SearchResult

```python
from fireflyframework_agentic.vectorstores import SearchResult

# Returned by search() and search_text()
result.document   # VectorDocument
result.score      # float (0.0 to 1.0, higher = more similar)
```

### SearchFilter

```python
from fireflyframework_agentic.vectorstores import SearchFilter

# Supported operators: eq, ne, gt, lt, gte, lte, in
filters = [
    SearchFilter(field="source", operator="eq", value="web"),
    SearchFilter(field="year", operator="gte", value=2024),
]
results = await store.search(query_embedding, filters=filters)
```

Note: Filter operator support varies by backend. `eq` is universally supported.
`InMemoryVectorStore` and `PgVectorVectorStore` support all 7 operators;
`PgVectorVectorStore` binds both the metadata key and value as parameters
(no SQL interpolation). Other external backends support a narrower subset.

---

## Namespaces

All operations accept a `namespace` parameter to isolate documents:

```python
await store.upsert(docs, namespace="project-a")
await store.upsert(docs, namespace="project-b")

# Search only within a namespace
results = await store.search_text("query", namespace="project-a")

# Delete only within a namespace
await store.delete(["id-1"], namespace="project-a")
```

---

## Auto-Embedding

When a `BaseVectorStore` has an embedder configured, documents without embeddings
are automatically embedded during `upsert()`:

```python
store = InMemoryVectorStore(embedder=my_embedder)

# These docs have no embedding -- they'll be auto-embedded
docs = [VectorDocument(id="1", text="Hello")]
await store.upsert(docs)  # embedder.embed() called automatically
```

The `search_text()` method embeds the query string before searching:

```python
# Equivalent to: embedding = await embedder.embed_one(query); store.search(embedding)
results = await store.search_text("my query")
```

---

## Registry

```python
from fireflyframework_agentic.vectorstores import VectorStoreRegistry, InMemoryVectorStore

registry = VectorStoreRegistry()
registry.register("memory", InMemoryVectorStore(embedder=my_embedder))

store = registry.get("memory")        # raises KeyError if the name is not registered
await store.upsert(docs)

registry.list_names()                 # -> ["memory"]
registry.unregister("memory")         # remove (no-op if absent)
```

---

## Tenant/Workspace Scoping

The `VectorStoreProtocol` is single-namespace: a store partitions documents by one
opaque `namespace` string. Multi-tenant applications need stronger guarantees --
every read and write must be confined to a `(tenant_id, workspace_id)` scope, and
forgetting the scope must fail loudly rather than silently leak across tenants.

`TenantScopedVectorStore` wraps **any** `VectorStoreProtocol` backend and folds the
scope into the canonical `"t/<tenant_id>/w/<workspace_id>"` namespace, so a single
wrapper makes every backend multi-tenant.

```python
from fireflyframework_agentic.vectorstores import (
    InMemoryVectorStore,
    TenantScopedVectorStore,
)

inner = InMemoryVectorStore(embedder=my_embedder)
store = TenantScopedVectorStore(inner)  # stamp_metadata=True by default

# tenant_id and workspace_id are required keyword-only arguments on every op
await store.upsert(docs, tenant_id="acme", workspace_id="prod")
results = await store.search(query_embedding, top_k=5, tenant_id="acme", workspace_id="prod")
await store.delete(["id-1"], tenant_id="acme", workspace_id="prod")

await store.initialise()  # passes through to the wrapped store's lifecycle hook
await store.close()
```

On `upsert`, each document is copied (never mutating the caller's objects), its
namespace is set to the scope, and -- when `stamp_metadata=True` (default) -- the
scope is also stamped onto `metadata["tenant_id"]` / `metadata["workspace_id"]` as
defense-in-depth. A caller that forgets `tenant_id`/`workspace_id` fails with
`TypeError`, so isolation can never be lost silently.

The namespace codec is exported directly:

```python
from fireflyframework_agentic.vectorstores import scope_namespace, parse_scope_namespace

scope_namespace("acme", "prod")          # -> "t/acme/w/prod"
parse_scope_namespace("t/acme/w/prod")   # -> ("acme", "prod")
```

Both raise `ValueError` if a component is empty or contains `/`. `ScopedVectorStore`
is the fail-loud `Protocol` that `TenantScopedVectorStore` satisfies.

---

## Configuration

Global defaults via environment variables (prefix `FIREFLY_AGENTIC_`):

| Setting | Env Variable | Default |
|---------|-------------|---------|
| `default_vector_store` | `FIREFLY_AGENTIC_DEFAULT_VECTOR_STORE` | `memory` |
| `vector_store_namespace` | `FIREFLY_AGENTIC_VECTOR_STORE_NAMESPACE` | `default` |

---

## Pipeline Integration (RAG)

Build retrieval-augmented generation workflows by wiring a `RetrievalStep` into a
pipeline via `PipelineBuilder` / `PipelineEngine`:

```python
from fireflyframework_agentic.pipeline import PipelineBuilder, RetrievalStep

# RetrievalStep embeds the query text (via embedder) and searches the store
retrieval = RetrievalStep(my_store, embedder=my_embedder, top_k=5)

engine = (
    PipelineBuilder("rag")
    .add_node("retrieve", retrieval)
    # .add_node("answer", agent)  # e.g. an AgentStep that consumes the results
    # .chain("retrieve", "answer")
    .build()
)

result = await engine.run(inputs="What is RAG?")
```

`RetrievalStep(store, *, embedder=None, top_k=5, input_key="input")` reads the
query from `inputs[input_key]` (falling back to the pipeline's initial inputs). It
embeds the query with `embedder.embed_one(...)` then calls `store.search(...)`; if
no embedder is supplied, the input is assumed to already be an embedding.

---

## Custom Backend

Subclass `BaseVectorStore` and implement three methods:

```python
from fireflyframework_agentic.vectorstores.base import BaseVectorStore
from fireflyframework_agentic.vectorstores.types import SearchFilter, SearchResult, VectorDocument

class MyVectorStore(BaseVectorStore):
    async def _upsert(self, documents: list[VectorDocument], namespace: str) -> None:
        # Store documents (embeddings are guaranteed to be present)
        ...

    async def _search(
        self,
        query_embedding: list[float],
        top_k: int,
        namespace: str,
        filters: list[SearchFilter] | None,
    ) -> list[SearchResult]:
        # Return top_k most similar documents
        ...

    async def _delete(self, ids: list[str], namespace: str) -> None:
        # Remove documents by ID within the namespace
        ...
```

The base class fills in the contract for you: all public ops default to
`namespace="default"`; `search()`/`search_text()` default to `top_k=5`; `upsert()`
auto-embeds documents lacking an embedding via `embedder.embed(texts)` (batch);
`search_text()` uses `embedder.embed_one(query)` and raises `VectorStoreError` if no
embedder is configured. Every public method wraps any non-`VectorStoreError`
exception from your `_upsert`/`_search`/`_delete` in a `VectorStoreError`.

See also: [Embeddings Guide](embeddings.md) for embedding provider setup.
