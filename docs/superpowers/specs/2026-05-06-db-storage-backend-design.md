# Design: Storage layer for managed SQLite files (Local + Azure Blob)

**Date:** 2026-05-06
**Branch:** `db_store_backend`
**Status:** Draft (pending user review)

## Goal

Add a storage abstraction that owns the **read/write lifecycle of a single
SQLite file** that may live either on the local filesystem or in Azure Blob
Storage. Wire `SqliteCorpus` and `SqliteVecVectorStore` to source their
file path and write lock from this layer, and switch the corpus_search
example to use it so the existing E2E test suite exercises the full stack.

Two backends ship with this change:

- `LocalBackend` — sqlite file lives on disk; locking via an `asyncio.Lock`
  plus a sentinel file; revision tracking via mtime-based etag.
- `AzureBlobBackend` — sqlite file lives in Azure Blob Storage; locking via
  blob lease (60 s, auto-renew); revision tracking via the blob's HTTP ETag.

The design optimises for the common case: a sole or dominant writer (e.g.
one container watching a SharePoint folder) ingests in batches. We
minimise blob I/O while keeping correctness under contention.

## Non-goals

- **No SQL API on the storage layer.** This PR does not add `query()`,
  `query_raw()`, `discover()`, or any other SQL surface on `DatabaseStore`.
  Callers continue to open their own `sqlite3` connections against the
  file path the storage layer hands them and run all SQL themselves.
- **No public-API redesign of `SqliteCorpus` or `SqliteVecVectorStore`.**
  The wiring change is constructor-level only (accept a `DatabaseStore`
  instead of a raw path) plus an internal connection-refresh hook so
  read connections are reopened when the cache file is replaced. All
  existing methods and their semantics stay.
- **No row-level merge of concurrent writes.** Writers are serialised by
  an exclusive lock; "force re-read on write" means re-pull on lock
  acquire if remote moved, not row merging.
- **No block-level diff upload, no WAL shipping, no CDC.** Future
  optimisations, listed as toggles only.
- **No schema migrations.** Outside the storage layer's concern.
- **No new structured-ingest path in this PR.** Mentioned in the diagram
  but lands separately once the storage layer is in.

## Scope

In scope:

- `StorageBackend` ABC and the two concrete backends.
- A thin orchestrator class (`DatabaseStore`) wrapping a backend with the
  lock + sync + upload state machine.
- A persistent local cache (path + sidecar metadata) tracked across
  process lifetimes.
- A retry policy with idiomatic error types.
- **Wiring**: `SqliteCorpus` and `SqliteVecVectorStore` accept a
  `DatabaseStore`; their write methods participate in a shared batch
  session; their read methods refresh the local connection when the
  cache file is replaced.
- **Corpus_search example update**: construct one shared `DatabaseStore`
  (default `LocalBackend`, env-toggle for `AzureBlobBackend`) and pass it
  to both classes. The ingest pipeline opens a single `for_write` batch
  spanning the chunk write + the vector write.
- Tests: unit (each backend in isolation, mocked), integration (Azurite
  for Azure backend), failure injection (lease loss, upload exhaustion),
  **E2E (corpus_search benchmark + agent tests run through
  `DatabaseStore`-backed stores, against both `LocalBackend` and an
  Azurite-backed `AzureBlobBackend`)**.

Out of scope (follow-up work):

- Any structured-ingest path that may consume this layer.
- Block-blob chunked upload, gzip-on-upload, periodic VACUUM. Hooks may
  exist as constructor toggles but default off; their full implementation
  is a future pass.

---

## Architecture

```
                    ┌────────────────────────────┐
                    │      DatabaseStore         │
                    │ for_write() -> WriteSession│
                    │ ensure_fresh() -> (Path,gen)│
                    │ close()                    │
                    └────────────┬───────────────┘
                                 │
                                 ▼
                    ┌───────────────────────┐
                    │  StorageBackend ABC   │
                    │  metadata()           │
                    │  download(dest)       │
                    │  upload(src, ...)     │
                    │  acquire_lock(timeout)│
                    │  release_lock(token)  │
                    └────┬────────────┬─────┘
                         │            │
                ┌────────▼─┐   ┌──────▼────────────┐
                │ Local    │   │ AzureBlob         │
                │ Backend  │   │ Backend           │
                └──────────┘   └───────────────────┘
```

`DatabaseStore` holds:

