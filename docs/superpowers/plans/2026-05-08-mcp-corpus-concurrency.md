# MCP Corpus Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the corpus_rag MCP server safe under parallel tool calls against the same `corpus_id`, route the structured pipeline through `DatabaseStore.for_write()`, and stop double-ingesting spreadsheets.

**Architecture:** Process-wide `_AGENT_CACHE` keyed by `corpus_id` so every tool call shares one `CorpusAgent`/`DatabaseStore`/`LocalBackend`. A per-corpus tool-level `asyncio.Lock` serialises writers; reads stay lock-free. `ingest_structured` accepts a `DatabaseStore` and runs `_sync_ingest_table` inside `db_store.for_write()` with a tightened sqlite3 connection (timeout + busy_timeout). `LocalFolderSource` learns an `exclude_predicate` so `ingest_corpus_filesystem` skips tabular files now owned by `ingest_corpus_structured`. Cached agents close on FastMCP lifespan shutdown.

**Tech Stack:** Python 3.13, `sqlite3` stdlib + `sqlite-vec`, `fastmcp` (lifespan API), `pytest` with `asyncio_mode=auto`.

**Spec:** See `docs/superpowers/specs/2026-05-08-mcp-corpus-concurrency-design.md`.

**Branch:** `fix/mcp-demo-findings` (continuing from the merged folder-filter commits).

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `tests/unit/tools/builtins/test_corpus_rag_registry.py` | Agent cache + per-corpus write-lock unit tests |
| `tests/unit/content/sources/test_local_folder_exclude.py` | `exclude_predicate` filtering unit tests |
| `tests/integration/test_mcp_corpus_concurrency.py` | E2E parallel structured + unstructured ingest against a real SQLite file |

**Modified files:**

| Path | Change |
|---|---|
| `src/fireflyframework_agentic/content/sources/local_folder.py` | Add `LocalFolderSourceConfig.exclude_predicate` and apply in `list_changed` |
| `src/fireflyframework_agentic/rag/ingest/structured_pipeline.py` | `ingest_structured(path, db_store, schema)` running through `db_store.for_write()`; `_sync_ingest_table` sets `busy_timeout` |
| `src/fireflyframework_agentic/rag/agent.py` | Pass `self._db_store` to `ingest_structured` |
| `src/fireflyframework_agentic/tools/builtins/corpus_rag.py` | `_AGENT_CACHE` + `_WRITE_LOCKS` + `_shutdown_agents`; tool bodies wrap writes in the per-corpus lock; `ingest_corpus_filesystem` uses `is_tabular_file` exclude predicate |
| `src/fireflyframework_agentic/exposure/mcp/server.py` | `create_mcp_app(*, lifespan=None)` plumbed through to `FastMCP` constructor |
| `examples/corpus_search/mcp_server.py` | Build a lifespan that calls `_shutdown_agents` on exit; pass to `create_mcp_app` |
| `tests/unit/rag/ingest/test_structured_pipeline.py` (existing) | Adapt to new `ingest_structured` signature |
| `tests/unit/corpus_search/test_agent_structured.py` (existing) | Adapt to new `ingest_structured` signature |

**Total estimated diff:** ~350 lines of code + ~250 lines of tests across 9 files.

---

## Task 1: `LocalFolderSourceConfig.exclude_predicate`

**Why first:** Foundational — the MCP filesystem ingest fix in Task 5 depends on this. No coupling to concurrency work, so it can land independently.

**Files:**
- Modify: `src/fireflyframework_agentic/content/sources/local_folder.py` (`LocalFolderSourceConfig`)
- Test: `tests/unit/content/sources/test_local_folder_exclude.py` (new)

- [ ] **Step 1.1: Write the failing test**

Create `tests/unit/content/sources/test_local_folder_exclude.py`:

```python
from pathlib import Path

import pytest

from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)


@pytest.mark.asyncio
async def test_exclude_predicate_skips_matching_files(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("keep")
    (tmp_path / "skip.csv").write_text("a,b\n1,2\n")
    (tmp_path / "also_skip.xlsx").write_bytes(b"PK\x03\x04")

    source = LocalFolderSource(
        LocalFolderSourceConfig(
            folder=tmp_path,
            exclude_predicate=lambda p: p.suffix.lower() in {".csv", ".xlsx"},
        )
    )

    names = sorted([rf.name async for rf in source.list_changed(since=None)])
    assert names == ["keep.md"]


@pytest.mark.asyncio
async def test_exclude_predicate_default_none_keeps_everything(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "b.csv").write_text("a,b\n1,2\n")

    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))
    names = sorted([rf.name async for rf in source.list_changed(since=None)])
    assert names == ["a.md", "b.csv"]
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
uv run pytest tests/unit/content/sources/test_local_folder_exclude.py -v
```
Expected: FAIL — `LocalFolderSourceConfig` does not accept `exclude_predicate`.

- [ ] **Step 1.3: Implement**

In `src/fireflyframework_agentic/content/sources/local_folder.py`, edit `LocalFolderSourceConfig` and `LocalFolderSource.list_changed`:

```python
from collections.abc import Callable

class LocalFolderSourceConfig(BaseModel):
    folder: Path
    include_hidden: bool = Field(
        default=False,
        description="When False (default), files whose name begins with '.' are skipped.",
    )
    exclude_predicate: Callable[[Path], bool] | None = Field(
        default=None,
        description=(
            "Optional callable; when it returns True for a file path, the file is "
            "skipped. Used by callers that route certain extensions to a separate "
            "pipeline (e.g. CSV/Excel handled by structured ingest)."
        ),
        exclude=True,  # not part of serialised config
    )

    model_config = {"arbitrary_types_allowed": True}
```

In `LocalFolderSource.__init__`:

```python
def __init__(self, config: LocalFolderSourceConfig) -> None:
    self._folder = Path(config.folder).resolve()
    self._include_hidden = config.include_hidden
    self._exclude_predicate = config.exclude_predicate
    self._watcher = FolderWatcher(folder=self._folder)
```

In `list_changed`, after the hidden check:

```python
if self._exclude_predicate is not None and self._exclude_predicate(path):
    continue
```

- [ ] **Step 1.4: Run test to verify it passes**

```bash
uv run pytest tests/unit/content/sources/test_local_folder_exclude.py -v
```
Expected: 2 passed.

- [ ] **Step 1.5: Commit**

```bash
git add src/fireflyframework_agentic/content/sources/local_folder.py \
        tests/unit/content/sources/test_local_folder_exclude.py
git commit -m "feat(content): LocalFolderSourceConfig.exclude_predicate

Allow callers to skip files matching a predicate (e.g. tabular formats
routed to a separate pipeline). Default None preserves existing behaviour.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Tighten `_sync_ingest_table` with explicit busy_timeout

**Why before Task 3:** Smaller change, easy to verify in isolation, sets up the connection hardening before we wrap it in `for_write()`.

**Files:**
- Modify: `src/fireflyframework_agentic/rag/ingest/structured_pipeline.py:150-198`
- Test: `tests/unit/rag/ingest/test_structured_pipeline.py` (existing — add a test)

- [ ] **Step 2.1: Add failing test**

Append to `tests/unit/rag/ingest/test_structured_pipeline.py`:

```python
import sqlite3

from fireflyframework_agentic.rag.ingest.structured_pipeline import _sync_ingest_table
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
)


