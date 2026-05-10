# CorpusAgent + ContentSource Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PR #103's `tools/builtins/sharepoint_rag.py` with a thin composition over a library-grade `CorpusAgent` that accepts any `ContentSource` (filesystem or SharePoint).

**Architecture:** Move `CorpusAgent` and `AnswerAgent` from `examples/corpus_search/` into `src/fireflyframework_agentic/rag/`. Add `LocalFolderSource` so filesystem ingestion uses the same `ContentSource` Protocol as SharePoint. Reshape ingest API around `ingest_source(source)`; split query API into `retrieve()` (no LLM) and `query()` (full pipeline with citations). Build four MCP tools in `tools/builtins/corpus_rag.py` that construct a fresh `CorpusAgent` per call from on-disk state.

**Tech Stack:** Python 3.12, `uv`, FastAPI/MCP, SqliteCorpus + SqliteVec, OpenTelemetry, pytest with `pytest-asyncio`. Branch: `javi/corpus-agent-content-source` (off `main`).

**Reference spec:** `docs/superpowers/specs/2026-05-05-corpus-agent-content-source-design.md`

---

## Conventions

- All commits go to the current branch (`javi/corpus-agent-content-source`). Do not push to `main`.
- After each step that changes code, run `uv run pytest <relevant tests> -v` and confirm green before committing.
- Keep `pre-commit` hooks active (ruff, end-of-file-fixer, etc.). Never skip with `--no-verify`.
- Follow the repo CLAUDE.md: never reference customer-specific corpus content in commit messages or code comments.

---

## Phase 1 — Move CorpusAgent + AnswerAgent into the library

After this phase, the library is the canonical home for both classes. Existing example code keeps working via thin re-export modules; existing tests are updated to point at the new module paths.

### Task 1: Move `AnswerAgent` to `src/fireflyframework_agentic/rag/retrieval/answerer.py`

**Files:**
- Create: `src/fireflyframework_agentic/rag/retrieval/answerer.py` (copy of old)
- Modify: `examples/corpus_search/retrieval/answerer.py` (replace with re-export)
- Modify: `src/fireflyframework_agentic/rag/retrieval/__init__.py` (add exports)
- Modify: `examples/corpus_search/retrieval/__init__.py` (no behaviour change, but verify it still re-exports cleanly)
- Modify (test patches): `tests/examples/corpus_search/test_answerer.py`, `tests/examples/corpus_search/test_agent.py`, `tests/examples/corpus_search/test_query_path.py`

- [ ] **Step 1: Copy module body to new path**

```bash
cp examples/corpus_search/retrieval/answerer.py src/fireflyframework_agentic/rag/retrieval/answerer.py
```

- [ ] **Step 2: Replace the old example file with a re-export**

Overwrite `examples/corpus_search/retrieval/answerer.py` with:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Re-export shim. The canonical home is
``fireflyframework_agentic.rag.retrieval.answerer``. This shim exists so
the example's CLI and historical test imports keep working unchanged.
New code should import from the library path.
"""

from __future__ import annotations

from fireflyframework_agentic.rag.retrieval.answerer import (
    Answer,
    AnswerAgent,
    CitedSource,
    format_chunks_for_prompt,
)

__all__ = ["Answer", "AnswerAgent", "CitedSource", "format_chunks_for_prompt"]
```

- [ ] **Step 3: Add the new symbols to the library `retrieval/__init__.py`**

Modify `src/fireflyframework_agentic/rag/retrieval/__init__.py` so `Answer`, `AnswerAgent`, `CitedSource`, `format_chunks_for_prompt` are re-exported from the canonical library path. Final file:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from fireflyframework_agentic.rag.retrieval.answerer import (
    Answer,
    AnswerAgent,
    CitedSource,
    format_chunks_for_prompt,
)
from fireflyframework_agentic.rag.retrieval.expander import QueryExpander
from fireflyframework_agentic.rag.retrieval.hybrid import HybridRetriever, reciprocal_rank_fusion
from fireflyframework_agentic.rag.retrieval.reranker import HaikuReranker, RerankerResult

__all__ = [
    "Answer",
    "AnswerAgent",
    "CitedSource",
    "HaikuReranker",
    "HybridRetriever",
    "QueryExpander",
    "RerankerResult",
    "format_chunks_for_prompt",
    "reciprocal_rank_fusion",
]
```

- [ ] **Step 4: Update test patch paths**

Tests currently patch `examples.corpus_search.retrieval.answerer.FireflyAgent`. After the move, the patch must target the canonical module — patching the shim has no effect because `AnswerAgent.answer` calls `FireflyAgent` from its own module's namespace, which is the library path.

Run a global replacement across `tests/examples/corpus_search/`:

```bash
grep -rl "examples.corpus_search.retrieval.answerer.FireflyAgent" tests/examples/corpus_search/ \
  | xargs sed -i '' 's#examples\.corpus_search\.retrieval\.answerer\.FireflyAgent#fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent#g'
```

(Note: `sed -i ''` is the BSD/macOS form; on Linux drop the `''`.)

- [ ] **Step 5: Run answerer + agent + query-path tests**

```bash
uv run pytest tests/examples/corpus_search/test_answerer.py \
              tests/examples/corpus_search/test_agent.py \
              tests/examples/corpus_search/test_query_path.py -v
```

Expected: all green. If a test fails because of a missed patch path, fix the offender; do not move on with reds.

- [ ] **Step 6: Commit**

```bash
git add src/fireflyframework_agentic/rag/retrieval/answerer.py \
        src/fireflyframework_agentic/rag/retrieval/__init__.py \
        examples/corpus_search/retrieval/answerer.py \
        tests/examples/corpus_search/
git commit -m "refactor(rag): move AnswerAgent into the library"
```

---

### Task 2: Move `CorpusAgent` to `src/fireflyframework_agentic/rag/agent.py`

**Files:**
- Create: `src/fireflyframework_agentic/rag/agent.py` (copy of old, with import paths fixed)
- Modify: `examples/corpus_search/agent.py` (replace with re-export)
- Modify: `src/fireflyframework_agentic/rag/__init__.py` (add `CorpusAgent` export)
- Modify (test imports): `tests/examples/corpus_search/test_agent.py`, `test_query_path.py`, `test_e2e_real_llm.py`

- [ ] **Step 1: Copy module body to new path**

```bash
cp examples/corpus_search/agent.py src/fireflyframework_agentic/rag/agent.py
```

- [ ] **Step 2: Fix imports inside the new file**

In `src/fireflyframework_agentic/rag/agent.py`, replace the line

```python
from examples.corpus_search.retrieval.answerer import Answer, AnswerAgent
```

with

```python
from fireflyframework_agentic.rag.retrieval.answerer import Answer, AnswerAgent
```

The other imports (`MarkitdownLoader`, `MarkdownChunker`, `FolderWatcher`, retrieval components, telemetry) already point at library paths — leave them.

- [ ] **Step 3: Replace the old example agent with a re-export**

Overwrite `examples/corpus_search/agent.py` with:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Re-export shim. The canonical home is
``fireflyframework_agentic.rag.agent``. New code should import from there.
"""

from __future__ import annotations

from fireflyframework_agentic.rag.agent import CorpusAgent

__all__ = ["CorpusAgent"]
```

- [ ] **Step 4: Add `CorpusAgent` to the library `rag/__init__.py`**

Final file (preserves the existing exports if any; today the file is empty other than the licence):

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from fireflyframework_agentic.rag.agent import CorpusAgent

__all__ = ["CorpusAgent"]
```

- [ ] **Step 5: Update test imports that point at the example path**

Three tests import `CorpusAgent` from the example module. Switch them to the library path:

