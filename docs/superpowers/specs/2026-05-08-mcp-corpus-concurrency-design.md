# Design: corpus_rag MCP — agent caching, write coordination, ingest separation

**Date:** 2026-05-08
**Branch:** `fix/mcp-demo-findings`
**Status:** Draft (pending user review)

## Goal

Make the `corpus_rag` MCP server safe and predictable when multiple tool
calls run in parallel against the same `corpus_id`, and remove the
duplicate-representation footgun where spreadsheets get ingested both as
text chunks and as SQL tables.

This spec is the second commit on top of the existing folder-filter fix
(`fix(rag): filter folder walks to tabular files for structured ingest`).
It addresses three concrete defects surfaced live during the Claude
Desktop demo on 2026-05-08:

1. Each MCP tool call instantiated a fresh `CorpusAgent` (via
   `_agent_for`) which built its own `LocalBackend`. Two concurrent calls
   meant two `asyncio.Lock` instances and a filesystem sentinel race.
2. `_sync_ingest_table` opened a raw `sqlite3.connect(db_path)` connection
   that bypassed `DatabaseStore.for_write()` entirely — no shared lock,
   no busy_timeout. With (1), two parallel tool calls produced transient
   "database disk image is malformed" errors and partial writes.
3. `ingest_corpus_filesystem` happily routed `.csv` / `.xls` / `.xlsx`
   files through markitdown as text chunks even though
   `ingest_corpus_structured` already turns them into SQL tables. Mixed
   drop folders ended up with the same data represented twice.

## Non-goals

- **No new MCP tool to delete or reset a corpus.** That belongs in a
  separate change.
- **No multi-process / multi-server coordination.** A single MCP server
  process owns its corpora; cross-process locking via the existing
  filesystem sentinel is sufficient and unchanged.
- **No row-level concurrency for `_sync_ingest_table`.** Writers serialise
  on the per-corpus write lock; concurrent inserts into the same SQLite
  file are not a goal.
- **No agent-pool eviction.** Cached `CorpusAgent` instances live for the
  MCP server process lifetime; we don't refcount or LRU-evict. Server
  shutdown closes them.
- **No public-API redesign.** Tool names, parameters, and return shapes
  stay identical.

## Architecture

```
┌──────────── MCP server process (FastMCP, single asyncio loop) ────────────┐
│                                                                            │
│   ┌─ corpus_rag.py module state ────────────────────────────────────┐    │
│   │   _AGENT_CACHE: dict[str, CorpusAgent]                          │    │
│   │   _WRITE_LOCKS: dict[str, asyncio.Lock]   (one per corpus_id)   │    │
│   └─────────────────────────────────────────────────────────────────┘    │
│                                                                            │
│   tool: ingest_corpus_filesystem(corpus_id, root_path)                    │
│       async with _write_lock_for(corpus_id):                              │
│           agent = _agent_for(corpus_id)   # cached                        │
│           await agent.ingest_folder(...)                                  │
│                                                                            │
│   tool: ingest_corpus_structured(corpus_id, path, schema?)                │
│       async with _write_lock_for(corpus_id):                              │
│           agent = _agent_for(corpus_id)   # same instance                 │
│           await agent.ingest_folder(mode='structured', ...)               │
│             └─> ingest_structured(path, agent._db_store, schema)          │
│                   async with db_store.for_write() as session:             │
│                       _sync_ingest_table(session.path, ...)               │
│                         # raw sqlite3 with busy_timeout=30                │
│                                                                            │
│   tool: corpus_query / corpus_retrieve  (READ — no write lock)            │
│       agent = _agent_for(corpus_id)   # same cached instance              │
│       await agent.query(...)                                              │
└────────────────────────────────────────────────────────────────────────────┘
```

Three coordination primitives, each with one job:

1. **`_AGENT_CACHE` (module-level dict).** One `CorpusAgent` per
   `corpus_id`, lazily created. Sharing the agent means sharing its
   `DatabaseStore` / `LocalBackend` / `SqliteCorpus` connection. This is
   the single most important fix — once everyone in the process agrees
   on which `LocalBackend` instance owns the file, the `asyncio.Lock`
   inside that backend actually does its job.
2. **`_WRITE_LOCKS[corpus_id]` (module-level asyncio.Lock).** Tool-level
   serialisation for writes against one corpus. Belt-and-braces: even if
   a future code path opens its own raw connection bypassing
   `for_write`, it still has to wait for whoever holds the tool-level
   lock. Reads don't take it — `corpus_query` and `corpus_retrieve` can
   run alongside ingest.
3. **`DatabaseStore.for_write()`.** Already exists and works. Now
   `ingest_structured` actually goes through it instead of opening a
   raw connection.

## Components

### 1. Agent registry in `corpus_rag.py`

Replace `_agent_for(corpus_id)` with a registry that returns a cached
agent and a per-corpus write lock helper:

```python
# src/fireflyframework_agentic/tools/builtins/corpus_rag.py

_AGENT_CACHE: dict[str, CorpusAgent] = {}
_WRITE_LOCKS: dict[str, asyncio.Lock] = {}
_CACHE_LOCK = asyncio.Lock()  # protects the dicts themselves


async def _agent_for(corpus_id: str) -> CorpusAgent:
    """Return a process-wide CorpusAgent for *corpus_id*, creating one on
    first use. Subsequent calls return the same instance — sharing the
    DatabaseStore/LocalBackend so the asyncio.Lock inside the backend
    actually serialises writes."""
    async with _CACHE_LOCK:
        if corpus_id not in _AGENT_CACHE:
            _AGENT_CACHE[corpus_id] = CorpusAgent(
                root=_corpus_root() / corpus_id,
                embed_model=os.environ["EMBEDDING_MODEL"],
                expansion_model=os.environ["EXPANSION_MODEL"],
                answer_model=os.environ["ANSWER_MODEL"],
                rerank_model=os.environ["RERANK_MODEL"],
            )
        return _AGENT_CACHE[corpus_id]


def _write_lock_for(corpus_id: str) -> asyncio.Lock:
    """Return the per-corpus write lock, creating one on first use."""
    if corpus_id not in _WRITE_LOCKS:
        _WRITE_LOCKS[corpus_id] = asyncio.Lock()
    return _WRITE_LOCKS[corpus_id]


async def _shutdown_agents() -> None:
    """Close every cached agent. Call on MCP server shutdown."""
    for agent in list(_AGENT_CACHE.values()):
        with contextlib.suppress(Exception):
            await agent.close()
    _AGENT_CACHE.clear()
    _WRITE_LOCKS.clear()
```

The `async with _agent_for(corpus_id) as agent` pattern at every tool
call site changes to a plain `agent = await _agent_for(corpus_id)`. Tool
implementations that write also wrap the body in
`async with _write_lock_for(corpus_id):`.

`_CACHE_LOCK` is held across the `CorpusAgent` constructor, but
construction is sync, fast, and does no I/O (it builds embedder /
loader / chunker objects in-memory; the SQLite file isn't touched until
the first `_ensure_corpus_ready`), so this can't deadlock with the
per-corpus write lock and serialisation cost is negligible.

### 2. Server lifespan hook

`examples/corpus_search/mcp_server.py` should arrange for
`_shutdown_agents` to run when the server stops. The exact mechanism
depends on FastMCP's lifecycle API — to be confirmed in the
implementation plan by reading
`fireflyframework_agentic/exposure/mcp/server.py` and the FastMCP docs.
Acceptable fallbacks, in order of preference:

1. FastMCP / Starlette `lifespan` async context manager that yields the
   running app and runs `_shutdown_agents()` on exit.
2. A `signal.signal(SIGTERM, ...)` handler that schedules
   `_shutdown_agents()` on the running loop.