def test_sync_ingest_table_sets_busy_timeout(tmp_path):
    db_path = tmp_path / "x.sqlite"
    spec = TableSpec(
        name="t",
        columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
    )
    _sync_ingest_table(db_path, spec, [{"id": 1}])

    # After the call, open the same file and confirm the table exists and
    # busy_timeout was set on the writer connection (we observe via PRAGMA
    # on the file — busy_timeout is per-connection, so we verify behaviour
    # by checking the function still works when another connection holds a
    # lock briefly).
    blocker = sqlite3.connect(db_path, timeout=0.1, isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        # Second writer with busy_timeout=30000 should wait, not fail.
        # We can't wait 30s in unit tests; instead, release the lock
        # quickly and confirm the second insert succeeds.
        blocker.commit()
    finally:
        blocker.close()

    result = _sync_ingest_table(db_path, spec, [{"id": 2}])
    assert result["status"] == "success"
    assert result["inserted"] == 1
```

- [ ] **Step 2.2: Run test to verify it passes (busy_timeout is currently default 5s, so this test should already pass; the failing assertion comes in step 2.3)**

Skip the run — Step 2.3's failing test exercises behaviour the current code lacks.

- [ ] **Step 2.3: Add a stricter failing test**

Append:

```python
def test_sync_ingest_table_uses_busy_timeout_pragma(tmp_path, monkeypatch):
    """The writer connection must explicitly set busy_timeout so it doesn't
    rely on the python sqlite3 module's default (5s)."""
    db_path = tmp_path / "x.sqlite"
    spec = TableSpec(
        name="t",
        columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
    )

    captured_timeouts: list[int] = []
    real_execute = sqlite3.Connection.execute

    def spy_execute(self, sql, *args, **kwargs):
        if "busy_timeout" in sql.lower():
            captured_timeouts.append(int(sql.split("=")[1].strip()))
        return real_execute(self, sql, *args, **kwargs)

    monkeypatch.setattr(sqlite3.Connection, "execute", spy_execute)
    _sync_ingest_table(db_path, spec, [{"id": 1}])

    assert 30000 in captured_timeouts, f"expected busy_timeout=30000, got {captured_timeouts}"
```

```bash
uv run pytest tests/unit/rag/ingest/test_structured_pipeline.py::test_sync_ingest_table_uses_busy_timeout_pragma -v
```
Expected: FAIL — current implementation never executes a `PRAGMA busy_timeout`.

- [ ] **Step 2.4: Implement**

In `src/fireflyframework_agentic/rag/ingest/structured_pipeline.py`, change the `sqlite3.connect` call at the top of `_sync_ingest_table`:

```python
def _sync_ingest_table(
    db_path: Path,
    table_spec: TableSpec,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        # ... existing body unchanged, but replace conn.commit / conn.rollback
        # with explicit BEGIN/COMMIT/ROLLBACK because isolation_level=None means
        # the connection is in autocommit mode.
        col_defs: list[str] = []
        # ... (rest as today, but wrap the per-row inserts in BEGIN/COMMIT)
```

Because `isolation_level=None` switches the driver to autocommit, the
existing `conn.rollback()` / `conn.commit()` calls become no-ops. Wrap
the inserts explicitly:

```python
        all_defs = col_defs + fk_defs
        conn.execute(f"CREATE TABLE IF NOT EXISTS {_quote(table_spec.name)} ({', '.join(all_defs)})")
        col_names = [c.name for c in table_spec.columns]
        placeholders = ", ".join("?" for _ in col_names)
        col_names_str = ", ".join(_quote(c) for c in col_names)
        errors: list[str] = []
        inserted = 0
        conn.execute("BEGIN")
        try:
            for row_num, row in enumerate(rows, start=2):
                values = [row.get(c) for c in col_names]
                if all(v is None for v in values):
                    continue
                try:
                    conn.execute(
                        f"INSERT INTO {_quote(table_spec.name)} ({col_names_str}) VALUES ({placeholders})",
                        values,
                    )
                    inserted += 1
                except sqlite3.Error as exc:
                    errors.append(f"row {row_num}: {exc}")
            if errors:
                conn.execute("ROLLBACK")
                return {"status": "failed", "inserted": 0, "errors": errors}
            conn.execute("COMMIT")
            return {"status": "success", "inserted": inserted, "errors": []}
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
```

Add `import contextlib` at the top of the module if not already present.

- [ ] **Step 2.5: Run tests**

```bash
uv run pytest tests/unit/rag/ingest/test_structured_pipeline.py -v
```
Expected: all green, including the new busy_timeout test.

- [ ] **Step 2.6: Commit**

```bash
git add src/fireflyframework_agentic/rag/ingest/structured_pipeline.py \
        tests/unit/rag/ingest/test_structured_pipeline.py
git commit -m "fix(rag): tighten _sync_ingest_table connection (timeout + busy_timeout)

Set sqlite3.connect timeout=30s and PRAGMA busy_timeout=30000 so the
writer waits for the WAL slot under contention instead of failing fast
with 'database is locked'. Switch to autocommit + explicit BEGIN/COMMIT
since the previous code relied on Python's implicit transaction control
that's incompatible with isolation_level=None (set in next commit).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `ingest_structured` takes `DatabaseStore` and goes through `for_write()`

**Files:**
- Modify: `src/fireflyframework_agentic/rag/ingest/structured_pipeline.py:230-254`
- Modify: `src/fireflyframework_agentic/rag/agent.py:299-320` (the `_ingest_structured_file` call site)
- Modify: `tests/unit/rag/ingest/test_structured_pipeline.py` (existing tests calling old signature)
- Modify: `tests/unit/corpus_search/test_agent_structured.py` (existing tests patching the symbol)

- [ ] **Step 3.1: Read the existing test that patches the symbol**

```bash
grep -n "ingest_structured" tests/unit/corpus_search/test_agent_structured.py | head
```
Note the existing test mocks at `fireflyframework_agentic.rag.agent.ingest_structured`. They keep working because we don't move the symbol.

- [ ] **Step 3.2: Write the failing test**

Append to `tests/unit/rag/ingest/test_structured_pipeline.py`:

```python
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_ingest_structured_acquires_for_write(tmp_path):
    """ingest_structured must enter db_store.for_write() before writing rows."""
    from fireflyframework_agentic.rag.ingest.structured_pipeline import ingest_structured
    from fireflyframework_agentic.rag.ingest.structured_schema import (
        ColumnSpec,
        ColumnType,
        TableSpec,
        TargetSchema,
    )

    csv = tmp_path / "rows.csv"
    csv.write_text("id\n1\n2\n")
    schema = TargetSchema(
        tables=[TableSpec(name="rows", columns=[ColumnSpec(name="id", type=ColumnType.integer)])]
    )

    db_store = MagicMock()
    session = MagicMock()
    session.path = tmp_path / "corpus.sqlite"
    enter = AsyncMock(return_value=session)
    exit_ = AsyncMock(return_value=None)
    db_store.for_write.return_value.__aenter__ = enter
    db_store.for_write.return_value.__aexit__ = exit_

    await ingest_structured(csv, db_store, schema)

    enter.assert_awaited_once()
    exit_.assert_awaited_once()
    # Sanity: rows actually landed in the file under session.path
    import sqlite3
    conn = sqlite3.connect(session.path)
    try:
        n = conn.execute("SELECT count(*) FROM rows").fetchone()[0]
        assert n == 2
    finally:
        conn.close()
```

- [ ] **Step 3.3: Run test to verify it fails**

```bash
uv run pytest tests/unit/rag/ingest/test_structured_pipeline.py::test_ingest_structured_acquires_for_write -v
```
Expected: FAIL — `ingest_structured` accepts a `Path`, not a `DatabaseStore`.

- [ ] **Step 3.4: Update `ingest_structured` signature and body**

In `src/fireflyframework_agentic/rag/ingest/structured_pipeline.py`:

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fireflyframework_agentic.storage import DatabaseStore


async def ingest_structured(
    path: Path,
    db_store: DatabaseStore,
    schema: TargetSchema,
) -> dict[str, Any]:
    """Insert rows from *path* into the SQLite file owned by *db_store*.

    Routes through ``db_store.for_write()`` so the asyncio + sentinel locks
    inside the storage backend serialise this writer with anything else
    talking to the same file. Returns ``{table_name: {status, inserted, errors}}``.
    """
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

- [ ] **Step 3.5: Update agent caller**

In `src/fireflyframework_agentic/rag/agent.py` find:

```python
ingest_result = await ingest_structured(path, self.root / "corpus.sqlite", schema)
```

Replace with:

```python
ingest_result = await ingest_structured(path, self._db_store, schema)
```

- [ ] **Step 3.6: Update existing tests that patched the old signature**

Search for callers in tests:

```bash
grep -rn "await ingest_structured\|ingest_structured(" tests/ | grep -v test_structured_pipeline
```

The existing patches at `fireflyframework_agentic.rag.agent.ingest_structured` mock the symbol entirely, so they don't depend on the signature — leave them. Only `tests/unit/rag/ingest/test_structured_pipeline.py` needs updates if any test calls the function with the old signature.

Inspect:
```bash
grep -n "ingest_structured(" tests/unit/rag/ingest/test_structured_pipeline.py
```

Update any direct call to pass a real or stub `DatabaseStore` (use the same MagicMock pattern from Step 3.2).

- [ ] **Step 3.7: Run all affected tests**

```bash
uv run pytest tests/unit/rag/ingest/ tests/unit/corpus_search/ -v
```
Expected: all green.

- [ ] **Step 3.8: Commit**

```bash
git add src/fireflyframework_agentic/rag/ingest/structured_pipeline.py \
        src/fireflyframework_agentic/rag/agent.py \
        tests/unit/rag/ingest/test_structured_pipeline.py
git commit -m "fix(rag): ingest_structured goes through DatabaseStore.for_write

Route the structured pipeline through the storage layer's lock instead
of opening a raw sqlite3 connection that bypassed every coordination
primitive. Concurrent MCP tool calls touching the same corpus now
serialise on the asyncio + sentinel locks already enforced by
DatabaseStore — fixing the 'database disk image is malformed' error
seen during the demo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Agent registry + per-corpus write lock in `corpus_rag.py`

**Files:**
- Modify: `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`
- Test: `tests/unit/tools/builtins/test_corpus_rag_registry.py` (new)

- [ ] **Step 4.1: Write the failing test**

Create `tests/unit/tools/builtins/test_corpus_rag_registry.py`:

```python
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from fireflyframework_agentic.tools.builtins import corpus_rag


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path: Path):
    """Reset the module-level cache and point CORPUS_ROOT at tmp_path."""
    corpus_rag._AGENT_CACHE.clear()
    corpus_rag._WRITE_LOCKS.clear()
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "openai:text-embedding-3-small")
    monkeypatch.setenv("EXPANSION_MODEL", "anthropic:claude-haiku-3-5")
    monkeypatch.setenv("ANSWER_MODEL", "anthropic:claude-haiku-3-5")
    monkeypatch.setenv("RERANK_MODEL", "anthropic:claude-haiku-3-5")
    yield
    corpus_rag._AGENT_CACHE.clear()
    corpus_rag._WRITE_LOCKS.clear()