```bash
grep -rl "from examples.corpus_search.agent import CorpusAgent" tests/examples/corpus_search/ \
  | xargs sed -i '' 's#from examples\.corpus_search\.agent import CorpusAgent#from fireflyframework_agentic.rag.agent import CorpusAgent#g'
```

- [ ] **Step 6: Run the full corpus_search test set**

```bash
uv run pytest tests/examples/corpus_search/ -v
```

Expected: all green. The shim modules at `examples/corpus_search/{agent.py,retrieval/answerer.py}` keep historical imports working; tests now exercise the library directly.

- [ ] **Step 7: Verify the example CLI still imports clean**

```bash
uv run python -c "from examples.corpus_search.cli import build_arg_parser; build_arg_parser()"
```

Expected: no output, exit 0.

- [ ] **Step 8: Commit**

```bash
git add src/fireflyframework_agentic/rag/agent.py \
        src/fireflyframework_agentic/rag/__init__.py \
        examples/corpus_search/agent.py \
        tests/examples/corpus_search/
git commit -m "refactor(rag): move CorpusAgent into the library"
```

---

## Phase 2 — Source abstraction

### Task 3: Add `LocalFolderSource`

**Files:**
- Create: `src/fireflyframework_agentic/content/sources/local_folder.py`
- Create: `tests/unit/content/sources/test_local_folder.py`
- Modify: `src/fireflyframework_agentic/content/sources/__init__.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/content/sources/test_local_folder.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for LocalFolderSource."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_lists_files_recursively(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "hello")
    _write(tmp_path / "sub" / "b.md", "world")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))

    raws = [r async for r in source.list_changed(None)]
    names = sorted(r.name for r in raws)
    assert names == ["a.md", "b.md"]


@pytest.mark.asyncio
async def test_skips_hidden_files_by_default(tmp_path: Path) -> None:
    _write(tmp_path / "visible.md", "x")
    _write(tmp_path / ".hidden.md", "x")
    _write(tmp_path / ".DS_Store", "")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))

    raws = [r async for r in source.list_changed(None)]
    assert [r.name for r in raws] == ["visible.md"]


@pytest.mark.asyncio
async def test_includes_hidden_when_requested(tmp_path: Path) -> None:
    _write(tmp_path / ".hidden.md", "x")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path, include_hidden=True))

    raws = [r async for r in source.list_changed(None)]
    assert [r.name for r in raws] == [".hidden.md"]


@pytest.mark.asyncio
async def test_etag_stable_when_file_unchanged(tmp_path: Path) -> None:
    f = _write(tmp_path / "a.md", "hello")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))

    first = [r async for r in source.list_changed(None)]
    second = [r async for r in source.list_changed(None)]
    assert first[0].etag == second[0].etag
    # mtime+size combination changes when content changes
    f.write_text("hello world", encoding="utf-8")
    third = [r async for r in source.list_changed(None)]
    assert third[0].etag != first[0].etag


@pytest.mark.asyncio
async def test_fetch_returns_path_unchanged(tmp_path: Path) -> None:
    f = _write(tmp_path / "a.md", "hello")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))

    raws = [r async for r in source.list_changed(None)]
    fetched = await source.fetch(raws[0])
    assert fetched == f.resolve()


@pytest.mark.asyncio
async def test_cursor_methods_are_noops(tmp_path: Path) -> None:
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))
    assert await source.current_cursor() is None
    assert await source.pending_cursor() is None
    await source.commit_delta("anything")  # must not raise


@pytest.mark.asyncio
async def test_source_id_is_kind_prefixed(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "x")
    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))
    raws = [r async for r in source.list_changed(None)]
    assert raws[0].source_id.startswith("local:")


@pytest.mark.asyncio
async def test_satisfies_content_source_protocol(tmp_path: Path) -> None:
    from fireflyframework_agentic.content.sources import ContentSource

    source = LocalFolderSource(LocalFolderSourceConfig(folder=tmp_path))
    assert isinstance(source, ContentSource)
```

- [ ] **Step 2: Verify tests fail (red)**

```bash
uv run pytest tests/unit/content/sources/test_local_folder.py -v
```

Expected: ImportError or `AttributeError` because `local_folder` module / classes don't exist yet.

- [ ] **Step 3: Implement `LocalFolderSource`**

Create `src/fireflyframework_agentic/content/sources/local_folder.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Filesystem :class:`ContentSource` — yields files under a local folder.

Mirrors the cursor-based contract of remote sources (SharePoint, S3) so a
single ingest pipeline can serve both local and remote corpora. v1 is
delta-less: every call to :meth:`list_changed` lists everything under the
folder. The :class:`fireflyframework_agentic.rag.ingest.ledger.IngestLedger`
already dedupes by content hash so re-listing is cheap; mtime-based delta
is a future enhancement.
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from fireflyframework_agentic.content.sources.base import RawFile
from fireflyframework_agentic.pipeline.triggers.folder_watcher import FolderWatcher

logger = logging.getLogger(__name__)


class LocalFolderSourceConfig(BaseModel):
    folder: Path
    include_hidden: bool = Field(
        default=False,
        description="When False (default), files whose name begins with '.' are skipped.",
    )


class LocalFolderSource:
    """A :class:`ContentSource` over a local directory tree."""

    def __init__(self, config: LocalFolderSourceConfig) -> None:
        self._folder = Path(config.folder).resolve()
        self._include_hidden = config.include_hidden
        self._watcher = FolderWatcher(folder=self._folder)

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:  # noqa: ARG002
        # ``since`` is intentionally unused in v1 — see module docstring.
        for path in sorted(self._folder.rglob("*")):
            if not path.is_file():
                continue
            if not self._include_hidden and self._watcher.is_hidden(path):
                continue
            try:
                stat = path.stat()
            except OSError as exc:
                logger.warning("stat failed for %s: %s", path, exc)
                continue
            rel = path.relative_to(self._folder).as_posix()
            mime_type, _ = mimetypes.guess_type(path.name)
            yield RawFile(
                source_id=f"local:{self._folder}/{rel}",
                name=path.name,
                mime_type=mime_type or "",
                size_bytes=stat.st_size,
                etag=f"{stat.st_mtime_ns}:{stat.st_size}",
                fetched_at=datetime.now(UTC),
                metadata={"absolute_path": str(path.resolve()), "relative_path": rel},
            )

    async def fetch(self, file: RawFile) -> Path:
        return Path(file.metadata["absolute_path"])

    async def current_cursor(self) -> str | None:
        return None

    async def pending_cursor(self) -> str | None:
        return None

    async def commit_delta(self, cursor: str) -> None:  # noqa: ARG002
        return None
```

- [ ] **Step 4: Export from the package**

Modify `src/fireflyframework_agentic/content/sources/__init__.py` to add `LocalFolderSource` and `LocalFolderSourceConfig`:

```python
# (preserve existing licence header)

from __future__ import annotations

from fireflyframework_agentic.content.sources.base import ContentSource, RawFile
from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)
from fireflyframework_agentic.content.sources.s3 import S3Source, S3SourceConfig
from fireflyframework_agentic.content.sources.sharepoint import (
    SharePointSource,
    SharePointSourceConfig,
)

__all__ = [
    "ContentSource",
    "LocalFolderSource",
    "LocalFolderSourceConfig",
    "RawFile",
    "S3Source",
    "S3SourceConfig",
    "SharePointSource",
    "SharePointSourceConfig",
]
```

- [ ] **Step 5: Verify tests pass (green)**

```bash
uv run pytest tests/unit/content/sources/test_local_folder.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/fireflyframework_agentic/content/sources/local_folder.py \
        src/fireflyframework_agentic/content/sources/__init__.py \
        tests/unit/content/sources/test_local_folder.py
git commit -m "feat(content): LocalFolderSource implementing ContentSource"
```