3. `atexit.register` with a synchronous wrapper that calls
   `asyncio.run(_shutdown_agents())` if no loop is running.

In the worst case where none of these are wired up, the cached agents
leak open SQLite connections at process exit — harmless for a
short-lived MCP subprocess but worth fixing properly.

### 3. Structured pipeline goes through `for_write()`

```python
# src/fireflyframework_agentic/rag/ingest/structured_pipeline.py

async def ingest_structured(
    path: Path,
    db_store: DatabaseStore,
    schema: TargetSchema,
) -> dict[str, Any]:
    rows_by_table = _load_rows(path, schema)
    results: dict[str, Any] = {}
    async with db_store.for_write() as session:
        loop = asyncio.get_running_loop()
        for table_spec in _order_tables_by_fk(schema.tables):
            rows = rows_by_table.get(table_spec.name)
            if rows is None:
                results[table_spec.name] = {
                    "status": "failed",
                    "inserted": 0,
                    "errors": [f"missing columns for table {table_spec.name!r}"],
                }
                continue
            results[table_spec.name] = await loop.run_in_executor(
                None, _sync_ingest_table, session.path, table_spec, rows
            )
    return results
```

`_sync_ingest_table` keeps its synchronous body but tightens its
`sqlite3.connect`:

```python
conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
conn.execute("PRAGMA busy_timeout = 30000")
```

`isolation_level=None` matches the rest of the corpus code (deferred
transactions handled explicitly via `commit`/`rollback`); the explicit
`busy_timeout` PRAGMA defends against the rare case where the
constructor `timeout=` arg is overridden by a sidecar tool.

The agent-side caller updates from
`await ingest_structured(path, self.root / "corpus.sqlite", schema)`
to `await ingest_structured(path, self._db_store, schema)`.

### 4. Filesystem ingest skips tabular files

`ingest_corpus_filesystem` should leave CSV / XLSX to the structured
path. Two ways to wire this:

- (a) Filter inside `LocalFolderSource` via a new `exclude` callable on
  `LocalFolderSourceConfig`.
- (b) Filter in `CorpusAgent.ingest_folder` before constructing the
  source.

Going with (a). `LocalFolderSourceConfig` already has a `glob` matcher;
adding `exclude_predicate: Callable[[Path], bool] | None` is the
minimal extension and benefits any other caller of the source. The MCP
filesystem ingest passes
`exclude_predicate=is_tabular_file` (re-exported from the structured
registry). Skipped files are reported in the existing `summary.skipped`
counter so users can see why a CSV/XLSX was bypassed.

The `CorpusAgent.ingest_folder` (default `mode="unstructured"`) wires
this through automatically. Direct CLI users who don't want the skip
can construct a `LocalFolderSource` without `exclude_predicate`.

## Data flow under contention

Two parallel MCP tool calls on the same corpus, after this change:

```
t=0   Tool A (ingest_corpus_structured) takes _WRITE_LOCKS[id]      [PASS]
t=0+ε Tool B (ingest_corpus_filesystem) tries _WRITE_LOCKS[id]      [BLOCKED]
t=0+δ Tool A: agent.ingest_folder(mode='structured')
        → ingest_structured(... db_store ...)
        → async with db_store.for_write():     # acquires asyncio.Lock + sentinel
              _sync_ingest_table(...)          # raw sqlite with busy_timeout
        → for_write releases
        → tool releases _WRITE_LOCKS[id]
t=T   Tool B unblocks, runs to completion against the same agent.
```

Two parallel calls on **different** corpora don't interact — each has
its own `_WRITE_LOCKS[id]` and its own cached agent / DatabaseStore.

A read tool (`corpus_query` / `corpus_retrieve`) running concurrently
with a write only contends inside SQLite — WAL mode lets readers see a
consistent snapshot during a writer's transaction.

## Error handling