- A `StorageBackend` instance.
- A local cache directory (`<cache_root>/<store_id>/`) containing the
  cached sqlite file plus a `metadata.json` sidecar tracking
  `{etag, last_modified, dirty}` across process lifetimes.
- Internal state: an `asyncio.Lock` to serialise concurrent calls in one
  process, the last freshness check timestamp, and the lock token while a
  write is in flight.

`DatabaseStore` does NOT open `sqlite3` connections. It hands callers the
local file path and the lock; callers do the SQL. WAL mode (set by the
caller when they open their connection) keeps local readers from blocking
the in-flight writer on the same host.

---

## Components

### `StorageBackend` (ABC)

`src/fireflyframework_agentic/storage/backend.py`

```python
class StorageMetadata(NamedTuple):
    etag: str | None         # backend-defined opaque revision token
    size_bytes: int | None
    modified: datetime | None
    exists: bool

class LockToken(NamedTuple):
    token: str               # opaque to caller; backend interprets
    acquired_at: datetime
    expires_at: datetime | None  # None = no auto-expiry (Local)

class StorageBackend(ABC):
    async def metadata(self) -> StorageMetadata: ...
    async def download(self, dest: Path) -> StorageMetadata: ...
    async def upload(self, src: Path, *,
                     if_match: str | None = None,
                     if_none_match: str | None = None) -> StorageMetadata: ...
    async def acquire_lock(self, *, timeout: float) -> LockToken: ...
    async def release_lock(self, token: LockToken) -> None: ...
    async def renew_lock(self, token: LockToken) -> LockToken:
        """Optional; default raises NotImplementedError. Used by
        AzureBlobBackend's auto-renew task."""
```

`upload` accepts `if_match` (used in normal path: only overwrite if remote
etag still matches what we expect — defends against split-brain after lease
loss) and `if_none_match='*'` (used on first write to atomically create
iff no blob exists).

### `LocalBackend`

`src/fireflyframework_agentic/storage/local_backend.py`

- Constructor: `LocalBackend(path: Path)` — `path` is the durable sqlite
  file location.
- `metadata()` → etag derived from `(mtime_ns, size)`; `exists=False` if
  missing.
- `download(dest)` → `shutil.copyfile(self.path, dest)` (no-op if
  `path == dest`, supported via stat-equality short-circuit).
- `upload(src)` → atomic rename: copy to `path.tmp`, `fsync`, `os.replace`.
  `if_match` is enforced by re-stat-ing under the lock; mismatch raises
  `StorageLeaseError`.
- `acquire_lock` → process-local `asyncio.Lock` + filesystem sentinel
  (`<path>.lock`, `O_CREAT | O_EXCL`). Token = `pid:nonce`.
- `release_lock` → unlink sentinel, release `asyncio.Lock`.
- Stale-sentinel reclaim: if the sentinel's pid no longer exists OR the
  lock file is older than `stale_lock_seconds` (default 600), break it
  and proceed. Logged at WARNING.

### `AzureBlobBackend`

`src/fireflyframework_agentic/storage/azure_backend.py`

- Constructor:
  `AzureBlobBackend(container_url, blob_name, *, credential, lease_duration_s=60)`.
- Uses `azure-storage-blob` (added under a new `[storage-azure]` extra,
  alongside `azure-identity`).
- `metadata()` → `BlobClient.get_blob_properties()` → returns `etag`,
  `size`, `last_modified`. 404 → `exists=False`, all other fields None.
- `download(dest)` → stream to `dest.tmp`, then atomic rename.
- `upload(src)` → `upload_blob(data=open(src, "rb"), overwrite=True,
  if_match=...)`. On `if_none_match='*'` first-write path the resulting
  412 is converted to `RaceLost` flag → caller switches to download path.
- `acquire_lock(timeout)` → `BlobClient.acquire_lease(lease_duration=60)`,
  retried until `timeout` elapses. Spawns a background asyncio task that
  renews every 30 s while the lock is held. Renewer exceptions are stored
  on the token; on next operation they surface as `StorageLeaseError`.
- `release_lock(token)` → cancel renewer, `release_lease(token.token)`.

### `DatabaseStore`

`src/fireflyframework_agentic/storage/database_store.py`