---

### Task 4: Add `IngestSummary` and `CorpusAgent.ingest_source`

**Files:**
- Modify: `src/fireflyframework_agentic/rag/agent.py` (add `IngestSummary`, `ingest_source`)
- Modify: `tests/examples/corpus_search/test_agent.py` (or new `tests/unit/rag/test_corpus_agent.py` for the new method — pick the latter to keep new tests in `tests/unit/rag/`)
- Create: `tests/unit/rag/test_corpus_agent_ingest_source.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/rag/test_corpus_agent_ingest_source.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for CorpusAgent.ingest_source."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.content.sources import ContentSource, RawFile
from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)
from fireflyframework_agentic.rag.agent import CorpusAgent, IngestSummary


class _StubEmbedder:
    """Deterministic 8-dim embedder for tests."""

    dimension = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t) % 7) / 7.0] * self.dimension for t in texts]


class _StubVectorStore:
    def __init__(self) -> None:
        self.documents: list[Any] = []

    async def upsert(self, documents: list[Any]) -> None:
        self.documents.extend(documents)

    async def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def delete_by_doc_id(self, doc_id: str) -> None:
        self.documents = [d for d in self.documents if getattr(d, "doc_id", None) != doc_id]

    async def close(self) -> None:
        return None


class _FakeSource:
    """Minimal in-memory ContentSource that yields supplied RawFile objects."""

    def __init__(self, files: list[tuple[Path, RawFile]]) -> None:
        self._files = files
        self._committed: str | None = None
        self._pending: str | None = "fake-cursor-1"

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:  # noqa: ARG002
        for _, raw in self._files:
            yield raw

    async def fetch(self, file: RawFile) -> Path:
        for path, raw in self._files:
            if raw.source_id == file.source_id:
                return path
        raise KeyError(file.source_id)

    async def current_cursor(self) -> str | None:
        return self._committed

    async def pending_cursor(self) -> str | None:
        return self._pending

    async def commit_delta(self, cursor: str) -> None:
        self._committed = cursor


def _raw(path: Path, source_id: str | None = None) -> RawFile:
    stat = path.stat()
    return RawFile(
        source_id=source_id or f"fake:{path.name}",
        name=path.name,
        mime_type="text/plain",
        size_bytes=stat.st_size,
        etag=f"{stat.st_mtime_ns}:{stat.st_size}",
        fetched_at=datetime.now(UTC),
        metadata={"absolute_path": str(path)},
    )


def _agent(root: Path) -> CorpusAgent:
    return CorpusAgent(
        root=root,
        embed_model="openai:text-embedding-3-small",
        embed_dimension=8,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=_StubEmbedder(),
        _vector_store=_StubVectorStore(),
    )


@pytest.mark.asyncio
async def test_ingest_source_runs_pipeline_and_commits_cursor(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    a = docs_dir / "a.md"
    a.write_text("alpha", encoding="utf-8")
    b = docs_dir / "b.md"
    b.write_text("beta", encoding="utf-8")
    source = _FakeSource([(a, _raw(a)), (b, _raw(b))])

    async with _agent(tmp_path / "corpus") as agent:
        summary = await agent.ingest_source(source)

    assert isinstance(summary, IngestSummary)
    assert summary.ingested == 2
    assert summary.skipped == 0
    assert summary.failed == 0
    assert summary.cursor == "fake-cursor-1"
    assert source._committed == "fake-cursor-1"  # cursor was committed


@pytest.mark.asyncio
async def test_ingest_source_does_not_commit_on_fetch_failure(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")

    class _FailFetch(_FakeSource):
        async def fetch(self, file: RawFile) -> Path:
            raise RuntimeError("boom")

    source = _FailFetch([(a, _raw(a))])

    async with _agent(tmp_path / "corpus") as agent:
        summary = await agent.ingest_source(source)

    assert summary.failed == 1
    assert summary.ingested == 0
    # Per-file fetch failures DO commit the cursor — drained iterator.
    # (Source-level errors that raise out of the iterator should not — covered separately.)
    assert source._committed == "fake-cursor-1"


@pytest.mark.asyncio
async def test_ingest_source_with_local_folder_source(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")
    (docs / "b.md").write_text("beta", encoding="utf-8")

    src = LocalFolderSource(LocalFolderSourceConfig(folder=docs))

    async with _agent(tmp_path / "corpus") as agent:
        summary = await agent.ingest_source(src)

    assert summary.ingested == 2
    assert summary.failed == 0


@pytest.mark.asyncio
async def test_ingest_summary_aggregates(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    source = _FakeSource([(a, _raw(a))])

    async with _agent(tmp_path / "corpus") as agent:
        summary = await agent.ingest_source(source)

    assert summary.results and summary.results[0].status == "success"
    assert summary.ingested == sum(1 for r in summary.results if r.status == "success")
```

- [ ] **Step 2: Run the new tests — they should fail**

```bash
uv run pytest tests/unit/rag/test_corpus_agent_ingest_source.py -v
```

Expected: ImportError on `IngestSummary`, or `AttributeError: ingest_source`.

- [ ] **Step 3: Add `IngestSummary` and `ingest_source` to `CorpusAgent`**

Modify `src/fireflyframework_agentic/rag/agent.py`:

1. Add new top-of-file imports (merge with the existing import block — do not duplicate `from __future__ import annotations` or already-present names):

```python
from dataclasses import dataclass, field

from fireflyframework_agentic.content.sources import ContentSource
```

2. Add the `IngestSummary` dataclass between the imports and `class CorpusAgent`:

```python
@dataclass(slots=True)
class IngestSummary:
    """Aggregate result of an ``ingest_source`` / ``ingest_folder`` run."""

    results: list[IngestionResult] = field(default_factory=list)
    cursor: str | None = None

    @property
    def ingested(self) -> int:
        return sum(1 for r in self.results if r.status == "success")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status not in {"success", "skipped"})
```

3. Add the method to `CorpusAgent` (place it right after `ingest_folder`):

```python
    async def ingest_source(self, source: ContentSource) -> IngestSummary:
        """Pull every changed file from ``source`` and ingest it.

        Drives the unified ContentSource loop:
        ``list_changed`` → per item ``fetch`` → ``ingest_one`` → after the
        iterator drains, ``commit_delta`` with the source's pending cursor.

        Per-file fetch / ingest errors are logged and counted in the
        returned :class:`IngestSummary`; they do not interrupt iteration.
        Source-level errors (auth, network, malformed cursor) propagate.
        """
        await self._ensure_corpus_ready()
        assert self._ledger is not None

        results: list[IngestionResult] = []
        cursor = await source.current_cursor()

        async for raw in source.list_changed(cursor):
            try:
                local_path = await source.fetch(raw)
            except Exception as exc:  # noqa: BLE001 — per-file isolation
                log.warning("fetch failed for %s: %s", raw.source_id, exc)
                results.append(
                    IngestionResult(
                        doc_id=raw.source_id,
                        source_path=raw.source_id,
                        status="failed",
                        n_chunks=0,
                    )
                )
                continue

            results.append(await self.ingest_one(local_path))

        new_cursor = await source.pending_cursor()
        if new_cursor:
            await source.commit_delta(new_cursor)

        return IngestSummary(results=results, cursor=new_cursor)
```

4. Export `IngestSummary` in `src/fireflyframework_agentic/rag/__init__.py`:

```python
from fireflyframework_agentic.rag.agent import CorpusAgent, IngestSummary

__all__ = ["CorpusAgent", "IngestSummary"]
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/unit/rag/test_corpus_agent_ingest_source.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full corpus_search suite to confirm no regressions**

```bash
uv run pytest tests/examples/corpus_search/ tests/unit/content/sources/ tests/unit/rag/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/fireflyframework_agentic/rag/agent.py \
        src/fireflyframework_agentic/rag/__init__.py \
        tests/unit/rag/test_corpus_agent_ingest_source.py
git commit -m "feat(rag): CorpusAgent.ingest_source + IngestSummary"
```

---

### Task 5: Refactor `CorpusAgent.ingest_folder` to wrap `LocalFolderSource`

**Files:**
- Modify: `src/fireflyframework_agentic/rag/agent.py` (replace `ingest_folder` body)
- Modify (if needed): `examples/corpus_search/cli.py` (callers expecting `list[IngestionResult]`)
- Modify: `tests/examples/corpus_search/test_agent.py` (assertions on `ingest_folder` return type)

- [ ] **Step 1: Replace `ingest_folder` to delegate to `ingest_source`**

In `src/fireflyframework_agentic/rag/agent.py`, replace the existing `ingest_folder` body with:

```python
    async def ingest_folder(self, folder: Path) -> IngestSummary:
        """Recursively ingest every (non-hidden) file under ``folder``.

        Thin wrapper around :meth:`ingest_source` using a
        :class:`LocalFolderSource`. Hidden files (``.DS_Store``, editor swap
        files, dotfiles) are skipped — same rule the watcher applies.
        """
        from fireflyframework_agentic.content.sources.local_folder import (
            LocalFolderSource,
            LocalFolderSourceConfig,
        )

        source = LocalFolderSource(LocalFolderSourceConfig(folder=Path(folder)))
        return await self.ingest_source(source)
```

The old span (`corpus_search.ingest_folder`) is removed here — `ingest_source` will get its own span in Task 10 once we rename the prefix.

- [ ] **Step 2: Update callers expecting `list[IngestionResult]`**

Find callers:

```bash
grep -rn "ingest_folder" examples/ tests/ src/ | grep -v "def ingest_folder"
```

For each call site, adapt to the new return type. Typical call site change:

```python
# Before
results = await agent.ingest_folder(folder)
print(f"ingested {sum(1 for r in results if r.status == 'success')} files")

# After
summary = await agent.ingest_folder(folder)
print(f"ingested {summary.ingested} files")
```

`tests/examples/corpus_search/test_agent.py` likely asserts `len(results) == N` and `r.status == "success"`. Replace with `summary.results` access:

```python
summary = await agent.ingest_folder(tmp_path)
assert summary.ingested == N
assert all(r.status == "success" for r in summary.results)
```

`examples/corpus_search/cli.py` ingestion command similarly: prints from `.ingested` / `.failed` / `.skipped` properties.

- [ ] **Step 3: Run the full corpus_search + new RAG tests**

```bash
uv run pytest tests/examples/corpus_search/ tests/unit/rag/ tests/unit/content/sources/ -v
```

Expected: all green. If any test fails because it asserted on the old `list[IngestionResult]` shape, update the assertion to access `.results` / `.ingested` / etc.

- [ ] **Step 4: Verify the example CLI still runs end-to-end on a fixture folder**

```bash
mkdir -p /tmp/ingest_smoke && echo "hello" > /tmp/ingest_smoke/a.md
uv run python -m examples.corpus_search ingest \
  --folder /tmp/ingest_smoke --root /tmp/ingest_smoke_kg \
  --embed-model openai:text-embedding-3-small --embed-dimension 1536
```

Expected: completes, prints a per-stage summary citing 1 ingested file. (Requires `OPENAI_API_KEY`. If not available, skip and rely on the unit tests.)

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/rag/agent.py \
        examples/corpus_search/ \
        tests/examples/corpus_search/
git commit -m "refactor(rag): ingest_folder delegates to ingest_source via LocalFolderSource"
```

---

## Phase 3 — API split

### Task 6: Split `query()` into `retrieve()` and `query()`

**Files:**
- Modify: `src/fireflyframework_agentic/rag/agent.py`
- Create: `tests/unit/rag/test_corpus_agent_retrieve_split.py`
- Modify: `tests/examples/corpus_search/test_query_path.py` if it asserts on internal call counts that change

- [ ] **Step 1: Write failing tests**

Create `tests/unit/rag/test_corpus_agent_retrieve_split.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests asserting `retrieve` and `query` are independent surfaces."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent
from fireflyframework_agentic.rag.corpus import ChunkHit


def _agent(tmp_path: Path) -> CorpusAgent:
    return CorpusAgent(
        root=tmp_path,
        embed_model="openai:text-embedding-3-small",
        embed_dimension=8,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=object(),
        _vector_store=object(),
    )


@pytest.mark.asyncio
async def test_retrieve_does_not_invoke_answer_agent(tmp_path: Path) -> None:
    a = _agent(tmp_path)
    fake_hits = [ChunkHit(chunk_id="c1", content="x", source_path="/p", score=1.0, metadata={})]

    with (
        patch.object(a, "_ensure_query_ready", new=AsyncMock()),
        patch.object(a, "_expander", create=True) as expander,
        patch.object(a, "_retriever", create=True) as retriever,
        patch.object(a, "_reranker", create=True) as reranker,
        patch.object(a, "_answerer", create=True) as answerer,
    ):
        expander.expand = AsyncMock(return_value=["q"])
        retriever.retrieve = AsyncMock(return_value=fake_hits)
        reranker.rerank = AsyncMock(return_value=fake_hits)
        answerer.answer = AsyncMock()

        hits = await a.retrieve("question", top_k=1)

    assert hits == fake_hits
    answerer.answer.assert_not_called()


@pytest.mark.asyncio
async def test_query_calls_answer_agent(tmp_path: Path) -> None:
    from fireflyframework_agentic.rag.retrieval.answerer import Answer

    a = _agent(tmp_path)
    fake_hits = [ChunkHit(chunk_id="c1", content="x", source_path="/p", score=1.0, metadata={})]
    fake_answer = Answer(text="y", citations=[], cited_sources=[])

    with (
        patch.object(a, "_ensure_query_ready", new=AsyncMock()),
        patch.object(a, "_expander", create=True) as expander,
        patch.object(a, "_retriever", create=True) as retriever,
        patch.object(a, "_reranker", create=True) as reranker,
        patch.object(a, "_answerer", create=True) as answerer,
    ):
        expander.expand = AsyncMock(return_value=["q"])
        retriever.retrieve = AsyncMock(return_value=fake_hits)
        reranker.rerank = AsyncMock(return_value=fake_hits)
        answerer.answer = AsyncMock(return_value=fake_answer)

        result = await a.query("question", top_k=1)

    assert result is fake_answer
    answerer.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_skips_reranker_when_disabled(tmp_path: Path) -> None:
    a = _agent(tmp_path)
    fake_hits = [ChunkHit(chunk_id="c1", content="x", source_path="/p", score=1.0, metadata={})]

    with (
        patch.object(a, "_ensure_query_ready", new=AsyncMock()),
        patch.object(a, "_expander", create=True) as expander,
        patch.object(a, "_retriever", create=True) as retriever,
        patch.object(a, "_reranker", create=True) as reranker,
    ):
        expander.expand = AsyncMock(return_value=["q"])
        retriever.retrieve = AsyncMock(return_value=fake_hits)
        reranker.rerank = AsyncMock()

        await a.retrieve("question", top_k=1, rerank=False)

    reranker.rerank.assert_not_called()
```

- [ ] **Step 2: Verify tests fail**

```bash
uv run pytest tests/unit/rag/test_corpus_agent_retrieve_split.py -v
```

Expected: `AttributeError: 'CorpusAgent' object has no attribute 'retrieve'`.

