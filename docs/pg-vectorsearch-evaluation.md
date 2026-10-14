# pg_vectorsearch adoption evaluation

Copyright 2026 Firefly Software Foundation. SPDX-License-Identifier: Apache-2.0.

The October 14, 2026 evaluation did not qualify pg_vectorsearch for adoption in
Agentic, flycanon, or flyquery. Pgvector/HNSW remains the supported PostgreSQL
backend. Agentic 26.10.0 fixes namespace writes without enabling PRISM or requiring
PostgreSQL 18. No PRISM configuration option, automatic extension installation,
index replacement, or schema migration was added.

## Release and compatibility

The evaluated [pg_vectorsearch v0.1.0 release](https://github.com/timescale/pg_vectorsearch/releases/tag/v0.1.0)
is commit `36b75d1cb56c12a380d600ef27217d88c9f419ec`. Its
[changelog](https://github.com/timescale/pg_vectorsearch/blob/36b75d1cb56c12a380d600ef27217d88c9f419ec/CHANGELOG.md)
describes its quality as alpha despite the final release label. It requires
PostgreSQL 18 or later and uses the PostgreSQL License. It can index existing
pgvector columns with its own operator classes, but the native probes rejected
expression indexes, unlogged tables, and `halfvec(3072)` indexes. The reported
maximum was 1,968 dimensions.

| Product | Existing storage contract | Decision |
| --- | --- | --- |
| Agentic | Fixed-width pgvector column, HNSW bootstrap, namespace and metadata filters | Storage is compatible at supported widths; filtered recall and index lifecycle need further qualification. |
| flycanon | Mixed widths, per-set partial expression indexes, wide halfvec embeddings | Expression indexes and widths above 1,968 are incompatible. A materialized projection would require a separate migration and synchronization design. |
| flyquery | Plain `vector(1536)` columns, dataset joins and RLS; computed ranking for examples | Column shape fits, but filtered retrieval and actual query plans are unqualified. An index change alone cannot convert computed ranking into ANN traversal. |

The audited source revisions were Agentic `8e56361`, flycanon `2d7dca1`, and
flyquery `be68d344`. The inspected flycanon/flyquery development and integration
stacks used PG16. Their production database upgrades were outside this evaluation.

## Measured results

The isolated runtime used PostgreSQL 18.6, pgvector 0.8.7, and pg_vectorsearch
0.1.0 on macOS arm64. PRISM was compiled in release mode with native NEON and
Apple Accelerate. PostgreSQL used 128 MiB shared buffers, 64 MiB work memory,
256 MiB maintenance memory, and no parallel query or maintenance workers for
the measured operations.

Two synthetic corpora used seed `20261014`: 30,000 vectors at width 384 and
12,000 at width 1,536. Normalized vectors formed 64 clusters across 16 tenants and
four projects. Exact cosine top-10 results came from an unindexed copy of each
table. Each cohort contained 48 distinct queries repeated three times. Opposite
tenant/project scopes deliberately selected rows far from the query's nearest
global clusters; their failure rates are not estimates of production traffic.

| Corpus | Setting | Global recall@10 | Global p50 latency | Incomplete opposite tenant/project queries |
| --- | --- | ---: | ---: | ---: |
| 30k × 384 | HNSW ef 40 | 99.17% | 0.347 ms | 144/144 |
| 30k × 384 | HNSW strict iterative ef 160 | 100% | 0.395 ms | 0/144 |
| 30k × 384 | PRISM auto | 93.75% | 0.168 ms | 111/144 |
| 30k × 384 | PRISM nprobe 256 | 94.79% | 0.660 ms | 102/144 |
| 12k × 1536 | HNSW ef 40 | 99.79% | 0.252 ms | 144/144 |
| 12k × 1536 | HNSW strict iterative ef 160 | 100% | 0.426 ms | 0/144 |
| 12k × 1536 | PRISM auto | 87.50% | 0.372 ms | 114/144 |
| 12k × 1536 | PRISM nprobe 256 | 95.42% | 1.669 ms | 48/144 |

Timings forced each ANN index and include the local client round trip. In the
1,536-dimensional run, 40 of 48 sampled natural plans chose a sequential scan
and sort instead. These timings do not describe default application performance.
The lower PRISM latency at width 384 also has lower recall; no global speedup at
matched recall was established. HNSW iterative scans filled the filtered result
slots, but opposite tenant/project recall was only 38.33% and 58.75% in the two
loaded corpora. Result count alone does not establish retrieval quality.

PRISM index sizes were 5.64 MB versus HNSW's 61.45 MB at width 384, and 5.19 MB
versus 98.31 MB at width 1,536 (decimal MB). Single build times were 0.663 versus
3.971 seconds and 0.518 versus 3.564 seconds. Full vectors remain in the heap.
Build order and background system activity were not controlled across repeated
independent builds. Post-query RSS includes shared mappings and does not establish
peak private memory savings.

Each corpus then received 5% inserts, 5% vector updates, and 5% deletes, followed
by VACUUM ANALYZE. Under simplified FORCE RLS policies and a restricted reader,
PRISM auto underfilled 37/48 and 38/48 opposite tenant/project queries, with
16.67% and 13.96% recall. No wrong-scope rows were observed. The test did not
reproduce actual service middleware, pooling, grants, or dataset joins.

One immediate shutdown and WAL recovery per corpus preserved committed ID/vector
fingerprints and six sampled query vectors across four cohorts per configuration.
Uncommitted inserts, deletes, and embedding updates rolled back. This does not
qualify backup/restore, failover, extension upgrades, or interrupted maintenance.
Independent review checked dataset parity, unique churn vectors, recorded plans,
scope results, and recovery comparisons.

## Conditions for a future pilot

Reconsider PRISM only after it preserves supported schemas, embedding widths,
IDs, scores, authorization, and source/citation contracts. Installation and index
construction must be operator-owned; PostgreSQL can choose either index when two
exist, so a configuration flag alone cannot guarantee routing.

A future pilot should achieve at least 95% mean recall@10 in every representative
filtered cohort, return `min(10, eligible rows)` on every query, and expose zero
rows outside the authorized scope. Compare latency at recall within one percentage
point. Require either 20% lower p95 latency or 30% lower measured peak private
memory without more than 20% p95 latency regression, using representative scale
and concurrency. These are proposed acceptance thresholds, not achieved results.

Qualify concurrent changes, pooled scope reuse, maintenance, recovery, upgrades,
and reversal separately. Keep existing indexes and data intact during evaluation.
For the supported backend's current settings and namespace behavior, see
[vector stores](vectorstores.md) and the [26.10.0 upgrade notes](migration.md#postgresql-vector-store-safety-in-26100).