```python
@dataclass(frozen=True)
class WriteSession:
    path: Path           # local cache file, lock held by DatabaseStore
    generation: int      # bumped each time the cache file is replaced
                         # (download or first-write). Used by callers to
                         # invalidate their long-lived read connections.

class DatabaseStore:
    def __init__(
        self,
        backend: StorageBackend,
        *,
        store_id: str,
        cache_root: Path | None = None,    # default: $FIREFLY_DBSTORE_CACHE_ROOT
                                           # or ~/.cache/fireflyframework_agentic/dbstore
        retry_policy: RetryPolicy | None = None,
        read_freshness_seconds: float = 5.0,
    ): ...

    @asynccontextmanager
    async def for_write(self, *, lock_timeout: float = 30.0) -> AsyncIterator[WriteSession]:
        """Acquire exclusive lock, sync from backend if stale, yield a
        WriteSession. Caller opens its own sqlite3 connection against
        session.path and runs whatever SQL it needs.

        Multiple callers (e.g. SqliteCorpus.upsert_chunks +
        SqliteVecVectorStore.upsert) can participate in the SAME batch
        by accepting a session parameter and skipping their own
        for_write. See "Wiring" section below.

        On clean exit: caller MUST have closed/flushed its connection;
        DatabaseStore uploads the file to the backend and releases the
        lock.

        On exception inside the block: no upload, lock released,
        exception propagates.

        On terminal upload failure (retries exhausted, or non-retryable):
        downloads remote (discarding local writes), releases lock,
        raises StorageUploadError. Caller MUST be idempotent — see
        contract section below."""

    async def ensure_fresh(self) -> tuple[Path, int]:
        """Lock-free. If the freshness window elapsed (or first call),
        HEAD the backend; if etag changed, download (which bumps the
        generation counter). Returns (cache_path, generation). The
        cache_path is stable for the DatabaseStore's lifetime; the
        generation increments whenever the file content has been
        replaced under us. Callers cache (conn, generation); when they
        observe a new generation they close and reopen their
        connection against the same path."""

    async def close(self) -> None: ...
```

### Caller contract

A caller using `for_write` (either as the outer `async with` or by being
handed a session) MUST:

1. Open its `sqlite3` connection against `session.path` inside the
   batch. WAL mode is recommended.
2. Close (or at least `commit()` and stop using) its connection before
   the outermost `for_write` exits, so the file on disk reflects the
   final committed state when `DatabaseStore` uploads.
3. Be **idempotent**: if the upload terminally fails, `DatabaseStore`
   discards the local writes and re-pulls remote. The caller must be
   able to re-run the same batch and produce the same logical
   end-state without duplicates. (`SqliteCorpus.ingestions`
   content-hash gating and `INSERT OR REPLACE` upserts on natural keys
   are the standard patterns.)

A caller using `ensure_fresh` for reads holds a `(connection,
generation)` pair as cache. Each read calls `ensure_fresh()` and
compares the returned generation to its cached one; on mismatch it
closes the old connection and opens a new one against the same path.
This is implemented as a small helper on the caller side
(`_get_read_conn`, see "Wiring").

---

---

## Wiring (`SqliteCorpus`, `SqliteVecVectorStore`, corpus_search example)

### Refactor pattern shared by both classes

```python
class SqliteCorpus:
    def __init__(self, store: DatabaseStore) -> None:
        self._store = store
        self._conn: sqlite3.Connection | None = None
        self._generation: int = -1
        self._conn_lock = asyncio.Lock()       # serialises connection rebuild

    async def _get_read_conn(self) -> sqlite3.Connection:
        path, generation = await self._store.ensure_fresh()
        async with self._conn_lock:
            if self._conn is None or generation != self._generation:
                if self._conn is not None:
                    await asyncio.to_thread(self._conn.close)
                self._conn = await asyncio.to_thread(self._open_conn, path)
                self._generation = generation
            return self._conn

    @staticmethod
    def _open_conn(path: Path) -> sqlite3.Connection:
        # WAL, executescript(_SCHEMA), row_factory, etc. — same as today's
        # _initialise_sync, just parameterised on path.
        ...

    # ---- writes ----

    async def upsert_chunks(
        self,
        chunks: Sequence[StoredChunk],
        *,
        session: WriteSession | None = None,
    ) -> None:
        if session is None:
            async with self._store.for_write() as session:
                await self._upsert_in_session(session, list(chunks))
        else:
            await self._upsert_in_session(session, list(chunks))

    async def _upsert_in_session(self, session: WriteSession, chunks: list[StoredChunk]) -> None:
        # Open a short-lived write connection against session.path.
        # WAL keeps open/close cheap; ingestion granularity is per-batch,
        # not per-row, so the cost is negligible.
        conn = await asyncio.to_thread(self._open_conn, session.path)
        try:
            await asyncio.to_thread(self._upsert_chunks_sync, conn, chunks)
        finally:
            await asyncio.to_thread(conn.close)

    # ---- reads ----

    async def bm25_search(self, query: str, *, top_k: int = 30) -> list[ChunkHit]:
        conn = await self._get_read_conn()
        return await asyncio.to_thread(self._bm25_search_sync, conn, query, top_k)
```