- [ ] **Step 3: Refactor `query()` and add `retrieve()`**

In `src/fireflyframework_agentic/rag/agent.py`, replace the existing `query()` with the pair below:

```python
    async def retrieve(
        self,
        question: str,
        *,
        top_k: int = 5,
        rerank: bool = True,
    ) -> list[ChunkHit]:
        """Run expand → hybrid retrieve → (optional) rerank.

        Returns the ranked chunk hits without invoking the answer LLM. Use
        this when the caller wants to compose its own answer or display raw
        evidence to the user. ``query`` calls into this method.
        """
        await self._ensure_query_ready()
        assert self._expander is not None
        assert self._retriever is not None
        assert self._reranker is not None

        async with timed_span(
            "corpus_search.retrieve",
            attributes={"question": question, "top_k": top_k, "rerank": rerank},
        ):
            queries = await self._expander.expand(question)
            candidates = await self._retriever.retrieve(
                queries,
                top_k_per_query=30,
                top_k_final=self._rerank_pool if rerank else top_k,
            )
            if rerank:
                return await self._reranker.rerank(question, candidates, top_k=top_k)
            return candidates[:top_k]

    async def query(self, question: str, *, top_k: int = 5) -> Answer:
        """Run the full pipeline: retrieve (with rerank) + answer.

        Wraps :meth:`retrieve` with the answerer so callers get a grounded
        answer plus citations in one call. ``top_k`` is the number of
        chunks fed into the answer agent *after* reranking.
        """
        await self._ensure_query_ready()
        assert self._answerer is not None

        query_start = time.perf_counter()
        async with timed_span(
            "corpus_search.query",
            attributes={
                "question": question,
                "top_k": top_k,
                "rerank_pool": self._rerank_pool,
            },
        ) as span:
            top_hits = await self.retrieve(question, top_k=top_k, rerank=True)
            answer = await self._answerer.answer(question, top_hits)
            outcome = "no_info" if not answer.cited_sources else "answered"
            elapsed_ms = (time.perf_counter() - query_start) * 1000.0
            query_total_duration.record(elapsed_ms, {"outcome": outcome})
            span.set_attribute("firefly.rag.citation_count", len(answer.cited_sources))
            span.set_attribute("firefly.rag.outcome", outcome)
            return answer
```

`ChunkHit` is already imported elsewhere in the module; confirm with `grep "ChunkHit" src/fireflyframework_agentic/rag/agent.py`. If not, add `from fireflyframework_agentic.rag.corpus import ChunkHit`.

- [ ] **Step 4: Run the new tests + the example query-path test**

```bash
uv run pytest tests/unit/rag/test_corpus_agent_retrieve_split.py \
              tests/examples/corpus_search/test_query_path.py \
              tests/examples/corpus_search/test_agent.py -v
```

Expected: all green. The `test_query_path.py` already mocks expander / retriever / reranker / answerer; the refactor preserves the chain and call counts so that test should pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/rag/agent.py \
        tests/unit/rag/test_corpus_agent_retrieve_split.py
git commit -m "refactor(rag): split CorpusAgent.query into retrieve() + query()"
```

---

### Task 7: Add `CorpusAgent.watch_source` (polling)

**Files:**
- Modify: `src/fireflyframework_agentic/rag/agent.py`
- Create: `tests/unit/rag/test_corpus_agent_watch_source.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/rag/test_corpus_agent_watch_source.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit test: watch_source polls list_changed at the given interval."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fireflyframework_agentic.content.sources import RawFile
from fireflyframework_agentic.rag.agent import CorpusAgent


class _StubEmbedder:
    dimension = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class _StubVectorStore:
    async def upsert(self, documents: list) -> None:
        pass

    async def search(self, *args, **kwargs) -> list:
        return []

    async def delete_by_doc_id(self, doc_id: str) -> None:
        pass

    async def close(self) -> None:
        pass


class _PollingSource:
    """Yields a different file each tick to verify the polling loop."""

    def __init__(self, files: list[Path]) -> None:
        self._files = list(files)
        self._committed: str | None = None

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:  # noqa: ARG002
        if not self._files:
            return
        path = self._files.pop(0)
        stat = path.stat()
        yield RawFile(
            source_id=f"poll:{path.name}",
            name=path.name,
            mime_type="text/plain",
            size_bytes=stat.st_size,
            etag=f"{stat.st_mtime_ns}:{stat.st_size}",
            fetched_at=datetime.now(UTC),
            metadata={"absolute_path": str(path)},
        )

    async def fetch(self, file: RawFile) -> Path:
        return Path(file.metadata["absolute_path"])

    async def current_cursor(self) -> str | None:
        return self._committed

    async def pending_cursor(self) -> str | None:
        return f"after-{self._committed}"

    async def commit_delta(self, cursor: str) -> None:
        self._committed = cursor