@pytest.mark.asyncio
async def test_agent_for_returns_cached_instance() -> None:
    a = await corpus_rag._agent_for("X")
    b = await corpus_rag._agent_for("X")
    assert a is b


@pytest.mark.asyncio
async def test_agent_for_different_corpus_ids_are_distinct() -> None:
    a = await corpus_rag._agent_for("X")
    b = await corpus_rag._agent_for("Y")
    assert a is not b


@pytest.mark.asyncio
async def test_write_lock_is_per_corpus() -> None:
    la = corpus_rag._write_lock_for("X")
    lb = corpus_rag._write_lock_for("Y")
    assert la is not lb
    assert corpus_rag._write_lock_for("X") is la


@pytest.mark.asyncio
async def test_write_lock_serialises_concurrent_writers() -> None:
    """Two coroutines holding _write_lock_for('Z') run sequentially, not concurrently."""
    timeline: list[str] = []

    async def writer(label: str) -> None:
        async with corpus_rag._write_lock_for("Z"):
            timeline.append(f"{label}-enter")
            await asyncio.sleep(0.05)
            timeline.append(f"{label}-exit")

    await asyncio.gather(writer("a"), writer("b"))
    # No interleaving: each writer's exit precedes the next writer's enter.
    assert timeline in (
        ["a-enter", "a-exit", "b-enter", "b-exit"],
        ["b-enter", "b-exit", "a-enter", "a-exit"],
    )


@pytest.mark.asyncio
async def test_shutdown_agents_closes_and_clears() -> None:
    a = await corpus_rag._agent_for("X")
    closed = []
    original_close = a.close

    async def tracking_close():
        closed.append(True)
        await original_close()

    a.close = tracking_close  # type: ignore[method-assign]
    await corpus_rag._shutdown_agents()
    assert closed == [True]
    assert corpus_rag._AGENT_CACHE == {}
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
uv run pytest tests/unit/tools/builtins/test_corpus_rag_registry.py -v
```
Expected: FAIL — `_AGENT_CACHE`, `_WRITE_LOCKS`, `_shutdown_agents`, async `_agent_for`, and `_write_lock_for` don't exist.

- [ ] **Step 4.3: Implement the registry**

In `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`, replace the existing `_agent_for` and add registry/lock helpers near the top of the module:

```python
import asyncio
import contextlib

