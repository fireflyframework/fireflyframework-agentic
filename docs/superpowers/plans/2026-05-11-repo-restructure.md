# Repo Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up the repo by (1) moving vendor-specific files to `examples/`, (2) flattening the package layout from `src/fireflyframework_agentic/` to `fireflyframework_agentic/`, and (3) renaming `corpus_retrieve` to `knowledge_search` to match the architecture document.

**Architecture:** Three independent but sequentially-ordered sweeps: first move files (maintains `src/` layout throughout so imports stay valid), then rename the tool function (small, targeted change), then flatten the layout (one `git mv` that changes every path but zero imports).

**Tech Stack:** Python 3.13, uv/uv_build, pytest-asyncio, ruff, pyright.

---

## Context — decisions from issue #133 comment

| File | Decision |
|---|---|
| `storage/azure_backend.py` | → `examples/corpus_search/` |
| `security/azure.py` | → `examples/corpus_search/` |
| `content/sources/s3.py` | → `examples/corpus_search/` |
| `content/sources/sharepoint.py` | → `examples/corpus_search/` |
| `cli/` (entire directory) | → `examples/mcp/` |
| `storage/` (rest of module) | stays — may migrate to `fireflyframework-infra` later |
| `vectorstores/sqlite_vec_store.py` | stays |

Naming alignment with architecture doc (`firefly-builderOS-arquitectura-fase1.md`):
- `corpus_retrieve` (tool name + function) → `knowledge_search` (§6.2: "knowledge\_search (RAG retrieval sobre Canon)")

---

## File map

### Files being moved to `examples/corpus_search/`
- `src/fireflyframework_agentic/storage/azure_backend.py` → `examples/corpus_search/azure_backend.py`
- `src/fireflyframework_agentic/security/azure.py` → `examples/corpus_search/azure_security.py`
- `src/fireflyframework_agentic/content/sources/s3.py` → `examples/corpus_search/s3_source.py`
- `src/fireflyframework_agentic/content/sources/sharepoint.py` → `examples/corpus_search/sharepoint_source.py`

### Files being moved to `examples/mcp/`
- `src/fireflyframework_agentic/cli/__init__.py` → `examples/mcp/__init__.py`
- `src/fireflyframework_agentic/cli/mcp_server.py` → `examples/mcp/mcp_server.py`
- `src/fireflyframework_agentic/cli/mcp_http.py` → `examples/mcp/mcp_http.py`

### Tests being moved alongside their subjects
- `tests/security/test_azure.py` → `examples/corpus_search/tests/test_azure_security.py`
- `tests/integration/storage/test_azure_backend_azurite.py` → `examples/corpus_search/tests/test_azure_backend_azurite.py`
- `tests/unit/content/sources/test_sharepoint.py` → `examples/corpus_search/tests/test_sharepoint_source.py`
- `tests/unit/content/sources/test_s3.py` → `examples/corpus_search/tests/test_s3_source.py`
- `tests/unit/cli/test_mcp_http.py` → `examples/mcp/tests/test_mcp_http.py`

### Files modified (not moved)
- `src/fireflyframework_agentic/storage/__init__.py` — remove `AzureBlobBackend`
- `src/fireflyframework_agentic/content/sources/__init__.py` — remove `SharePointSource`, `S3Source`
- `src/fireflyframework_agentic/tools/builtins/corpus_rag.py` — remove `ingest_corpus_sharepoint`, rename `corpus_retrieve` → `knowledge_search`
- `tests/unit/tools/builtins/test_corpus_rag.py` — update `corpus_retrieve` → `knowledge_search`
- `tests/integration/test_mcp_corpus_e2e.py` — update `corpus_retrieve` → `knowledge_search`
- `examples/corpus_search/mcp_server.py` — update `corpus_retrieve` → `knowledge_search`
- `examples/corpus_search/run_mcp_query.py` — update `corpus_retrieve` → `knowledge_search`
- `pyproject.toml` — remove `storage-azure` extra, remove script entries, fix pyright/pytest paths after flat layout
- (after flat layout) `fireflyframework_agentic/` replaces `src/fireflyframework_agentic/`