@pytest.mark.asyncio
async def test_watch_source_polls_until_cancelled(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("beta", encoding="utf-8")

    agent = CorpusAgent(
        root=tmp_path / "corpus",
        embed_model="openai:text-embedding-3-small",
        embed_dimension=8,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=_StubEmbedder(),
        _vector_store=_StubVectorStore(),
    )
    source = _PollingSource([a, b])

    seen: list[str] = []
    async with agent:

        async def consume() -> None:
            async for result in agent.watch_source(source, interval=0.01):
                seen.append(result.source_path)
                if len(seen) >= 2:
                    raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await consume()

    assert len(seen) == 2
    # Cursor was committed at least once during the loop
    assert source._committed is not None
```

- [ ] **Step 2: Verify test fails**

```bash
uv run pytest tests/unit/rag/test_corpus_agent_watch_source.py -v
```

Expected: `AttributeError: 'CorpusAgent' object has no attribute 'watch_source'`.

- [ ] **Step 3: Implement `watch_source`**

In `src/fireflyframework_agentic/rag/agent.py`, add right after `ingest_source`:

```python
    async def watch_source(
        self,
        source: ContentSource,
        *,
        interval: float = 60.0,
    ) -> AsyncIterator[IngestionResult]:
        """Poll ``source.list_changed`` on a timer; yield per-file results.

        After each successful drain of the iterator, the source's
        ``pending_cursor`` is committed, so the next tick only sees newly
        changed files. Caller cancels by exiting the iteration (``break``,
        task cancellation, etc.).
        """
        await self._ensure_corpus_ready()
        while True:
            cursor = await source.current_cursor()
            async for raw in source.list_changed(cursor):
                try:
                    local_path = await source.fetch(raw)
                except Exception as exc:  # noqa: BLE001
                    log.warning("fetch failed for %s: %s", raw.source_id, exc)
                    yield IngestionResult(
                        doc_id=raw.source_id,
                        source_path=raw.source_id,
                        status="failed",
                    )
                    continue
                yield await self.ingest_one(local_path)

            new_cursor = await source.pending_cursor()
            if new_cursor:
                await source.commit_delta(new_cursor)

            await asyncio.sleep(interval)
```

`asyncio` is already imported at the top of the module; confirm with `grep "^import asyncio" src/fireflyframework_agentic/rag/agent.py`. If not, add it. Same for `AsyncIterator`.

- [ ] **Step 4: Verify test passes**

```bash
uv run pytest tests/unit/rag/test_corpus_agent_watch_source.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/rag/agent.py \
        tests/unit/rag/test_corpus_agent_watch_source.py
git commit -m "feat(rag): CorpusAgent.watch_source — polling-based source watcher"
```

---

## Phase 4 — MCP surface

### Task 8: Define `CorpusNotFoundError`

**Files:**
- Modify: `src/fireflyframework_agentic/rag/__init__.py`
- Create: `src/fireflyframework_agentic/rag/exceptions.py`
- Create: `tests/unit/rag/test_exceptions.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/rag/test_exceptions.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for CorpusNotFoundError."""

from __future__ import annotations

from fireflyframework_agentic.rag import CorpusNotFoundError


def test_message_includes_corpus_id() -> None:
    err = CorpusNotFoundError("my-corpus", "/tmp/firefly/corpora/my-corpus/corpus.sqlite")
    msg = str(err)
    assert "my-corpus" in msg
    assert "/tmp/firefly/corpora/my-corpus/corpus.sqlite" in msg
```

- [ ] **Step 2: Verify test fails**

```bash
uv run pytest tests/unit/rag/test_exceptions.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/fireflyframework_agentic/rag/exceptions.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""RAG-specific exceptions."""

from __future__ import annotations


class CorpusNotFoundError(LookupError):
    """Raised when a requested corpus has no on-disk SQLite file.

    The MCP retrieval / query tools raise this rather than returning empty
    hits with a warning, so a typo'd corpus_id never silently looks like
    "no relevant chunks".
    """

    def __init__(self, corpus_id: str, expected_path: str) -> None:
        super().__init__(
            f"Corpus {corpus_id!r} not found — no SQLite file at {expected_path!r}. "
            f"Ingest at least one document into this corpus before querying."
        )
        self.corpus_id = corpus_id
        self.expected_path = expected_path
```

- [ ] **Step 4: Re-export from `rag/__init__.py`**

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from fireflyframework_agentic.rag.agent import CorpusAgent, IngestSummary
from fireflyframework_agentic.rag.exceptions import CorpusNotFoundError

__all__ = ["CorpusAgent", "CorpusNotFoundError", "IngestSummary"]
```

- [ ] **Step 5: Verify test passes**

```bash
uv run pytest tests/unit/rag/test_exceptions.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add src/fireflyframework_agentic/rag/exceptions.py \
        src/fireflyframework_agentic/rag/__init__.py \
        tests/unit/rag/test_exceptions.py
git commit -m "feat(rag): CorpusNotFoundError exception"
```

---

### Task 9: Build `tools/builtins/corpus_rag.py` — four MCP tools

**Files:**
- Create: `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`
- Create: `tests/unit/tools/builtins/__init__.py` (if missing)
- Create: `tests/unit/tools/builtins/test_corpus_rag.py`

This is the largest task; split into TDD steps that each make one tool work.

- [ ] **Step 1: Write the test fixture and the first failing test (filesystem ingest)**

Create `tests/unit/tools/builtins/test_corpus_rag.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Integration-style unit tests for the corpus_rag MCP tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.rag.exceptions import CorpusNotFoundError


@pytest.fixture
def configured_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "corpora"))
    monkeypatch.setenv("EMBEDDING_MODEL", "openai:text-embedding-3-small")
    monkeypatch.setenv("EXPANSION_MODEL", "anthropic:claude-haiku-4-5-20251001")
    monkeypatch.setenv("ANSWER_MODEL", "anthropic:claude-sonnet-4-6")
    monkeypatch.setenv("RERANK_MODEL", "anthropic:claude-haiku-4-5-20251001")
    return tmp_path


class _StubEmbedder:
    dimension = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class _StubVectorStore:
    def __init__(self) -> None:
        self._docs: list[Any] = []

    async def upsert(self, docs: list[Any]) -> None:
        self._docs.extend(docs)

    async def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def delete_by_doc_id(self, doc_id: str) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.fixture
def stub_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch CorpusAgent's backend factories so tests don't hit the network."""
    from fireflyframework_agentic.rag import agent as agent_mod

    monkeypatch.setattr(agent_mod.CorpusAgent, "_build_embedder", lambda self, m: _StubEmbedder())
    monkeypatch.setattr(agent_mod.CorpusAgent, "_build_vector_store", lambda self: _StubVectorStore())


@pytest.mark.asyncio
async def test_ingest_corpus_filesystem_smoke(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_filesystem

    docs = configured_env / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")
    (docs / "b.md").write_text("beta", encoding="utf-8")

    result = await ingest_corpus_filesystem.execute(corpus_id="t1", root_path=str(docs))
    assert result["corpus_id"] == "t1"
    assert result["ingested"] == 2
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_corpus_retrieve_raises_for_unknown_corpus(
    configured_env: Path, stub_backends: None
) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_retrieve

    with pytest.raises(CorpusNotFoundError):
        await corpus_retrieve.execute(corpus_id="never-ingested", question="anything", top_k=3)


@pytest.mark.asyncio
async def test_corpus_query_raises_for_unknown_corpus(
    configured_env: Path, stub_backends: None
) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_query

    with pytest.raises(CorpusNotFoundError):
        await corpus_query.execute(corpus_id="never-ingested", question="anything", top_k=3)
```

(`.execute(...)` calls the underlying function via the `_DecoratedTool` wrapper; existing `firefly_tool`-decorated tests use the same shape.)

- [ ] **Step 2: Verify the tests fail**

```bash
uv run pytest tests/unit/tools/builtins/test_corpus_rag.py -v
```

Expected: ImportError (`corpus_rag` module not found).

- [ ] **Step 3: Implement `corpus_rag.py`**

Create `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Corpus RAG tools exposed via MCP.

Four tools:
    - ingest_corpus_filesystem(corpus_id, root_path)
    - ingest_corpus_sharepoint(corpus_id, drive_id, root_folder?)
    - corpus_retrieve(corpus_id, question, top_k)
    - corpus_query(corpus_id, question, top_k)

Each call constructs a fresh CorpusAgent rooted at
``CORPUS_ROOT/<corpus_id>`` and delegates. No process-global registry; the
on-disk SqliteCorpus + SqliteVec carry continuity across requests.

Auth: SharePoint ingestion uses the framework's managed-identity token
provider against Microsoft Graph (zero-trust model — see
:mod:`fireflyframework_agentic.security.azure`).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)
from fireflyframework_agentic.rag import CorpusAgent, CorpusNotFoundError
from fireflyframework_agentic.tools.decorators import firefly_tool

log = logging.getLogger(__name__)

_DEFAULT_CORPUS_ROOT = "/tmp/firefly/corpora"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def _corpus_root() -> Path:
    return Path(os.environ.get("CORPUS_ROOT", _DEFAULT_CORPUS_ROOT))


def _agent_for(corpus_id: str) -> CorpusAgent:
    """Construct an agent rooted at ``CORPUS_ROOT/<corpus_id>``."""
    return CorpusAgent(
        root=_corpus_root() / corpus_id,
        embed_model=os.environ["EMBEDDING_MODEL"],
        expansion_model=os.environ["EXPANSION_MODEL"],
        answer_model=os.environ["ANSWER_MODEL"],
        rerank_model=os.environ["RERANK_MODEL"],
    )


def _assert_corpus_exists(corpus_id: str) -> Path:
    """Raise CorpusNotFoundError if no SQLite file at the expected path."""
    sqlite_path = _corpus_root() / corpus_id / "corpus.sqlite"
    if not sqlite_path.exists():
        raise CorpusNotFoundError(corpus_id, str(sqlite_path))
    return sqlite_path


# ---------- ingest ---------------------------------------------------------


@firefly_tool(
    "ingest_corpus_filesystem",
    description=(
        "Ingest every (non-hidden) file under root_path into the corpus identified "
        "by corpus_id. Idempotent: unchanged files are skipped via content-hash "
        "deduplication. Returns counts of ingested / skipped / failed documents."
    ),
    tags=("rag", "ingest", "filesystem"),
)
async def ingest_corpus_filesystem(corpus_id: str, root_path: str) -> dict[str, Any]:
    source = LocalFolderSource(LocalFolderSourceConfig(folder=Path(root_path)))
    async with _agent_for(corpus_id) as agent:
        summary = await agent.ingest_source(source)
    return {
        "corpus_id": corpus_id,
        "ingested": summary.ingested,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "cursor": summary.cursor,
    }


@firefly_tool(
    "ingest_corpus_sharepoint",
    description=(
        "Ingest every changed file from a SharePoint drive into the corpus "
        "identified by corpus_id. Auth uses the runtime's managed identity to "
        "obtain a Microsoft Graph token. Returns counts of ingested / skipped / "
        "failed documents and the new delta cursor."
    ),
    tags=("rag", "ingest", "sharepoint"),
)
async def ingest_corpus_sharepoint(
    corpus_id: str,
    drive_id: str,
    root_folder: str | None = None,
) -> dict[str, Any]:
    from azure.identity.aio import ManagedIdentityCredential

    from fireflyframework_agentic.content.sources.sharepoint import (
        SharePointSource,
        SharePointSourceConfig,
    )

    cache_dir = _corpus_root() / corpus_id / "sharepoint" / "cache"
    delta_file = _corpus_root() / corpus_id / "sharepoint" / "delta.json"
    cache_dir.mkdir(parents=True, exist_ok=True)

    config = SharePointSourceConfig(
        drive_id=drive_id,
        root_folder=root_folder,
        cache_dir=cache_dir,
        delta_file=delta_file,
    )
    credential = ManagedIdentityCredential()

    async def token_provider() -> str:
        token = await credential.get_token(_GRAPH_SCOPE)
        return token.token

    try:
        async with SharePointSource(config, token_provider=token_provider) as source:
            async with _agent_for(corpus_id) as agent:
                summary = await agent.ingest_source(source)
    finally:
        await credential.close()

    return {
        "corpus_id": corpus_id,
        "ingested": summary.ingested,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "cursor": summary.cursor,
    }


# ---------- retrieve / query -----------------------------------------------


@firefly_tool(
    "corpus_retrieve",
    description=(
        "Run hybrid retrieval (BM25 + dense) with optional reranking over a "
        "corpus and return the top-K matching chunks with score, source path, "
        "and metadata. No LLM answer generation. Raises if corpus_id is unknown."
    ),
    tags=("rag", "query"),
)
async def corpus_retrieve(corpus_id: str, question: str, top_k: int = 5) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    async with _agent_for(corpus_id) as agent:
        hits = await agent.retrieve(question, top_k=top_k, rerank=True)
    return {
        "corpus_id": corpus_id,
        "question": question,
        "hits": [
            {
                "chunk_id": h.chunk_id,
                "score": h.score,
                "content": h.content,
                "source_path": h.source_path,
                "metadata": h.metadata,
            }
            for h in hits
        ],
    }


@firefly_tool(
    "corpus_query",
    description=(
        "Run the full corpus pipeline (expand → retrieve → rerank → answer) and "
        "return a grounded answer with inline citations. Raises if corpus_id is "
        "unknown."
    ),
    tags=("rag", "query"),
)
async def corpus_query(corpus_id: str, question: str, top_k: int = 5) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    async with _agent_for(corpus_id) as agent:
        answer = await agent.query(question, top_k=top_k)
    return {
        "corpus_id": corpus_id,
        "question": question,
        "answer": answer.text,
        "citations": answer.citations,
        "cited_sources": [
            {"chunk_id": c.chunk_id, "source_path": c.source_path, "snippet": c.snippet}
            for c in answer.cited_sources
        ],
    }


__all__ = [
    "corpus_query",
    "corpus_retrieve",
    "ingest_corpus_filesystem",
    "ingest_corpus_sharepoint",
]
```

- [ ] **Step 4: Make sure `tests/unit/tools/builtins/__init__.py` exists**

```bash
mkdir -p tests/unit/tools/builtins && touch tests/unit/tools/builtins/__init__.py
```

- [ ] **Step 5: Run the new tests**

```bash
uv run pytest tests/unit/tools/builtins/test_corpus_rag.py -v
```

Expected: 3 passed (ingest_corpus_filesystem_smoke, both `CorpusNotFoundError` cases).

- [ ] **Step 6: Smoke-import — make sure decorators registered the tools**

```bash
uv run python -c "
import fireflyframework_agentic.tools.builtins.corpus_rag  # noqa: F401
from fireflyframework_agentic.tools.registry import tool_registry
names = sorted(t.name for t in tool_registry.list_tools()
               if t.name.startswith(('ingest_corpus_', 'corpus_')))
print(names)
"
```

Expected:
```
['corpus_query', 'corpus_retrieve', 'ingest_corpus_filesystem', 'ingest_corpus_sharepoint']
```

(`ToolRegistry.list_tools()` returns `list[ToolInfo]`; `ToolInfo.name` is the tool name. See `src/fireflyframework_agentic/tools/registry.py:88` and `src/fireflyframework_agentic/tools/base.py:75`.)

- [ ] **Step 7: Commit**

```bash
git add src/fireflyframework_agentic/tools/builtins/corpus_rag.py \
        tests/unit/tools/builtins/__init__.py \
        tests/unit/tools/builtins/test_corpus_rag.py
git commit -m "feat(tools): corpus_rag MCP tools (filesystem + sharepoint ingest, retrieve + query)"
```

---

## Phase 5 — Polish

### Task 10: Rename telemetry span prefix `corpus_search.*` → `firefly.rag.*`

The metric/instrument names already use `firefly.rag.*` (see `src/fireflyframework_agentic/rag/_telemetry.py`). Only the span names inside `CorpusAgent` carry the legacy `corpus_search.` prefix.

**Files:**
- Modify: `src/fireflyframework_agentic/rag/agent.py`
- Modify: `docs/superpowers/specs/2026-05-04-corpus-search-e2e-appinsights-design.md` (KQL queries that key off span names — find/replace)

- [ ] **Step 1: Rename span names in the agent**

In `src/fireflyframework_agentic/rag/agent.py`, find the three `timed_span("corpus_search.*"...)` call sites (`ingest_folder` is gone by now; the surviving ones live inside `retrieve` and `query`, plus any `ingest_source` span you may add) and replace:

```bash
grep -n 'timed_span("corpus_search\.' src/fireflyframework_agentic/rag/agent.py
```

For each match, swap the prefix:

```python
# Before
async with timed_span("corpus_search.retrieve", attributes={...}):
    ...
async with timed_span("corpus_search.query", attributes={...}) as span:
    ...

# After
async with timed_span("firefly.rag.retrieve", attributes={...}):
    ...
async with timed_span("firefly.rag.query", attributes={...}) as span:
    ...
```

Add a span around `ingest_source` while you're here:

```python
    async def ingest_source(self, source: ContentSource) -> IngestSummary:
        await self._ensure_corpus_ready()
        ...
        async with timed_span(
            "firefly.rag.ingest_source",
            attributes={"source": source.__class__.__name__},
        ) as span:
            # existing body
            span.set_attribute("firefly.rag.terminal.success", summary.ingested)
            span.set_attribute("firefly.rag.terminal.skipped", summary.skipped)
            span.set_attribute("firefly.rag.terminal.failed", summary.failed)
            return summary
```

- [ ] **Step 2: Update KQL examples in the AppInsights design spec**

```bash
sed -i '' 's#corpus_search\.\(ingest_folder\|query\|retrieve\)#firefly.rag.\1#g' \
  docs/superpowers/specs/2026-05-04-corpus-search-e2e-appinsights-design.md
```

Manually inspect the diff afterwards — only KQL string literals should change.

- [ ] **Step 3: Run tests to confirm nothing depended on the old span names**

```bash
uv run pytest tests/examples/corpus_search/ tests/unit/rag/ -v
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/fireflyframework_agentic/rag/agent.py \
        docs/superpowers/specs/2026-05-04-corpus-search-e2e-appinsights-design.md
git commit -m "refactor(rag): rename span prefix corpus_search.* -> firefly.rag.*"
```

---

### Task 11: Operator deployment guide — `docs/deploy/corpus-persistence.md`

**Files:**
- Create: `docs/deploy/corpus-persistence.md`

- [ ] **Step 1: Write the guide**

```bash
mkdir -p docs/deploy
```

Create `docs/deploy/corpus-persistence.md`:

```markdown
# Persisting Firefly RAG corpora on Azure Container Apps

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The `corpus_rag` MCP tools store each corpus as a SQLite file at
`${CORPUS_ROOT}/<corpus_id>/corpus.sqlite` (chunks + FTS5 + vec0 + ledger
co-resident, per the `SqliteVecVectorStore` design). For any non-toy
deployment **operators must override the default `CORPUS_ROOT`** — the
default `/tmp/firefly/corpora` is ephemeral and per-replica on Container
Apps, which means a cold start wipes the corpus.

## Recommended setup: Azure Files volume

1. Provision an Azure Files share. Microsoft's storage-mounts guide is
   the source of truth for the exact CLI invocations:
   <https://learn.microsoft.com/azure/container-apps/storage-mounts>
2. Register the share with the Container Apps environment
   (`az containerapp env storage set ... --azure-file-share-name corpora`).
3. Mount it on the `firefly-mcp` Container App at `/mnt/corpora`.
4. Set the env var on the app:

       az containerapp update --name firefly-mcp --resource-group rg-firefly \
           --set-env-vars CORPUS_ROOT=/mnt/corpora

The MCP tools will now write to and read from the durable share. Cold
starts no longer lose state.

## Multi-replica caveat

`SqliteCorpus` is single-writer. Two replicas writing the *same* corpus
will corrupt the SQLite file (FTS5 + vec0 are not safe under concurrent
writers from different processes). Two safe operating modes:

- **Single-replica ingest path.** Set `--max-replicas 1` on the Container
  App (or split ingest onto a dedicated single-replica app). Reads can
  fan out across replicas safely.
- **Per-replica corpus partitioning.** If multiple replicas must serve
  ingest, arrange that any given `corpus_id` only lands on one replica
  (e.g. partition routing in the calling agent). The framework does not
  enforce this — operators must.

## Other env vars consumed by the MCP tools

| Variable | Purpose | Example |
|---|---|---|
| `CORPUS_ROOT` | Where corpora live on disk. | `/mnt/corpora` |
| `EMBEDDING_MODEL` | Embedder spec, `provider:model`. | `azure:text-embedding-3-small` |
| `EXPANSION_MODEL` | LLM for query expansion. | `anthropic:claude-haiku-4-5-20251001` |
| `ANSWER_MODEL` | LLM for answer synthesis. | `anthropic:claude-sonnet-4-6` |
| `RERANK_MODEL` | LLM for listwise reranking. | `anthropic:claude-haiku-4-5-20251001` |

The Azure embedder additionally needs `EMBEDDING_BINDING_HOST` and
`EMBEDDING_BINDING_API_KEY`, mirroring the example CLI's conventions
(see `examples/corpus_search/cli.py`).

## SharePoint ingestion auth

`ingest_corpus_sharepoint` uses `azure.identity.aio.ManagedIdentityCredential`
to obtain a Microsoft Graph token. The Container App's user-assigned
managed identity (`firefly-mcp-mi`) needs `Sites.Selected` (preferred)
or `Sites.Read.All` granted on the target SharePoint site. Avoid
broad `.All` permissions when a per-site grant suffices.

## Verifying persistence

After mounting the share and pointing `CORPUS_ROOT` at it:

```bash
# From inside any container with the same mount:
ls /mnt/corpora                       # lists corpus_id directories
sqlite3 /mnt/corpora/<corpus_id>/corpus.sqlite '.tables'
# Expect: chunks, ingest_ledger, vec_chunks, ...
```

Round-trip: ingest a small folder via the MCP tool, restart the
Container App (`az containerapp revision restart ...`), then call
`corpus_query` with a question that should hit the ingested document.
A grounded answer confirms persistence.
```

- [ ] **Step 2: Verify it builds**

```bash
test -f docs/deploy/corpus-persistence.md && echo OK
```

- [ ] **Step 3: Commit**

```bash
git add docs/deploy/corpus-persistence.md
git commit -m "docs(deploy): operator guide for persistent CORPUS_ROOT on Container Apps"
```

---

### Task 12: Coordination note for PR #103 rebase

PR #103 (`deploy/azure-mcp`, open) introduced `tools/builtins/sharepoint_rag.py`
and a side-effect import in `cli/mcp_http.py`. After this branch lands on
`main`, PR #103 needs three small changes during rebase. This task
captures them as a checklist that does not require code changes on
*this* branch.

**Files:**
- Modify: `docs/superpowers/plans/2026-05-05-corpus-agent-content-source.md` (this file — add a "PR #103 rebase checklist" section near the bottom; that work happens after PR #103 author rebases).

- [ ] **Step 1: Append the checklist below to this plan file (under a new heading "PR #103 rebase checklist")**

(Do this in a single edit; it's documentation, no code, no tests.)

```markdown
## PR #103 rebase checklist (post-merge)

Once `javi/corpus-agent-content-source` is on `main`, PR #103 must
rebase and apply these three deltas:

1. **Delete** `src/fireflyframework_agentic/tools/builtins/sharepoint_rag.py`.
2. **Edit** `src/fireflyframework_agentic/cli/mcp_http.py`: change the
   side-effect import from `sharepoint_rag` to `corpus_rag`:

       # before
       from fireflyframework_agentic.tools.builtins import sharepoint_rag  # noqa: F401
       # after
       from fireflyframework_agentic.tools.builtins import corpus_rag  # noqa: F401

3. **Update the Dockerfile** if its `uv sync` step pinned extras
   solely to satisfy `sharepoint_rag.py`. The new `corpus_rag` module
   needs the same set: `azure`, `rag`, `openai-embeddings`,
   `markitdown`, `sqlite-vec`. No new extras.

After these three changes, run the unit tests for the MCP tools
(`tests/unit/tools/builtins/test_corpus_rag.py`) and the CLI
(`tests/unit/cli/test_mcp_http.py`); both should pass.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-05-05-corpus-agent-content-source.md
git commit -m "docs(plan): PR #103 rebase checklist"
```

---

## Final verification

- [ ] **Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: green. If anything outside `corpus_search` / `rag` / `content/sources` / `tools/builtins` regresses, investigate immediately — the moves shouldn't touch unrelated tests, but a stray side-effect import or a renamed symbol can.

- [ ] **Run pyright**

```bash
uv run pyright src/fireflyframework_agentic/rag/ \
               src/fireflyframework_agentic/content/sources/local_folder.py \
               src/fireflyframework_agentic/tools/builtins/corpus_rag.py
```

Expected: 0 errors. Fix any flagged.

- [ ] **Run ruff format + lint**

```bash
uv run ruff format src/ tests/ && uv run ruff check src/ tests/
```

Expected: clean.

- [ ] **Push the branch and open a PR against `main`**

```bash
git push -u origin javi/corpus-agent-content-source
gh pr create --title "feat(rag): CorpusAgent + ContentSource abstraction" \
  --body "Replaces PR #103's tools/builtins/sharepoint_rag.py with a thin composition over a library-grade CorpusAgent. See docs/superpowers/specs/2026-05-05-corpus-agent-content-source-design.md."
```

PR #103 author then rebases per the checklist above.

---