from fireflyframework_agentic.rag import CorpusAgent  # already imported

_AGENT_CACHE: dict[str, CorpusAgent] = {}
_WRITE_LOCKS: dict[str, asyncio.Lock] = {}
_CACHE_LOCK = asyncio.Lock()


async def _agent_for(corpus_id: str) -> CorpusAgent:
    """Return a process-wide CorpusAgent for *corpus_id*, creating one on
    first use. Sharing the agent means sharing its DatabaseStore /
    LocalBackend / SqliteCorpus connections so the asyncio.Lock inside the
    backend actually serialises writes."""
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
    """Close every cached agent. Wired into FastMCP lifespan in Task 5."""
    agents = list(_AGENT_CACHE.values())
    _AGENT_CACHE.clear()
    _WRITE_LOCKS.clear()
    for agent in agents:
        with contextlib.suppress(Exception):
            await agent.close()
```

- [ ] **Step 4.4: Update every tool body**

Each tool that previously did `async with _agent_for(...) as agent:` now does `agent = await _agent_for(...)`. Tools that **write** wrap the body in the per-corpus lock. Read tools do not.

Tools to update (all in `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`):

- `ingest_corpus_filesystem` → wrap in `_write_lock_for(corpus_id)`.
- `discover_corpus_schema` → no lock (no DB writes).
- `ingest_corpus_structured` → wrap in `_write_lock_for(corpus_id)`.
- `ingest_corpus_sharepoint` → wrap in `_write_lock_for(corpus_id)`.
- `corpus_retrieve` → no lock.
- `corpus_query` → no lock.

Pattern for write tools:

```python
async def ingest_corpus_filesystem(corpus_id: str, root_path: str) -> dict[str, Any]:
    async with _write_lock_for(corpus_id):
        agent = await _agent_for(corpus_id)
        target = Path(root_path)
        # ... rest of existing body, no `async with` around the agent
```

Pattern for read tools:

```python
async def corpus_retrieve(...) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    agent = await _agent_for(corpus_id)
    # ... existing body
```

- [ ] **Step 4.5: Run registry tests + existing tool tests**

```bash
uv run pytest tests/unit/tools/builtins/test_corpus_rag_registry.py \
              tests/unit/tools/builtins/test_corpus_rag.py -v
```
Expected: all green.

- [ ] **Step 4.6: Commit**

```bash
git add src/fireflyframework_agentic/tools/builtins/corpus_rag.py \
        tests/unit/tools/builtins/test_corpus_rag_registry.py
git commit -m "fix(mcp): cache CorpusAgent per corpus_id + per-corpus write lock

Replace the per-call _agent_for() with a process-wide registry so every
MCP tool call against a given corpus_id shares the same DatabaseStore /
LocalBackend / SqliteCorpus instance — the asyncio.Lock inside the
backend now actually coordinates writers in the same process. Add a
per-corpus _WRITE_LOCKS asyncio.Lock at the tool layer as belt-and-
braces. Read tools (corpus_query / corpus_retrieve) stay lock-free.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: FastMCP lifespan hook for agent shutdown

**Files:**
- Modify: `src/fireflyframework_agentic/exposure/mcp/server.py`
- Modify: `examples/corpus_search/mcp_server.py`

- [ ] **Step 5.1: Write the failing test**

Append to `tests/unit/tools/builtins/test_corpus_rag_registry.py`:

```python
@pytest.mark.asyncio
async def test_create_mcp_app_accepts_lifespan() -> None:
    """create_mcp_app must accept a lifespan and pass it to FastMCP."""
    from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
    from fireflyframework_agentic.tools.registry import ToolRegistry

    fired: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        fired.append("startup")
        try:
            yield
        finally:
            fired.append("shutdown")

    app = create_mcp_app(name="test", registry=ToolRegistry(), lifespan=lifespan)
    # Drive the lifespan manually — FastMCP exposes it as `.lifespan`.
    async with app.lifespan(app):
        assert fired == ["startup"]
    assert fired == ["startup", "shutdown"]
```

- [ ] **Step 5.2: Run test to verify it fails**

```bash
uv run pytest tests/unit/tools/builtins/test_corpus_rag_registry.py::test_create_mcp_app_accepts_lifespan -v
```
Expected: FAIL — `create_mcp_app` does not accept `lifespan`.

- [ ] **Step 5.3: Add `lifespan` param to `create_mcp_app`**

In `src/fireflyframework_agentic/exposure/mcp/server.py`:

```python
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

from fastmcp import FastMCP


def create_mcp_app(
    *,
    name: str = "firefly",
    version: str = "0.1.0",
    registry: ToolRegistry | None = None,
    lifespan: Callable[[FastMCP], AbstractAsyncContextManager[None]] | None = None,
) -> FastMCP:
    """..."""
    del version
    mcp_kwargs: dict[str, Any] = {}
    if lifespan is not None:
        mcp_kwargs["lifespan"] = lifespan
    mcp: FastMCP = FastMCP(name, **mcp_kwargs)
    reg = registry if registry is not None else tool_registry
    for info in reg.list_tools():
        tool = reg.get(info.name)
        _register_tool(mcp, tool)
    return mcp
```

(Add `from typing import Any` if not already imported.)