---

## Task 1 — Move provider-specific backend files to examples/

**Files:**
- Create: `examples/corpus_search/__init__.py`
- Move: `src/fireflyframework_agentic/storage/azure_backend.py` → `examples/corpus_search/azure_backend.py`
- Move: `src/fireflyframework_agentic/security/azure.py` → `examples/corpus_search/azure_security.py`
- Move: `src/fireflyframework_agentic/content/sources/s3.py` → `examples/corpus_search/s3_source.py`
- Move: `src/fireflyframework_agentic/content/sources/sharepoint.py` → `examples/corpus_search/sharepoint_source.py`

- [ ] **Step 1.1: Verify tests pass before touching anything**

```bash
cd /home/u/signature/fireflyframework-agentic
source ~/.venvs/firefly/bin/activate
pytest tests/ -x -q --ignore=tests/integration --ignore=tests/performance 2>&1 | tail -20
```
Expected: green (or known-failing nightly tests only).

- [ ] **Step 1.2: Create examples/corpus_search/ package**

```bash
mkdir -p examples/corpus_search/tests
touch examples/corpus_search/__init__.py
touch examples/corpus_search/tests/__init__.py
```

- [ ] **Step 1.3: git mv the four backend files**

```bash
git mv src/fireflyframework_agentic/storage/azure_backend.py examples/corpus_search/azure_backend.py
git mv src/fireflyframework_agentic/security/azure.py examples/corpus_search/azure_security.py
git mv src/fireflyframework_agentic/content/sources/s3.py examples/corpus_search/s3_source.py
git mv src/fireflyframework_agentic/content/sources/sharepoint.py examples/corpus_search/sharepoint_source.py
```

- [ ] **Step 1.4: Fix the self-import inside the moved sharepoint source**

`examples/corpus_search/sharepoint_source.py` imports from `fireflyframework_agentic.content.sources.base`. That import is fine — it still points to the framework package. No change needed. Verify:

```bash
grep "from fireflyframework_agentic" examples/corpus_search/sharepoint_source.py | head -5
```
Expected: imports reference `fireflyframework_agentic.content.sources.base` (which stays in src/).

- [ ] **Step 1.5: Commit**

```bash
git add examples/corpus_search/
git commit -m "refactor: move vendor-specific backends to examples/corpus_search/"
```

---

## Task 2 — Move tests for the moved backend files

**Files:**
- Move: `tests/security/test_azure.py` → `examples/corpus_search/tests/test_azure_security.py`
- Move: `tests/integration/storage/test_azure_backend_azurite.py` → `examples/corpus_search/tests/test_azure_backend_azurite.py`
- Move: `tests/unit/content/sources/test_sharepoint.py` → `examples/corpus_search/tests/test_sharepoint_source.py`
- Move: `tests/unit/content/sources/test_s3.py` → `examples/corpus_search/tests/test_s3_source.py`

- [ ] **Step 2.1: git mv the test files**

```bash
git mv tests/security/test_azure.py examples/corpus_search/tests/test_azure_security.py
git mv tests/integration/storage/test_azure_backend_azurite.py examples/corpus_search/tests/test_azure_backend_azurite.py
git mv tests/unit/content/sources/test_sharepoint.py examples/corpus_search/tests/test_sharepoint_source.py
git mv tests/unit/content/sources/test_s3.py examples/corpus_search/tests/test_s3_source.py
```

- [ ] **Step 2.2: Update imports in moved test files**

`test_azure_security.py` imported from `fireflyframework_agentic.security.azure` — update to import from `examples.backends.azure_security`. But since `examples/` is not an installed package, the test must use a relative import path or sys.path trick. The simplest fix: add a `conftest.py` in `examples/corpus_search/tests/` that puts `examples/` on sys.path.

Create `examples/corpus_search/tests/conftest.py`:

```python
"""Ensure examples/ is importable in the test session."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
```

Then update the import in `examples/corpus_search/tests/test_azure_security.py`:

```python
# Before:
from fireflyframework_agentic.security.azure import EntraIDVerifier, ...
# After:
from backends.azure_security import EntraIDVerifier, ...
```

Run a quick grep to see exactly what the test imports:
```bash
grep "^from\|^import" examples/corpus_search/tests/test_azure_security.py | head -20
```

Apply the same pattern to all four moved test files — replace `fireflyframework_agentic.security.azure` with `backends.azure_security`, `fireflyframework_agentic.storage.azure_backend` with `backends.azure_backend`, etc.

- [ ] **Step 2.3: Run the moved tests to verify they load correctly**

```bash
pytest examples/corpus_search/tests/ -x -q 2>&1 | tail -20
```
Expected: tests that require Azure deps skip cleanly; S3 stub tests pass.

- [ ] **Step 2.4: Verify the main test suite no longer references moved files**

```bash
pytest tests/ -x -q --ignore=tests/integration --ignore=tests/performance 2>&1 | tail -20
```
Expected: green. The `tests/security/` and `tests/unit/content/sources/` directories will have fewer files; that is correct.

- [ ] **Step 2.5: Commit**

```bash
git add examples/corpus_search/tests/
git commit -m "refactor: move backend tests alongside their subjects in examples/corpus_search/"
```

---

## Task 3 — Update framework __init__.py files

**Files:**
- Modify: `src/fireflyframework_agentic/storage/__init__.py`
- Modify: `src/fireflyframework_agentic/content/sources/__init__.py`

- [ ] **Step 3.1: Strip AzureBlobBackend from storage/__init__.py**

Open `src/fireflyframework_agentic/storage/__init__.py`. Remove:
1. The `try/except ImportError` block that imports `AzureBlobBackend`
2. The `_AZURE_BACKEND_IMPORT_ERROR` variable and its `__getattr__` guard
3. `"AzureBlobBackend"` from `__all__`

Result (keep everything else):

```python
from fireflyframework_agentic.storage._types import (
    DatabaseStoreError,
    LockToken,
    RetryPolicy,
    StorageDownloadError,
    StorageLeaseError,
    StorageMetadata,
    StorageTransientError,
    StorageUploadError,
    StoreUnavailableError,
    WriteSession,
)
from fireflyframework_agentic.storage.backend import StorageBackend
from fireflyframework_agentic.storage.database_store import DatabaseStore
from fireflyframework_agentic.storage.local_backend import LocalBackend

__all__ = [
    "DatabaseStore",
    "DatabaseStoreError",
    "LocalBackend",
    "LockToken",
    "RetryPolicy",
    "StorageBackend",
    "StorageDownloadError",
    "StorageLeaseError",
    "StorageMetadata",
    "StorageTransientError",
    "StorageUploadError",
    "StoreUnavailableError",
    "WriteSession",
]
```

- [ ] **Step 3.2: Strip SharePointSource and S3Source from content/sources/__init__.py**

Open `src/fireflyframework_agentic/content/sources/__init__.py`. Remove the `S3Source`, `S3SourceConfig`, `SharePointSource`, and `SharePointSourceConfig` imports and from `__all__`.

Result:

```python
from fireflyframework_agentic.content.sources.base import ContentSource, RawFile
from fireflyframework_agentic.content.sources.local_folder import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)

__all__ = [
    "ContentSource",
    "LocalFolderSource",
    "LocalFolderSourceConfig",
    "RawFile",
]
```

- [ ] **Step 3.3: Run tests to verify nothing broke**

```bash
pytest tests/ -x -q --ignore=tests/integration --ignore=tests/performance 2>&1 | tail -20
```
Expected: green.

- [ ] **Step 3.4: Commit**

```bash
git add src/fireflyframework_agentic/storage/__init__.py \
        src/fireflyframework_agentic/content/sources/__init__.py
git commit -m "refactor: remove vendor-specific symbols from storage and content.sources __init__"
```

---

## Task 4 — Move cli/ to examples/mcp/