- **Lock acquisition timeout.** `DatabaseStore.for_write` already raises
  `StorageLeaseError` after `lock_timeout=30s`. The new tool-layer lock
  is a plain `asyncio.Lock` with no built-in timeout; we don't add one
  because contention here is bounded by the inner `for_write` timeout
  and adding a second timeout would just confuse the failure mode.
- **Cache poisoning.** If `CorpusAgent.__init__` raises, we never insert
  into `_AGENT_CACHE`, so the next call retries cleanly.
- **Tool-level write lock + read tool.** Reads do not take the
  tool-level lock; only the per-call `agent.query`/`retrieve` paths
  apply, which use the corpus's existing `_lock`.

## Testing

- **Unit (`tests/unit/corpus_search/test_agent_registry.py`):**
  - `test_agent_for_returns_cached_instance` — same id ⇒ same object.
  - `test_agent_for_different_ids_are_isolated` — different objects with
    different roots.
  - `test_write_lock_serialises_concurrent_writers` — two coroutines
    enter `_write_lock_for("x")`; second only proceeds after the first
    releases. Validate via observable side-effects (e.g. an ordered
    list of entry/exit timestamps).
  - `test_write_lock_is_per_corpus` — concurrent writers on different
    `corpus_id`s don't block each other.
- **Unit (`tests/unit/rag/ingest/test_structured_pipeline.py`):**
  - `test_ingest_structured_acquires_for_write` — patch `db_store.for_write`
    to confirm it's entered before `_sync_ingest_table` is called.
  - `test_sync_ingest_table_sets_busy_timeout` — open the connection,
    assert `PRAGMA busy_timeout` returns 30000.
- **Unit (`tests/unit/content/sources/test_local_folder.py`):**
  - `test_exclude_predicate_filters_files` — predicate returning True
    for a path means the source skips that file.
- **Integration (`tests/integration/test_corpus_concurrency.py`,
  marker `integration`):**
  - `test_parallel_ingest_same_corpus_is_safe` — fire `ingest_one` for
    a markdown file and `ingest_one(mode="structured")` for a CSV
    concurrently; assert both succeed and the SQLite file passes
    `PRAGMA integrity_check`.
- **Regression for finding #2:** the same integration test is the
  regression. Pre-fix it would non-deterministically hit "malformed
  image" or empty `ingestions` table; post-fix it always lands cleanly.

Manual verification (after merge):
1. `rm -rf kg/real-data`.
2. From Claude Desktop, ask Claude to call `ingest_corpus_filesystem`
   AND `ingest_corpus_structured` *in parallel* on the same drop folder.
3. Both calls return success. `chunks` table non-empty (PPTXs only,
   XLSXs skipped). Structured tables populated. `PRAGMA integrity_check`
   returns `ok`.

## Migration / compatibility

- Tool API surface unchanged.
- `ingest_structured(path, db_path, schema)` becomes
  `ingest_structured(path, db_store, schema)`. Internal call site (only
  used by `CorpusAgent`) updates in the same commit. Public re-exports
  in `rag/ingest/__init__.py` follow.
- `LocalFolderSourceConfig` gains an optional `exclude_predicate`; default
  `None` preserves existing behaviour.
- Existing tests using the old `ingest_structured` signature update in
  the same commit.

## Out of scope (logged for follow-up)

- **Multi-server coordination.** If the same corpus is mounted by two
  MCP servers (e.g. one per Claude Desktop, one per `claude` CLI), they
  still rely on the filesystem sentinel for cross-process locking. That
  works today; a future change might switch to file locks (`fcntl`) for
  faster contention.
- **CorpusAgent.close on idle timeout.** If memory pressure becomes a
  concern with many corpora, an LRU cap on `_AGENT_CACHE` is a 10-line
  follow-up.
- **Better error message when an XLSX is asked for via `ingest_corpus_filesystem`.**
  Today a CSV/XLSX silently goes to `skipped`. A debug-level log line
  explaining "skipped — handled by ingest_corpus_structured" would help
  but is not blocking.