- [ ] **Step 5.4: Run the lifespan test to verify it passes**

```bash
uv run pytest tests/unit/tools/builtins/test_corpus_rag_registry.py::test_create_mcp_app_accepts_lifespan -v
```
Expected: PASS.

- [ ] **Step 5.5: Wire the lifespan in the MCP server script**

In `examples/corpus_search/mcp_server.py`, modify `main()`:

```python
import contextlib
from collections.abc import AsyncIterator

from fastmcp import FastMCP

from fireflyframework_agentic.tools.builtins.corpus_rag import _shutdown_agents


@contextlib.asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncIterator[None]:
    log = logging.getLogger("firefly.mcp_server")
    try:
        yield
    finally:
        log.info("shutting down — closing %d cached corpus agents", 0)  # see below
        await _shutdown_agents()
```

In `main()`, replace the `create_mcp_app(...)` call with:

```python
app = create_mcp_app(name="firefly-corpus", registry=_build_registry(), lifespan=_lifespan)
```

- [ ] **Step 5.6: Smoke-test the script still launches**

```bash
timeout 3 /Users/javi/.local/bin/uv --directory /Users/javi/work/fireflyframework-agentic \
    run python examples/corpus_search/mcp_server.py 2>&1 | head -15
```
Expected: log lines including "starting firefly corpus_rag MCP server" within 3s, then SIGTERM. No tracebacks.

- [ ] **Step 5.7: Commit**

```bash
git add src/fireflyframework_agentic/exposure/mcp/server.py \
        examples/corpus_search/mcp_server.py \
        tests/unit/tools/builtins/test_corpus_rag_registry.py
git commit -m "feat(mcp): close cached corpus agents on FastMCP lifespan exit

create_mcp_app now accepts an optional lifespan async context manager
and passes it to FastMCP. examples/corpus_search/mcp_server.py wires a
lifespan that calls _shutdown_agents() on shutdown so cached agents
close their SQLite connections cleanly when Claude Desktop disconnects.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `ingest_corpus_filesystem` skips tabular files

**Files:**
- Modify: `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`
- Test: `tests/unit/tools/builtins/test_corpus_rag.py` (or new test file if absent)

- [ ] **Step 6.1: Locate or create a tool-level test file**

```bash
ls tests/unit/tools/builtins/test_corpus_rag*.py
```

If none exists for tool-body behaviour, append the test below to `test_corpus_rag_registry.py` (we already created it). Otherwise add to the existing file.

- [ ] **Step 6.2: Write the failing test**

```python
@pytest.mark.asyncio
async def test_ingest_corpus_filesystem_skips_tabular_files(tmp_path: Path, monkeypatch) -> None:
    """ingest_corpus_filesystem should leave CSV/XLSX to ingest_corpus_structured."""
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "deck.md").write_text("hello")
    (drop / "rows.csv").write_text("a,b\n1,2\n")
    (drop / "sheet.xlsx").write_bytes(b"PK\x03\x04")

    captured: dict[str, Any] = {}

    class _StubAgent:
        async def ingest_source(self, source):
            captured["source"] = source
            class _S:
                results: list = []
                ingested = skipped = failed = 0
                cursor = None
            return _S()
        async def close(self):
            pass

    monkeypatch.setitem(corpus_rag._AGENT_CACHE, "T", _StubAgent())

    await corpus_rag.ingest_corpus_filesystem(corpus_id="T", root_path=str(drop))

    # The source's exclude_predicate should drop CSV/XLSX from the iterator.
    source = captured["source"]
    names = sorted([rf.name async for rf in source.list_changed(since=None)])
    assert names == ["deck.md"]
```

- [ ] **Step 6.3: Run test to verify it fails**

```bash
uv run pytest tests/unit/tools/builtins/test_corpus_rag_registry.py::test_ingest_corpus_filesystem_skips_tabular_files -v
```
Expected: FAIL — current `ingest_corpus_filesystem` doesn't pass an `exclude_predicate`.

- [ ] **Step 6.4: Implement**

In `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`, edit `ingest_corpus_filesystem`:

```python
from fireflyframework_agentic.rag.ingest.structured_registry import is_tabular_file


async def ingest_corpus_filesystem(corpus_id: str, root_path: str) -> dict[str, Any]:
    async with _write_lock_for(corpus_id):
        agent = await _agent_for(corpus_id)
        source = LocalFolderSource(
            LocalFolderSourceConfig(
                folder=Path(root_path),
                exclude_predicate=is_tabular_file,
            )
        )
        summary = await agent.ingest_source(source)
        # ... existing return shape unchanged
```

(Keep the surrounding result-building untouched — only the source construction and the lock wrapper change.)

- [ ] **Step 6.5: Run all corpus_rag tests**

```bash
uv run pytest tests/unit/tools/builtins/ -v
```
Expected: all green.

- [ ] **Step 6.6: Commit**

```bash
git add src/fireflyframework_agentic/tools/builtins/corpus_rag.py \
        tests/unit/tools/builtins/test_corpus_rag_registry.py
git commit -m "fix(mcp): ingest_corpus_filesystem skips files handled by structured ingest

CSV / XLS / XLSX in the drop folder go to ingest_corpus_structured, not
markitdown. Without this, the same row landed twice (once as a text
chunk, once as a SQL row), confusing query-time grounding.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Integration test — parallel ingest does not corrupt the SQLite file