**Files:**
- Create: `examples/mcp/__init__.py`, `examples/mcp/tests/__init__.py`
- Move: `src/fireflyframework_agentic/cli/mcp_server.py` → `examples/mcp/mcp_server.py`
- Move: `src/fireflyframework_agentic/cli/mcp_http.py` → `examples/mcp/mcp_http.py`
- Move: `tests/unit/cli/test_mcp_http.py` → `examples/mcp/tests/test_mcp_http.py`

- [ ] **Step 4.1: Create examples/mcp/ package**

```bash
mkdir -p examples/mcp/tests
touch examples/mcp/__init__.py
touch examples/mcp/tests/__init__.py
```

- [ ] **Step 4.2: git mv cli files and their test**

```bash
git mv src/fireflyframework_agentic/cli/mcp_server.py examples/mcp/mcp_server.py
git mv src/fireflyframework_agentic/cli/mcp_http.py examples/mcp/mcp_http.py
git mv tests/unit/cli/test_mcp_http.py examples/mcp/tests/test_mcp_http.py
# Remove the now-empty cli directory
git rm src/fireflyframework_agentic/cli/__init__.py
```

- [ ] **Step 4.3: Update import in moved test**

`examples/mcp/tests/test_mcp_http.py` imports `from fireflyframework_agentic.cli.mcp_http import build_app`. Update to import from `mcp.mcp_http`. Add a conftest if one doesn't exist:

Create `examples/mcp/tests/conftest.py`:

```python
"""Ensure examples/ is importable in the test session."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
```

Then in `examples/mcp/tests/test_mcp_http.py` replace:

```python
from fireflyframework_agentic.cli.mcp_http import build_app
```

with:

```python
from mcp.mcp_http import build_app
```

- [ ] **Step 4.4: Remove script entries from pyproject.toml**

In `pyproject.toml`, remove the entire `[project.scripts]` section (both `firefly-mcp` and `firefly-mcp-http` pointed into `cli/` which no longer exists in the package):

```toml
# Delete these lines:
[project.scripts]
firefly-mcp = "fireflyframework_agentic.cli.mcp_server:main"
firefly-mcp-http = "fireflyframework_agentic.cli.mcp_http:main"
```

- [ ] **Step 4.5: Remove storage-azure extra from pyproject.toml**

`AzureBlobBackend` has moved to examples/ so the `storage-azure` extra no longer belongs in the framework package. In `pyproject.toml`:

1. Delete the `storage-azure` optional-dependency block:
```toml
# Delete:
storage-azure = [
    "azure-storage-blob>=12.20.0",
    "azure-identity>=1.19",
]
```

2. Remove `storage-azure` from the `all` extra list.

The `azure` extra stays — it's used by `observability/exporters.py` for Azure Monitor.

- [ ] **Step 4.6: Run tests**

```bash
pytest tests/ examples/mcp/tests/ -x -q --ignore=tests/integration --ignore=tests/performance 2>&1 | tail -20
```
Expected: green. The `test_mcp_http.py` test that calls `build_app()` should pass (it only needs fastmcp, fastapi, uvicorn).

- [ ] **Step 4.7: Commit**

```bash
git add examples/mcp/ pyproject.toml
git rm -r src/fireflyframework_agentic/cli/
git commit -m "refactor: move cli MCP entry points to examples/mcp/, remove script entries"
```

---

## Task 5 — Update corpus_rag.py: remove ingest_corpus_sharepoint + rename corpus_retrieve

**Files:**
- Modify: `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`
- Modify: `tests/unit/tools/builtins/test_corpus_rag.py`
- Modify: `tests/integration/test_mcp_corpus_e2e.py`
- Modify: `examples/corpus_search/mcp_server.py`
- Modify: `examples/corpus_search/run_mcp_query.py`

- [ ] **Step 5.1: Remove ingest_corpus_sharepoint from corpus_rag.py**

In `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`:

1. Delete the `ingest_corpus_sharepoint` function (the `@firefly_tool(...)` decorator block + async def, approximately lines 285–345).
2. Remove `"ingest_corpus_sharepoint"` from the module-level `__all__` list.
3. Remove any mention of `ingest_corpus_sharepoint` from the module docstring.
4. Remove the `_GRAPH_SCOPE` constant if it's only used by `ingest_corpus_sharepoint` — check first:

```bash
grep "_GRAPH_SCOPE" src/fireflyframework_agentic/tools/builtins/corpus_rag.py
```

If it only appears inside `ingest_corpus_sharepoint`, delete it too.

- [ ] **Step 5.2: Rename corpus_retrieve → knowledge_search in corpus_rag.py**

In `src/fireflyframework_agentic/tools/builtins/corpus_rag.py`:

1. Change the `@firefly_tool("corpus_retrieve", ...)` decorator first argument to `"knowledge_search"`.
2. Rename the function `async def corpus_retrieve(...)` to `async def knowledge_search(...)`.
3. Update `__all__` — replace `"corpus_retrieve"` with `"knowledge_search"`.
4. Update any docstring or inline comment that says `corpus_retrieve`.

The function body and signature remain identical — only the name changes.

- [ ] **Step 5.3: Update test references**

In `tests/unit/tools/builtins/test_corpus_rag.py`:
- Replace every occurrence of `corpus_retrieve` with `knowledge_search`.

```bash
sed -i 's/corpus_retrieve/knowledge_search/g' tests/unit/tools/builtins/test_corpus_rag.py
```

In `tests/integration/test_mcp_corpus_e2e.py`:
- Replace `"corpus_retrieve"` (the MCP tool name string) with `"knowledge_search"`.

```bash
sed -i 's/"corpus_retrieve"/"knowledge_search"/g' tests/integration/test_mcp_corpus_e2e.py
```

- [ ] **Step 5.4: Update examples that reference corpus_retrieve**

```bash
sed -i 's/corpus_retrieve/knowledge_search/g' examples/corpus_search/mcp_server.py
sed -i 's/corpus_retrieve/knowledge_search/g' examples/corpus_search/run_mcp_query.py
```

- [ ] **Step 5.5: Run tests to verify**

```bash
pytest tests/unit/tools/ tests/unit/tools/builtins/ -x -q 2>&1 | tail -20
```
Expected: green.

- [ ] **Step 5.6: Commit**

```bash
git add src/fireflyframework_agentic/tools/builtins/corpus_rag.py \
        tests/unit/tools/builtins/test_corpus_rag.py \
        tests/integration/test_mcp_corpus_e2e.py \
        examples/corpus_search/mcp_server.py \
        examples/corpus_search/run_mcp_query.py
git commit -m "refactor: remove ingest_corpus_sharepoint, rename corpus_retrieve → knowledge_search"
```

---

## Task 6 — Flat layout: move src/fireflyframework_agentic → fireflyframework_agentic

This is the biggest mechanical change but the lowest conceptual risk: zero imports change.

**Files affected:** every file under `src/fireflyframework_agentic/` (path changes; content unchanged).

- [ ] **Step 6.1: git mv the package directory**

```bash
git mv src/fireflyframework_agentic fireflyframework_agentic
```

Verify src/ is now empty:
```bash
ls src/
```
If empty:
```bash
rmdir src/
```

- [ ] **Step 6.2: Quick smoke test — can Python import the package?**

```bash
source ~/.venvs/firefly/bin/activate
python -c "import fireflyframework_agentic; print(fireflyframework_agentic.__version__ if hasattr(fireflyframework_agentic, '__version__') else 'ok')"
```

If this fails with `ModuleNotFoundError`, it means the venv needs the package reinstalled from the new path:
```bash
pip install -e ".[dev]" --quiet
```
Then retry.

- [ ] **Step 6.3: Update pyproject.toml tool paths**

In `pyproject.toml`, update the three `src` references:

```toml
[tool.pyright]
pythonVersion = "3.13"
typeCheckingMode = "basic"
include = ["fireflyframework_agentic"]      # was: ["src"]
exclude = ["tests/**", "examples/**"]
extraPaths = ["."]                          # was: ["src", "."]


[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]                          # was: ["src", "."]
markers = [
    "nightly: runs only in nightly CI. Long-running tests: benchmarks, real LLM/DB/HTTP, or anything not suitable for the PR gate.",
    "integration: runs against the real CorpusAgent / DatabaseStore stack (no external network — embedders / LLM agents are stubbed or mocked).",
]
```