`SqliteVecVectorStore` follows the same pattern. Its `_open_conn` loads
the `sqlite-vec` extension before returning the connection (existing
logic, just lifted into a factory). Its `_upsert/_search/_delete` accept
the optional `session` kwarg.

Public API of both classes is unchanged — every existing method keeps its
signature; the only addition is the optional `session` kwarg on the
write methods. Existing tests pass.

### Path-based construction (compatibility)

To keep call sites that pass a raw path working with minimum churn:

```python
class SqliteCorpus:
    @classmethod
    def from_path(cls, path: Path | str) -> "SqliteCorpus":
        from fireflyframework_agentic.storage import LocalBackend, DatabaseStore
        store = DatabaseStore(
            LocalBackend(Path(path)),
            store_id=f"local:{Path(path).resolve()}",
        )
        return cls(store)
```

`SqliteVecVectorStore.from_path(path, dimension)` does the same.

When two classes co-locate in the same file (the corpus_search case),
the caller is responsible for constructing **one** `DatabaseStore` and
passing it to **both** classes — otherwise the store_id / cache layout
diverges and they'd race on the file. See the corpus_search example
below.

### Coordinated batch (single upload per ingestion)

Today's ingest pipeline calls `corpus.upsert_chunks(...)` and
`vec_store.upsert(...)` in sequence. Under the new layer they share one
batch:

```python
async with database_store.for_write() as session:
    await corpus.upsert_chunks(chunks, session=session)
    await vec_store.upsert(documents, session=session)
# single upload happens here on exit
```

Each class still opens and closes its own short-lived sqlite3
connection inside the session — they don't share a connection — but
both write to the same file under the same backend lock, and only one
upload happens.

### Corpus_search example update

`examples/corpus_search/cli.py` (and `agent.py` where it constructs
stores) is changed to:

```python
from fireflyframework_agentic.storage import (
    DatabaseStore, LocalBackend, AzureBlobBackend,
)

def _build_database_store(corpus_dir: Path) -> DatabaseStore:
    backend_kind = os.environ.get("CORPUS_SEARCH_BACKEND", "local")
    if backend_kind == "local":
        backend = LocalBackend(corpus_dir / "corpus.sqlite")
    elif backend_kind == "azure":
        backend = AzureBlobBackend(
            container_url=os.environ["AZURE_BLOB_CONTAINER_URL"],
            blob_name=os.environ.get("AZURE_BLOB_NAME", "corpus.sqlite"),
            credential=DefaultAzureCredential(),
        )
    else:
        raise ValueError(f"Unknown CORPUS_SEARCH_BACKEND: {backend_kind}")
    return DatabaseStore(backend, store_id="corpus_search")

store = _build_database_store(corpus_dir)
corpus = SqliteCorpus(store)
vec_store = SqliteVecVectorStore(store, dimension=embedder.dimension)
```

The default (`CORPUS_SEARCH_BACKEND=local`, or unset) preserves today's
on-disk behaviour. Setting it to `azure` switches the same code path to
blob storage with no other changes.

The ingest pipeline in `examples/corpus_search/__main__.py` /
`agent.py` is updated to wrap chunk + vector writes in one
`async with store.for_write()` block.

---

## Lifecycle

### `for_write` (typical SharePoint batch — sole writer steady state)