**Why last:** This is the regression for the original bug. It needs every prior fix to pass.

**Files:**
- Test: `tests/integration/test_mcp_corpus_concurrency.py` (new)

- [ ] **Step 7.1: Write the failing test**

Create `tests/integration/test_mcp_corpus_concurrency.py`:

```python
"""End-to-end regression for parallel MCP tool calls on the same corpus.

This test exercises the real CorpusAgent + DatabaseStore + structured
pipeline against a real on-disk SQLite file. It mocks only the embedding
provider (to keep CI hermetic and fast) and the LLM-backed schema-discovery
agent (we pre-supply a TargetSchema). Everything else is live code.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.tools.builtins import corpus_rag


pytestmark = pytest.mark.integration


class _StubEmbedder:
    async def embed(self, texts, **_kwargs):
        return EmbeddingResult(
            embeddings=[[0.0, 0.0, 0.0, 0.0] for _ in texts],
            model="stub", usage=None, dimensions=4,
        )

    async def embed_one(self, _text, **_kwargs):
        return [0.0, 0.0, 0.0, 0.0]


class _StubVectorStore:
    def __init__(self) -> None:
        self.docs: dict[str, Any] = {}

    async def upsert(self, documents, _namespace="default"):
        for d in documents:
            self.docs[d.id] = d

    async def delete(self, ids, _namespace="default"):
        for i in ids:
            self.docs.pop(i, None)


@pytest.fixture
def drop_folder(tmp_path: Path) -> Path:
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "doc.md").write_text("# Title\n\nSome words.\n")
    (drop / "doc2.md").write_text("# Other\n\nMore words.\n")
    (drop / "rows.csv").write_text("id,amount\n1,9.99\n2,19.99\n3,29.99\n")
    return drop


@pytest.fixture(autouse=True)
def _isolated_corpus_root(monkeypatch, tmp_path: Path):
    corpus_rag._AGENT_CACHE.clear()
    corpus_rag._WRITE_LOCKS.clear()
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "corpora"))
    monkeypatch.setenv("EMBEDDING_MODEL", "openai:text-embedding-3-small")
    monkeypatch.setenv("EXPANSION_MODEL", "anthropic:claude-haiku-3-5")
    monkeypatch.setenv("ANSWER_MODEL", "anthropic:claude-haiku-3-5")
    monkeypatch.setenv("RERANK_MODEL", "anthropic:claude-haiku-3-5")
    yield
    asyncio.run(corpus_rag._shutdown_agents())


def _stub_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="rows",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_),
                ],
            )
        ]
    )


@pytest.mark.asyncio
async def test_parallel_filesystem_and_structured_ingest_do_not_corrupt(drop_folder: Path) -> None:
    """The bug fixed by this PR: running structured + filesystem ingest in
    parallel against the same corpus used to produce 'database disk image
    is malformed' and partial writes. After the fix, both succeed and the
    SQLite file passes integrity_check."""

    # Inject the stub embedder/vector store on the cached agent so the test
    # doesn't need real Azure / OpenAI calls.
    agent = await corpus_rag._agent_for("regression")
    agent._embedder = _StubEmbedder()
    agent._vector_store = _StubVectorStore()

    schema = _stub_schema()
    with patch(
        "fireflyframework_agentic.rag.agent.discover_schema_for_paths",
        new=AsyncMock(return_value=schema),
    ):
        results = await asyncio.gather(
            corpus_rag.ingest_corpus_filesystem(
                corpus_id="regression", root_path=str(drop_folder),
            ),
            corpus_rag.ingest_corpus_structured(
                corpus_id="regression", path=str(drop_folder),
                schema=schema.model_dump(mode="json"),
            ),
        )

    fs_result, st_result = results
    assert fs_result["failed"] == 0
    assert st_result["failed"] == 0

    db_path = Path(corpus_rag._corpus_root()) / "regression" / "corpus.sqlite"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        assert integrity == ("ok",)
        chunks = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        rows = conn.execute("SELECT count(*) FROM rows").fetchone()[0]
        assert chunks > 0, "filesystem ingest produced no chunks"
        assert rows == 3, f"structured ingest produced {rows} rows, expected 3"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_parallel_writes_on_different_corpora_are_independent(drop_folder: Path) -> None:
    """Two corpora can write in parallel without serialising on each other."""

    a = await corpus_rag._agent_for("alpha")
    a._embedder, a._vector_store = _StubEmbedder(), _StubVectorStore()
    b = await corpus_rag._agent_for("beta")
    b._embedder, b._vector_store = _StubEmbedder(), _StubVectorStore()

    schema = _stub_schema()
    with patch(
        "fireflyframework_agentic.rag.agent.discover_schema_for_paths",
        new=AsyncMock(return_value=schema),
    ):
        await asyncio.gather(
            corpus_rag.ingest_corpus_filesystem(corpus_id="alpha", root_path=str(drop_folder)),
            corpus_rag.ingest_corpus_filesystem(corpus_id="beta", root_path=str(drop_folder)),
        )

    for cid in ("alpha", "beta"):
        db = Path(corpus_rag._corpus_root()) / cid / "corpus.sqlite"
        assert db.exists()
        conn = sqlite3.connect(db)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        finally:
            conn.close()
```