- [ ] **Step 6.4: Update .pre-commit-config.yaml if it references src/**

```bash
grep -n "src/" .pre-commit-config.yaml
```

The only `src/` reference found earlier was for `studio/static` (an old artefact). If that line appears, remove it:

```bash
# Remove line containing src/fireflyframework_agentic/studio/static
sed -i '/src\/fireflyframework_agentic\/studio\/static/d' .pre-commit-config.yaml
```

- [ ] **Step 6.5: Reinstall the package from new location**

```bash
pip install -e ".[dev,rag,corpus-search,mcp,embeddings,openai-embeddings,rest]" --quiet
```

- [ ] **Step 6.6: Run the full test suite**

```bash
pytest tests/ -x -q --ignore=tests/integration --ignore=tests/performance 2>&1 | tail -30
```
Expected: green.

Also run the examples tests:
```bash
pytest examples/corpus_search/tests/ examples/mcp/tests/ -x -q 2>&1 | tail -15
```

- [ ] **Step 6.7: Commit**

```bash
git add fireflyframework_agentic/ pyproject.toml .pre-commit-config.yaml
git commit -m "refactor: flatten package layout — remove src/ layer"
```

---

## Task 7 — Open PR

- [ ] **Step 7.1: Verify pyright passes on the new layout**

```bash
pyright fireflyframework_agentic/ 2>&1 | tail -20
```
Expected: 0 errors (or same baseline as before the refactor).

- [ ] **Step 7.2: Run ruff**

```bash
ruff check fireflyframework_agentic/ examples/ --fix 2>&1 | tail -10
ruff format fireflyframework_agentic/ examples/ 2>&1 | tail -5
```

Commit any auto-fixes:
```bash
git add -p && git commit -m "style: ruff fixes after restructure"
```

- [ ] **Step 7.3: Create the PR**

```bash
git push -u origin refactor/repo-restructure
gh pr create \
  --title "refactor: flatten layout, move vendor backends to examples/, rename corpus_retrieve→knowledge_search" \
  --body "$(cat <<'EOF'
## Summary

- Moves vendor-specific backends (Azure Blob, Azure Entra ID, SharePoint, S3 stub) to `examples/corpus_search/` per issue #133 decision
- Moves MCP CLI entry points (`cli/`) to `examples/mcp/`; removes `firefly-mcp` / `firefly-mcp-http` script entries and `storage-azure` optional dep
- Flattens package layout: `src/fireflyframework_agentic/` → `fireflyframework_agentic/` (no import changes)
- Renames `corpus_retrieve` MCP tool to `knowledge_search` to align with architecture document §6.2

Closes #133.

## Test plan
- [ ] Unit tests green: `pytest tests/ --ignore=tests/integration --ignore=tests/performance`
- [ ] Examples tests green: `pytest examples/corpus_search/tests/ examples/mcp/tests/`
- [ ] Pyright: 0 errors on new layout
- [ ] Ruff: no violations
EOF
)"
```

---

## Self-review

**Spec coverage:**
- ✅ azure_backend.py moved to examples/corpus_search/
- ✅ security/azure.py moved to examples/corpus_search/
- ✅ content/sources/s3.py moved to examples/corpus_search/
- ✅ content/sources/sharepoint.py moved to examples/corpus_search/
- ✅ cli/ moved to examples/mcp/
- ✅ __init__.py files cleaned up (storage, content/sources)
- ✅ ingest_corpus_sharepoint removed from corpus_rag.py
- ✅ corpus_retrieve renamed to knowledge_search everywhere
- ✅ Tests for moved files migrated alongside subjects
- ✅ Flat layout done via git mv
- ✅ pyproject.toml updated (script entries removed, storage-azure removed, paths fixed)
- ✅ PR created

**Placeholder scan:** No TBDs found.

**Type consistency:** `knowledge_search` used consistently in corpus_rag.py, its tests, and the examples. `build_app` import path in mcp test updated to `mcp.mcp_http`.