```
for_write entered
  acquire_lock                          (Local: instant; Azure: 1 RTT)
  meta = metadata()                     (1 RTT, ~tens of ms)
  if meta.exists and meta.etag == cached_etag:
      skip download                     (no body transfer)
  elif meta.exists:
      download(cache_path)
      generation += 1; cached_etag = meta.etag
  else:
      ensure cache_path is empty file
      generation += 1; mark first_write = True
  if sidecar.dirty:                     (crash recovery — see below)
      download(cache_path); generation += 1
      sidecar.dirty = False; cached_etag = meta.etag
  yield WriteSession(path=cache_path, generation=generation)

caller (and any sub-callers it passed `session` to) opens its own
sqlite3 conn against session.path, runs writes, commits, closes

exit (no exception):
  sidecar.dirty = True; persist sidecar
  with retry_policy:
      new_meta = upload(cache_path,
                        if_match=cached_etag if not first_write else None,
                        if_none_match='*' if first_write else None)
  cached_etag = new_meta.etag; sidecar.dirty = False; persist sidecar
  release_lock
```

### `for_write` exit on exception inside the block

```
exception inside with-block (caller's SQL or Python error)
__aexit__ sees exc:
  no upload
  release_lock
  exception propagates unchanged
```

`sidecar.dirty` was not flipped, because we hadn't reached the upload
phase. Local cache reflects whatever the caller's sqlite3 connection
left on disk. On the next `for_write`, if remote etag differs we'll
re-download and overwrite that local mess; if remote etag matches we'll
keep the local file as-is (caller's own rollback discipline applies).

### `for_write` exit on terminal upload failure

```
exit (clean):
  COMMIT-equivalent already done by caller
  upload retry 1/N → retryable error → backoff
  upload retry 2/N → retryable error → backoff
  upload retry N/N → terminal
  download(cache_path)                  (discard local writes)
  cached_etag = meta_after.etag; sidecar.dirty = False
  release_lock
  log ERROR with full context
  raise StorageUploadError
```

Non-retryable errors short-circuit retries and follow the same path.

Caller (idempotent) re-detects the same source files on the next batch
and re-runs.

### `ensure_fresh` (cold reader)

```
ensure_fresh()
  if (now - last_freshness) > read_freshness_seconds:
      meta = metadata()                 (1 RTT)
      if meta.exists and meta.etag != cached_etag:
          download(cache_path)
          generation += 1; cached_etag = meta.etag
      last_freshness = now
  return (cache_path, generation)
```

### `ensure_fresh` (steady-state reader within freshness window)

```
ensure_fresh()  → returns (cache_path, generation) immediately, no I/O
```

### Crash recovery via the `dirty` flag

If the process crashes between sidecar `dirty=True` and a successful
upload, the local cache may be ahead of remote. On the next `for_write`,
the entry sequence detects `dirty=True` and re-downloads to discard the
unrecovered local state, then proceeds. The caller's idempotency
contract handles re-doing the lost work.

If the crash leaves a stale `LocalBackend` sentinel, the next acquirer's
stale-sentinel reclaim path breaks it after the timeout.

---

## Retry policy and errors

```python
@dataclass
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_s: float = 1.0
    max_backoff_s: float = 30.0
    jitter: bool = True
    retry_on: tuple[type[Exception], ...] = (StorageTransientError,)

# Error hierarchy
DatabaseStoreError
├── StorageUploadError       # terminal upload failure
├── StorageDownloadError
├── StorageLeaseError        # lease lost, conditional check failed
├── StorageTransientError    # retryable; not surfaced raw
└── StoreUnavailableError    # init/config problems (creds, container missing)
```

`StorageTransientError` wraps: HTTP 5xx, 408, 429, network errors,
DNS failures. Everything else is non-retryable: 4xx (auth, not found,
malformed), conditional-check failures (412 — covered by lease-error
path), config errors.

Every raised error carries: `store_id`, `backend_kind`, `etag_before`,
`etag_after_remote`, `attempts`, redacted resource URL, and the inner
exception. Every raised error is also logged at `ERROR` before raising,
matching the global "no silent errors" guardrail.

---

## Configuration

- New module: `src/fireflyframework_agentic/storage/`.
- New optional extras:
  - `[storage-azure]` → `azure-storage-blob`, `azure-identity`.
  (Local backend has no extras.)
- New env var: `FIREFLY_DBSTORE_CACHE_ROOT` (default
  `~/.cache/fireflyframework_agentic/dbstore`).

---

## Testing strategy

### Unit (mocked backend)

- `DatabaseStore.for_write` lifecycle: skip-download-on-etag-match,
  download-on-mismatch, upload after clean exit, sidecar updates,
  rollback path on exception inside block.
- Crash-recovery path: pre-set `dirty=True`, verify next `for_write`
  re-downloads.
- `RetryPolicy` honours `retry_on`; non-retryable surfaces immediately.
- `for_write` terminal upload failure: verify download-and-discard +
  release lock + raise with full context.
- `ensure_fresh` honours freshness window; HEADs only when stale.

### Backend-isolated

- `LocalBackend` against a real tmpdir: concurrent writers across
  asyncio tasks serialise correctly; stale-sentinel reclaim breaks an
  abandoned lock; `if_match` enforcement.
- `AzureBlobBackend` against
  [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite):
  lease acquire / renew / release; conditional upload (412 on
  if-none-match race); download; metadata on missing blob.

### Failure injection

- Kill upload mid-batch → verify next `for_write` enters dirty-recovery
  path and discards local.
- Network blip > 60 s → simulate lease loss → upload's conditional PUT
  fails → discard-and-rethrow path.
- Azure 5xx burst → retries succeed within `max_attempts`.

### Wiring tests (`SqliteCorpus`, `SqliteVecVectorStore`)

- Connection-refresh on generation bump: pre-populate the local cache,
  build a `SqliteCorpus`, run a read, replace the cache file out of
  band (simulating a remote-driven refresh), verify the next read
  observes the new generation, closes the old conn and reopens.
- Coordinated batch: `async with store.for_write()` wrapping
  `corpus.upsert_chunks(session=session)` +
  `vec_store.upsert(session=session)` results in **one** upload, not
  two.
- Standalone batch: calling `corpus.upsert_chunks(...)` without a
  session opens its own `for_write` and does its own upload — verifies
  back-compat for callers that haven't been migrated.
- `from_path` factory: existing path-based call sites keep working.

### End-to-end (corpus_search example)

The existing test suites under `tests/examples/corpus_search/` and
`tests/integration/test_ingest_with_real_vectorstore.py` are
parameterised over backend kind:

- **`local`** — `CORPUS_SEARCH_BACKEND=local`, default; existing
  behaviour, must stay green.
- **`azure_blob_azurite`** — same suite run against an Azurite-backed
  `AzureBlobBackend`; covers ingestion + retrieval + benchmark.

This is what makes the storage layer testable end-to-end as the user
asked for: the corpus agent's existing E2E tests are the integration
proof.

### What we explicitly do NOT test in this PR

- Vector / FTS5 query semantics — unchanged by this layer; existing
  tests cover them and continue to run.
- Any structured-ingest path — out of scope.

---

## Migration plan

The PR can be landed as one merge or split into sequential commits;
either way the changes are additive at each step:

1. **Storage module** (`src/fireflyframework_agentic/storage/`) —
   `StorageBackend` ABC + `LocalBackend` + `DatabaseStore`. Unit and
   `LocalBackend` integration tests. No callers wired in yet.
2. **`AzureBlobBackend`** behind `[storage-azure]` extra. Azurite
   integration tests.
3. **Wiring** — refactor `SqliteCorpus` and `SqliteVecVectorStore`
   constructors; add `from_path` factories; add `_get_read_conn` /
   generation handling; add optional `session` kwarg to write methods.
   All existing tests for those classes pass against `from_path`-built
   stores.
4. **Corpus_search example** — switch to `DatabaseStore`-backed
   construction; ingest pipeline wraps chunk + vector writes in one
   `for_write`. Existing E2E suite passes against `local` backend;
   add Azurite parameterisation.

Existing `corpus.sqlite` users who don't opt into Azure see no
behaviour change beyond `SqliteCorpus(path)` becoming
`SqliteCorpus.from_path(path)` (or — if we choose to keep
`SqliteCorpus(path)` as a sugar shim — no source change at all; punt
that ergonomics call to implementation).

Follow-ups out of scope here:

- Structured-ingest path consuming `DatabaseStore`.
- gzip-on-upload, periodic VACUUM, block-blob chunked upload.

---

## Open questions / deferred

- **Stale-sentinel reclaim parameters for `LocalBackend`.** Default of
  10 minutes seems generous; punt to implementation PR for tuning.
- **Admin "force re-download" hook.** Useful for ops if a known-bad
  local cache needs to be wiped without restarting. Trivial to add;
  defer to first user that needs it.
- **Whether `DatabaseStore.ensure_fresh` should expose a callback for
  "cache was replaced".** Useful for callers that hold long-lived
  connections. Defer to wiring PR — caller pattern will tell us.