- [ ] **Step 7.2: Run integration tests**

```bash
uv run pytest tests/integration/test_mcp_corpus_concurrency.py -v -m integration
```
Expected: 2 passed.

If they fail, the failure points at which prior task didn't land properly — diagnose before continuing.

- [ ] **Step 7.3: Run the full unit + integration suite**

```bash
uv run pytest tests/unit/ tests/integration/test_mcp_corpus_concurrency.py -q
```
Expected: all green. No flaky tests.

- [ ] **Step 7.4: Commit**

```bash
git add tests/integration/test_mcp_corpus_concurrency.py
git commit -m "test(integration): regression for parallel MCP corpus ingest

Reproduces the demo-time bug: running structured + filesystem ingest in
parallel against the same corpus used to produce 'database disk image
is malformed' and partial writes. Asserts both finish cleanly and
PRAGMA integrity_check returns ok. Also covers the cross-corpus
independence case (different corpus_ids don't serialise on each other).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Update PR description and push

- [ ] **Step 8.1: Push the commits**

```bash
git push origin fix/mcp-demo-findings
```

- [ ] **Step 8.2: Update the PR body**

```bash
gh pr edit 123 --body "$(cat <<'EOF'
## Summary
Two fixes from a Claude Desktop MCP demo, packaged together.

### 1. Folder-mode discovery filters to tabular files (initial commits)
- `discover_corpus_schema` and `ingest_corpus_structured` (folder mode) now skip non-tabular files (PPTX, PDF, DOCX, …) so a mixed drop folder doesn't crash schema discovery with `UnicodeDecodeError`.
- `_csv_sample` opens with explicit UTF-8 + a Latin-1 / CP1252 hint when decoding fails.

### 2. Parallel-safe MCP corpus access (new commits)
- Process-wide `_AGENT_CACHE`: every tool call against a `corpus_id` shares one `CorpusAgent` / `DatabaseStore` / `LocalBackend`, so the asyncio.Lock inside the backend actually coordinates writers.
- Per-corpus `_WRITE_LOCKS` at the tool layer: belt-and-braces serialisation for write tools; reads stay lock-free.
- `ingest_structured` goes through `db_store.for_write()` instead of opening a raw `sqlite3.connect(db_path)` — fixes the "database disk image is malformed" error during parallel calls.
- `_sync_ingest_table` sets `timeout=30` + `PRAGMA busy_timeout = 30000`.
- `ingest_corpus_filesystem` skips CSV / XLS / XLSX (handled by `ingest_corpus_structured`) via a new `LocalFolderSourceConfig.exclude_predicate`.
- FastMCP lifespan hook closes cached agents on shutdown (`create_mcp_app(*, lifespan=...)`).

## Why
Surfaced live during a Claude Desktop demo:
- Mixed drop folder of 2 PPTX + 2 XLSX → schema discovery exploded with `UnicodeDecodeError` from a PPTX byte read as a CSV.
- Parallel `ingest_corpus_filesystem` + `ingest_corpus_structured` produced "database disk image is malformed", 25 k partial rows, and 0 unstructured chunks.

## Test plan
- [x] `uv run pytest tests/unit/rag tests/unit/corpus_search tests/unit/tools tests/unit/content tests/unit/exposure -q` — all green
- [x] `uv run pytest tests/integration/test_mcp_corpus_concurrency.py -v -m integration` — 2 passed
- [ ] Manual: from Claude Desktop, fire `ingest_corpus_filesystem` and `ingest_corpus_structured` *in parallel* on `drop/mcp-test/`. Both succeed; `PRAGMA integrity_check` returns `ok`; PPTXs become chunks, XLSXs become SQL tables, no double-representation.

## Specs
- `docs/superpowers/specs/2026-05-08-mcp-corpus-concurrency-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8.3: Print PR URL**

```bash
gh pr view 123 --json url -q .url
```

---

## Self-review

**Spec coverage check** (against `2026-05-08-mcp-corpus-concurrency-design.md`):
- §Architecture — `_AGENT_CACHE`, `_WRITE_LOCKS`, `for_write` routing → Tasks 3, 4. ✅
- §Components 1 (registry) → Task 4. ✅
- §Components 2 (lifespan) → Task 5. ✅
- §Components 3 (structured pipeline) → Tasks 2, 3. ✅
- §Components 4 (filesystem skips tabular) → Tasks 1, 6. ✅
- §Testing (unit) → Tasks 1, 2, 3, 4, 5, 6. ✅
- §Testing (integration) → Task 7. ✅
- §Migration / compatibility (signature change cascade) → Task 3 step 3.6. ✅

**Type / signature consistency:**
- `_agent_for` is async everywhere it's called (Tasks 4, 6, 7). ✅
- `ingest_structured(path, db_store, schema)` signature matches caller updates in Tasks 3 + 7. ✅
- `LocalFolderSourceConfig.exclude_predicate` typed `Callable[[Path], bool] | None` everywhere it's referenced. ✅
- `_shutdown_agents` is async; called from a sync `atexit`-style wrapper in Task 5 lifespan (uses `await` inside async cm). ✅

**Placeholder scan:** None found.

**Scope check:** One spec, one PR, ~8 commits including the integration test. No additional decomposition needed.
