# Structured Ingestion Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the structured data ingestion module from `feat/ingestion-module` into main, wiring it to the existing `ContentSource` (PR #101) instead of its own SharePoint adapter, and add a Claude-based schema discovery agent plus a SQLite query tool for agent use.

**Architecture:** `feat/ingestion-module` contains a complete hexagonal ingestion pipeline (`IngestionService` + `ScriptMapper` + `SQLiteSink`) but duplicates the SharePoint source that PR #101 already merged. We cherry-pick all ingestion code except the internal SharePoint adapter, then replace `DataSourcePort` with the existing `ContentSource` protocol, add a `path: Path` parameter to the mapper interface, and wire the config factory to PR #101's `SharePointSource`. Two new files complete the end-to-end: a `discover_schema` async function (Claude via pydantic-ai) and a `query_sqlite` function (SELECT-only SQL tool for agents).

**Tech Stack:** Python 3.12, pydantic-ai (Agent with `output_type`), openpyxl, pyyaml, sqlite3 (stdlib), httpx (already core dep).

---

## File Map

### Bring in from `feat/ingestion-module` (unchanged)
- `src/fireflyframework_agentic/ingestion/__init__.py`
- `src/fireflyframework_agentic/ingestion/exceptions.py`
- `src/fireflyframework_agentic/ingestion/domain/__init__.py` — will be modified
- `src/fireflyframework_agentic/ingestion/domain/records.py` — will be modified
- `src/fireflyframework_agentic/ingestion/domain/schema.py`
- `src/fireflyframework_agentic/ingestion/ports/__init__.py` — will be modified
- `src/fireflyframework_agentic/ingestion/ports/mapper.py` — will be modified
- `src/fireflyframework_agentic/ingestion/ports/secrets.py`
- `src/fireflyframework_agentic/ingestion/ports/sink.py`
- `src/fireflyframework_agentic/ingestion/ports/source.py` — will be deleted
- `src/fireflyframework_agentic/ingestion/adapters/__init__.py`
- `src/fireflyframework_agentic/ingestion/adapters/env_provider.py`
- `src/fireflyframework_agentic/ingestion/adapters/keyvault_provider.py`
- `src/fireflyframework_agentic/ingestion/adapters/mappers/__init__.py`
- `src/fireflyframework_agentic/ingestion/adapters/mappers/script_mapper.py` — will be modified
- `src/fireflyframework_agentic/ingestion/adapters/sinks/__init__.py`
- `src/fireflyframework_agentic/ingestion/adapters/sinks/sqlite_sink.py`
- `src/fireflyframework_agentic/ingestion/adapters/sources/__init__.py` — will be deleted
- `src/fireflyframework_agentic/ingestion/adapters/sources/sharepoint.py` — will be deleted
- `src/fireflyframework_agentic/ingestion/config/__init__.py`
- `src/fireflyframework_agentic/ingestion/config/ingestion_config.py` — will be modified
- `src/fireflyframework_agentic/ingestion/cli/__init__.py`
- `src/fireflyframework_agentic/ingestion/cli/main.py`
- `src/fireflyframework_agentic/ingestion/services/__init__.py`
- `src/fireflyframework_agentic/ingestion/services/ingestion_service.py` — will be modified
- `tests/test_ingestion/` (all files) — several will be modified or deleted

### Create (new files)
- `src/fireflyframework_agentic/ingestion/agents/__init__.py`
- `src/fireflyframework_agentic/ingestion/agents/schema_discovery.py`
- `src/fireflyframework_agentic/ingestion/tools/__init__.py`
- `src/fireflyframework_agentic/ingestion/tools/sqlite_query.py`

---

## Task 1: Create branch and bring in ingestion module

**Files:** all `ingestion/` files from `feat/ingestion-module`

- [ ] **Step 1: Create feature branch from main**

```bash
git -C /home/u/signature/fireflyframework-agentic checkout main
git -C /home/u/signature/fireflyframework-agentic pull
git -C /home/u/signature/fireflyframework-agentic checkout -b feat/structured-ingestion-integration
```

- [ ] **Step 2: Cherry-pick ingestion source files from feat/ingestion-module**

```bash
REPO=/home/u/signature/fireflyframework-agentic
git -C $REPO checkout feat/ingestion-module -- \
  src/fireflyframework_agentic/ingestion/ \
  tests/test_ingestion/ \
  tests/integration/test_ingestion.py
```

Note: `security/identifiers.py` may already be on main (check first):
```bash
git -C $REPO show main:src/fireflyframework_agentic/security/identifiers.py 2>/dev/null && echo "EXISTS" || echo "MISSING"
```
If MISSING, also run:
```bash
git -C $REPO checkout feat/ingestion-module -- src/fireflyframework_agentic/security/identifiers.py
```

- [ ] **Step 3: Verify the files are staged**

```bash
git -C /home/u/signature/fireflyframework-agentic status --short | grep "^[AM]" | wc -l
```
Expected: 40+ files staged.

- [ ] **Step 4: Commit the raw cherry-pick (pre-surgery)**

```bash
git -C /home/u/signature/fireflyframework-agentic add src/fireflyframework_agentic/ingestion/ tests/test_ingestion/ tests/integration/test_ingestion.py src/fireflyframework_agentic/security/identifiers.py
git -C /home/u/signature/fireflyframework-agentic commit -m "chore: bring in ingestion module from feat/ingestion-module (pre-surgery)"
```

---

## Task 2: Delete duplicate SharePoint source and DataSourcePort

**Files:**
- Delete: `src/fireflyframework_agentic/ingestion/adapters/sources/sharepoint.py`
- Delete: `src/fireflyframework_agentic/ingestion/adapters/sources/__init__.py`
- Delete: `src/fireflyframework_agentic/ingestion/ports/source.py`
- Delete: `tests/test_ingestion/test_sharepoint_source.py`
- Modify: `src/fireflyframework_agentic/ingestion/ports/__init__.py`

- [ ] **Step 1: Delete the duplicate SharePoint source files**

```bash
REPO=/home/u/signature/fireflyframework-agentic
rm $REPO/src/fireflyframework_agentic/ingestion/adapters/sources/sharepoint.py
rm $REPO/src/fireflyframework_agentic/ingestion/adapters/sources/__init__.py
rmdir $REPO/src/fireflyframework_agentic/ingestion/adapters/sources/
rm $REPO/src/fireflyframework_agentic/ingestion/ports/source.py
rm $REPO/tests/test_ingestion/test_sharepoint_source.py
```

- [ ] **Step 2: Remove DataSourcePort from ports/__init__.py**

Replace the full content of `src/fireflyframework_agentic/ingestion/ports/__init__.py` with:

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Hexagonal ports for the ingestion module."""

from fireflyframework_agentic.ingestion.ports.mapper import MapperPort
from fireflyframework_agentic.ingestion.ports.secrets import SecretsProvider
from fireflyframework_agentic.ingestion.ports.sink import StructuredSinkPort

__all__ = [
    "MapperPort",
    "SecretsProvider",
    "StructuredSinkPort",
]
```

- [ ] **Step 3: Commit deletions**

```bash
REPO=/home/u/signature/fireflyframework-agentic
git -C $REPO add -u
git -C $REPO commit -m "refactor(ingestion): remove duplicate SharePoint source and DataSourcePort"
```

---

## Task 3: Replace ingestion RawFile with content.sources.base RawFile

The ingestion module's `RawFile` (Pydantic model with `local_path`) is replaced by `content.sources.base.RawFile` (frozen dataclass with `metadata`). Mappers receive the local path as a separate `path: Path` argument instead of reading it from the file object.

**Files:**
- Modify: `src/fireflyframework_agentic/ingestion/domain/records.py`
- Modify: `src/fireflyframework_agentic/ingestion/domain/__init__.py`

- [ ] **Step 1: Remove RawFile from domain/records.py**

Replace the full content of `src/fireflyframework_agentic/ingestion/domain/records.py` with:

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Domain records for the ingestion module.

These models are pure value objects: they hold data and validate it through
Pydantic, but never perform I/O. Adapters and services compose them.

Note: RawFile is defined in content.sources.base and re-exported here for
convenience so callers can use a single import path.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fireflyframework_agentic.content.sources.base import RawFile


class TypedRecord(BaseModel):
    """A single row produced by a mapping script, targeted at a table."""

    table: str
    row: dict[str, Any]


class IngestionError(BaseModel):
    """A non-fatal error captured during a run."""

    kind: str
    message: str
    file_source_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    """Outcome of a single IngestionService.run_* invocation."""

    files_processed: int = 0
    records_written: dict[str, int] = Field(default_factory=dict)
    errors: list[IngestionError] = Field(default_factory=list)
    run_id: str | None = None


__all__ = ["IngestionError", "IngestionResult", "RawFile", "TypedRecord"]
```

- [ ] **Step 2: Update domain/__init__.py to export RawFile from records (which re-exports from content.sources.base)**

`src/fireflyframework_agentic/ingestion/domain/__init__.py` already exports `RawFile` from `records.py`. Since `records.py` now imports and re-exports `RawFile` from `content.sources.base`, the `__init__.py` needs no change — `RawFile` will flow through correctly.

Verify by running:
```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -c "from fireflyframework_agentic.ingestion.domain import RawFile; print(RawFile)"
```
Expected: `<class 'fireflyframework_agentic.content.sources.base.RawFile'>`

- [ ] **Step 3: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add src/fireflyframework_agentic/ingestion/domain/records.py
git -C /home/u/signature/fireflyframework-agentic commit -m "refactor(ingestion): use content.sources.base.RawFile, remove local_path field"
```

---

## Task 4: Update MapperPort and ScriptMapper to accept path parameter

Mappers no longer read `file.local_path` — they receive the local path as an explicit `path: Path` argument. This makes the dependency on local disk explicit and enables the service to own the fetch lifecycle.

**Files:**
- Modify: `src/fireflyframework_agentic/ingestion/ports/mapper.py`
- Modify: `src/fireflyframework_agentic/ingestion/adapters/mappers/script_mapper.py`
- Modify: `tests/test_ingestion/fixtures/scripts/customers.py`
- Modify: `tests/test_ingestion/fixtures/scripts/sales.py`

- [ ] **Step 1: Update MapperPort**

Replace the full content of `src/fireflyframework_agentic/ingestion/ports/mapper.py` with:

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""MapperPort: protocol for converting raw files into typed records."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from fireflyframework_agentic.ingestion.domain import RawFile, TargetSchema, TypedRecord


@runtime_checkable
class MapperPort(Protocol):
    """Translates a RawFile (and its local cached path) into typed rows."""

    def supports(self, file: RawFile) -> bool:
        """Return whether this mapper can handle *file*."""
        ...

    def map(self, file: RawFile, path: Path, schema: TargetSchema) -> Iterator[TypedRecord]:
        """Yield typed records produced from *file*.

        Args:
            file: Metadata about the file (name, mime_type, source_id, etc.).
            path: Local path to the cached copy of the file on disk.
            schema: Target schema to validate emitted rows against.
        """
        ...
```

- [ ] **Step 2: Update ScriptMapper and MapFn**

Replace the full content of `src/fireflyframework_agentic/ingestion/adapters/mappers/script_mapper.py` with:

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""ScriptMapper: dynamically loads user-supplied mapping scripts.

Each script in the configured directory must declare:

* ``PATTERN`` -- a compiled re.Pattern matched against RawFile.name
  (or RawFile.source_id for path-based dispatch).
* ``map(file: RawFile, path: Path, schema: TargetSchema) -> Iterator[TypedRecord]``
  -- a callable that yields typed records. ``path`` is the local cached
  copy of the file; scripts must read from this path, not from ``file``.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import cast

from fireflyframework_agentic.ingestion.domain import (
    RawFile,
    TargetSchema,
    TypedRecord,
)
from fireflyframework_agentic.ingestion.exceptions import (
    MappingScriptError,
    MultipleMappersError,
)

logger = logging.getLogger(__name__)

MapFn = Callable[[RawFile, Path, TargetSchema], Iterator[TypedRecord]]


class _LoadedScript:
    __slots__ = ("path", "pattern", "map_fn")

    def __init__(self, path: Path, pattern: re.Pattern[str], map_fn: MapFn) -> None:
        self.path = path
        self.pattern = pattern
        self.map_fn = map_fn

    def matches(self, file: RawFile) -> bool:
        return bool(self.pattern.search(file.name) or self.pattern.search(file.source_id))


class ScriptMapper:
    """Loads mapping scripts from a directory and dispatches by PATTERN."""

    def __init__(self, scripts_dir: str | Path) -> None:
        self._scripts_dir = Path(scripts_dir)
        if not self._scripts_dir.is_dir():
            raise MappingScriptError(f"scripts_dir {self._scripts_dir} does not exist or is not a directory")
        self._scripts: list[_LoadedScript] = self._load_all(self._scripts_dir)

    @property
    def scripts_dir(self) -> Path:
        return self._scripts_dir

    @property
    def script_count(self) -> int:
        return len(self._scripts)

    def supports(self, file: RawFile) -> bool:
        return any(s.matches(file) for s in self._scripts)

    def map(self, file: RawFile, path: Path, schema: TargetSchema) -> Iterator[TypedRecord]:
        matches = [s for s in self._scripts if s.matches(file)]
        if not matches:
            raise MappingScriptError(f"no mapping script matches file {file.source_id!r}")
        if len(matches) > 1:
            paths = [str(s.path) for s in matches]
            raise MultipleMappersError(f"multiple mapping scripts match {file.source_id!r}: {paths}")
        yield from matches[0].map_fn(file, path, schema)

    @staticmethod
    def _load_all(scripts_dir: Path) -> list[_LoadedScript]:
        loaded: list[_LoadedScript] = []
        for path in sorted(scripts_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module = ScriptMapper._load_module(path)
            pattern = ScriptMapper._extract_pattern(module, path)
            map_fn = ScriptMapper._extract_map(module, path)
            loaded.append(_LoadedScript(path=path, pattern=pattern, map_fn=map_fn))
        return loaded

    @staticmethod
    def _load_module(path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(f"firefly_mapping_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise MappingScriptError(f"could not import script {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise MappingScriptError(f"error executing script {path}: {exc}") from exc
        return module

    @staticmethod
    def _extract_pattern(module: ModuleType, path: Path) -> re.Pattern[str]:
        if not hasattr(module, "PATTERN"):
            raise MappingScriptError(f"script {path} does not declare PATTERN")
        pattern = module.PATTERN
        if isinstance(pattern, str):
            try:
                return re.compile(pattern)
            except re.error as exc:
                raise MappingScriptError(f"script {path} PATTERN is not a valid regex: {exc}") from exc
        if not isinstance(pattern, re.Pattern):
            raise MappingScriptError(f"script {path} PATTERN must be a re.Pattern or str, got {type(pattern).__name__}")
        return pattern

    @staticmethod
    def _extract_map(module: ModuleType, path: Path) -> MapFn:
        if not hasattr(module, "map"):
            raise MappingScriptError(f"script {path} does not declare map()")
        fn = module.map
        if not callable(fn):
            raise MappingScriptError(f"script {path} map is not callable")
        return cast("MapFn", fn)
```

- [ ] **Step 3: Update fixture script customers.py**

Replace `tests/test_ingestion/fixtures/scripts/customers.py` with:

```python
import re
from collections.abc import Iterator
from pathlib import Path

from fireflyframework_agentic.ingestion.domain import RawFile, TargetSchema, TypedRecord

PATTERN = re.compile(r"customers.*\.csv$")


def map(file: RawFile, path: Path, schema: TargetSchema) -> Iterator[TypedRecord]:
    text = path.read_text()
    lines = text.strip().splitlines()
    headers = lines[0].split(",")
    for row in lines[1:]:
        values = row.split(",")
        record = dict(zip(headers, values, strict=False))
        yield TypedRecord(
            table="customers",
            row={"id": int(record["id"]), "name": record["name"], "tier": record["tier"]},
        )
```

- [ ] **Step 4: Update fixture script sales.py**

Replace `tests/test_ingestion/fixtures/scripts/sales.py` with:

```python
import re
from collections.abc import Iterator
from pathlib import Path

from fireflyframework_agentic.ingestion.domain import RawFile, TargetSchema, TypedRecord

PATTERN = re.compile(r"sales.*\.csv$")


def map(file: RawFile, path: Path, schema: TargetSchema) -> Iterator[TypedRecord]:
    text = path.read_text()
    lines = text.strip().splitlines()
    headers = lines[0].split(",")
    for row in lines[1:]:
        values = row.split(",")
        record = dict(zip(headers, values, strict=False))
        yield TypedRecord(
            table="sales",
            row={
                "id": int(record["id"]),
                "customer_id": int(record["customer_id"]),
                "day": record["day"],
                "amount": float(record["amount"]),
                "paid": record["paid"],
            },
        )
```

- [ ] **Step 5: Run script_mapper tests (expect FAIL for now — service/config not updated yet)**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pytest tests/test_ingestion/test_script_mapper.py -v 2>&1 | tail -20
```

- [ ] **Step 6: Commit**

```bash
REPO=/home/u/signature/fireflyframework-agentic
git -C $REPO add src/fireflyframework_agentic/ingestion/ports/mapper.py \
  src/fireflyframework_agentic/ingestion/adapters/mappers/script_mapper.py \
  tests/test_ingestion/fixtures/scripts/
git -C $REPO commit -m "refactor(ingestion): mapper.map() takes explicit path: Path argument"
```

---

## Task 5: Update IngestionService to use ContentSource

Replace `DataSourcePort` with `ContentSource` (from `content.sources.base`). Store `(raw, local)` tuples instead of mutating `RawFile`. Commit delta via `pending_cursor()` / `commit_delta()` after successful sink finalization.

**Files:**
- Modify: `src/fireflyframework_agentic/ingestion/services/ingestion_service.py`

- [ ] **Step 1: Replace ingestion_service.py**

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Linear orchestrator that wires source, mapper, and sink together."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fireflyframework_agentic.content.sources.base import ContentSource, RawFile
from fireflyframework_agentic.ingestion.domain import (
    IngestionError,
    IngestionResult,
    TargetSchema,
)
from fireflyframework_agentic.ingestion.ports import (
    MapperPort,
    StructuredSinkPort,
)

logger = logging.getLogger(__name__)


class IngestionService:
    """Coordinates a single ingestion run.

    The orchestration is intentionally linear (no DAG, no fan-out). Errors
    surfaced by the sink or mapping scripts are accumulated in IngestionResult
    rather than aborting the run; only fatal conditions (auth failure,
    unparseable schema, sink misconfiguration) propagate as exceptions.
    """

    def __init__(
        self,
        source: ContentSource,
        mapper: MapperPort,
        sink: StructuredSinkPort,
        schema: TargetSchema,
    ) -> None:
        self._source = source
        self._mapper = mapper
        self._sink = sink
        self._schema = schema

    async def run_incremental(
        self,
        since: str | None = None,
        *,
        run_id: str | None = None,
    ) -> IngestionResult:
        cursor = since if since is not None else await self._source.current_cursor()
        return await self._run(since=cursor, run_id=run_id)

    async def run_full_rebuild(self, *, run_id: str | None = None) -> IngestionResult:
        return await self._run(since=None, run_id=run_id)

    async def _run(self, since: str | None, run_id: str | None = None) -> IngestionResult:
        result = IngestionResult(run_id=run_id)
        started = time.perf_counter()

        # Phase 1: list changed files and fetch into local cache.
        cached: list[tuple[RawFile, Path]] = []
        async for raw in self._source.list_changed(since):
            try:
                local = await self._source.fetch(raw)
            except Exception as exc:
                result.errors.append(
                    IngestionError(
                        kind="FetchError",
                        message=f"failed to fetch {raw.source_id!r}: {exc}",
                        file_source_id=raw.source_id,
                    )
                )
                continue
            cached.append((raw, local))

        # Phase 2: rebuild sink and run mappings.
        self._sink.begin(self._schema)
        for raw, local in cached:
            if not self._mapper.supports(raw):
                result.errors.append(
                    IngestionError(
                        kind="NoMapperFound",
                        message=f"no mapping script matches {raw.source_id!r}",
                        file_source_id=raw.source_id,
                    )
                )
                continue
            try:
                records = list(self._mapper.map(raw, local, self._schema))
            except Exception as exc:
                result.errors.append(
                    IngestionError(
                        kind="MappingScriptError",
                        message=f"mapping {raw.source_id!r} raised: {exc}",
                        file_source_id=raw.source_id,
                    )
                )
                continue
            self._sink.write(records)
            result.files_processed += 1

        sink_errors = getattr(self._sink, "validation_errors", None) or []
        result.errors.extend(sink_errors)
        result.records_written = self._sink.finalize()

        # Commit delta only after successful sink finalization.
        pending = await self._source.pending_cursor()
        if pending is not None:
            await self._source.commit_delta(pending)

        elapsed = time.perf_counter() - started
        logger.info(
            "ingestion run completed in %.2fs: files=%d records=%s errors=%d",
            elapsed,
            result.files_processed,
            result.records_written,
            len(result.errors),
        )
        return result
```

- [ ] **Step 2: Commit**

```bash
REPO=/home/u/signature/fireflyframework-agentic
git -C $REPO add src/fireflyframework_agentic/ingestion/services/ingestion_service.py
git -C $REPO commit -m "refactor(ingestion): IngestionService uses ContentSource, explicit path tuples"
```

---

## Task 6: Update ingestion_config.py to use content.sources.sharepoint.SharePointSource

Remove all imports of the deleted internal SharePoint source. Wire `build_source` to PR #101's `SharePointSource` using a token-provider closure for OAuth2 client-credentials.

**Files:**
- Modify: `src/fireflyframework_agentic/ingestion/config/ingestion_config.py`

- [ ] **Step 1: Replace ingestion_config.py**

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pydantic config model for ingestion.yaml + factory helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel, Field

from fireflyframework_agentic.content.sources.base import ContentSource
from fireflyframework_agentic.content.sources.sharepoint import (
    SharePointSource,
    SharePointSourceConfig,
)
from fireflyframework_agentic.ingestion.adapters import EnvSecretsProvider
from fireflyframework_agentic.ingestion.adapters.mappers import ScriptMapper
from fireflyframework_agentic.ingestion.adapters.sinks import SQLiteSink
from fireflyframework_agentic.ingestion.domain import TargetSchema
from fireflyframework_agentic.ingestion.exceptions import IngestionConfigError
from fireflyframework_agentic.ingestion.ports import (
    MapperPort,
    SecretsProvider,
    StructuredSinkPort,
)
from fireflyframework_agentic.ingestion.services import IngestionService


class SourceSection(BaseModel):
    type: Literal["sharepoint"]
    config: dict[str, Any]


class MapperSection(BaseModel):
    type: Literal["script"]
    scripts_dir: Path


class SinkSection(BaseModel):
    type: Literal["sqlite"]
    mode: Literal["in-memory", "file"] = "in-memory"
    path: Path | None = None


class StateSection(BaseModel):
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".fireflyframework/ingestion/cache")
    delta_file: Path = Field(default_factory=lambda: Path.home() / ".fireflyframework/ingestion/delta.json")


class SecretsSection(BaseModel):
    type: Literal["env", "azure-keyvault"] = "env"
    vault_url: str | None = None


class IngestionConfig(BaseModel):
    """Top-level ingestion.yaml schema."""

    source: SourceSection
    mapper: MapperSection
    sink: SinkSection
    schema_path: Path = Field(alias="schema")
    state: StateSection = Field(default_factory=StateSection)
    secrets: SecretsSection = Field(default_factory=SecretsSection)

    model_config = {"populate_by_name": True}

    @classmethod
    def from_yaml(cls, path: str | Path) -> IngestionConfig:
        try:
            data = yaml.safe_load(Path(path).read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise IngestionConfigError(f"could not read {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise IngestionConfigError(f"{path}: top-level must be a mapping")
        return cls.model_validate(data)


def build_secrets_provider(section: SecretsSection) -> SecretsProvider:
    if section.type == "env":
        return EnvSecretsProvider()
    if section.type == "azure-keyvault":
        if not section.vault_url:
            raise IngestionConfigError("secrets.type=azure-keyvault requires secrets.vault_url")
        from fireflyframework_agentic.ingestion.adapters.keyvault_provider import (
            AzureKeyVaultSecretsProvider,
        )
        return AzureKeyVaultSecretsProvider(section.vault_url)
    raise IngestionConfigError(f"unknown secrets type: {section.type!r}")


def build_source(
    section: SourceSection,
    state: StateSection,
    secrets: SecretsProvider,
) -> ContentSource:
    if section.type == "sharepoint":
        tenant_id = secrets.get(section.config["tenant_id_secret"])
        client_id = secrets.get(section.config["client_id_secret"])
        client_secret_val = secrets.get(section.config["client_secret_secret"])

        async def _token_provider() -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret_val,
                        "scope": "https://graph.microsoft.com/.default",
                    },
                )
                resp.raise_for_status()
                return str(resp.json()["access_token"])

        extra = {k: v for k, v in section.config.items()
                 if k not in {"tenant_id_secret", "client_id_secret", "client_secret_secret"}}
        merged = {**extra, "cache_dir": state.cache_dir, "delta_file": state.delta_file}
        sp_config = SharePointSourceConfig.model_validate(merged)
        return SharePointSource(sp_config, _token_provider)
    raise IngestionConfigError(f"unknown source type: {section.type!r}")


def build_mapper(section: MapperSection) -> MapperPort:
    if section.type == "script":
        return ScriptMapper(section.scripts_dir)
    raise IngestionConfigError(f"unknown mapper type: {section.type!r}")


def build_sink(section: SinkSection) -> StructuredSinkPort:
    if section.type == "sqlite":
        if section.mode == "in-memory":
            return SQLiteSink(":memory:")
        if section.path is None:
            raise IngestionConfigError(f"sqlite sink mode={section.mode!r} requires sink.path")
        return SQLiteSink(str(section.path))
    raise IngestionConfigError(f"unknown sink type: {section.type!r}")


def build_service(config: IngestionConfig) -> IngestionService:
    schema = TargetSchema.from_yaml(config.schema_path)
    secrets = build_secrets_provider(config.secrets)
    source = build_source(config.source, config.state, secrets)
    mapper = build_mapper(config.mapper)
    sink = build_sink(config.sink)
    return IngestionService(source, mapper, sink, schema)


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} references in value using os.environ."""
    return os.path.expandvars(value)
```

Note: `AzureKeyVaultSecretsProvider` is imported inside `build_secrets_provider` because `azure-keyvault-secrets` is an optional dependency. This is the only exception to the top-of-file import rule.

- [ ] **Step 2: Commit**

```bash
REPO=/home/u/signature/fireflyframework-agentic
git -C $REPO add src/fireflyframework_agentic/ingestion/config/ingestion_config.py
git -C $REPO commit -m "refactor(ingestion): build_source wires to content.sources.sharepoint.SharePointSource"
```

---

## Task 7: Update pyproject.toml

Remove the `ingestion-sharepoint` extra (httpx is already core), keep `ingestion-keyvault`, add `ingestion` extra with pyyaml and openpyxl (needed by schema discovery). Add `firefly-ingest` script entry.

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Check current extras section**

```bash
grep -A 30 "optional-dependencies" /home/u/signature/fireflyframework-agentic/pyproject.toml | head -40
```

- [ ] **Step 2: Add ingestion extras and script entry**

Find the `[project.optional-dependencies]` section and add:
```toml
ingestion = ["pyyaml>=6.0", "openpyxl>=3.1"]
ingestion-keyvault = ["azure-identity>=1.19.0", "azure-keyvault-secrets>=4.9.0"]
```

Find the `[project.scripts]` section (or `[project]` if it doesn't exist) and add:
```toml
firefly-ingest = "fireflyframework_agentic.ingestion.cli:main"
```

- [ ] **Step 3: Install updated extras**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  pip install -e ".[ingestion]" --quiet
```

Expected: installs pyyaml and openpyxl, no errors.

- [ ] **Step 4: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add pyproject.toml
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(ingestion): add ingestion extras and firefly-ingest CLI entry point"
```

---

## Task 8: Update tests

Update `test_ingestion_service.py` to use `ContentSource`-compatible `FakeSource` (no `local_path` on `RawFile`, add `pending_cursor()`). Update `test_script_mapper.py` to call `mapper.map(file, path, schema)`. Update `test_config.py` to remove `SharePointSource` import from internal adapter.

**Files:**
- Modify: `tests/test_ingestion/test_ingestion_service.py`
- Modify: `tests/test_ingestion/test_script_mapper.py`
- Modify: `tests/test_ingestion/test_config.py`

- [ ] **Step 1: Replace test_ingestion_service.py**

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration tests for IngestionService with a FakeSource and real adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fireflyframework_agentic.content.sources.base import RawFile
from fireflyframework_agentic.ingestion.adapters.mappers import ScriptMapper
from fireflyframework_agentic.ingestion.adapters.sinks import SQLiteSink
from fireflyframework_agentic.ingestion.domain import (
    ColumnSpec,
    ForeignKeySpec,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.ingestion.services import IngestionService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FakeSource:
    """Implements ContentSource protocol using in-memory file lists."""

    def __init__(
        self,
        files: list[tuple[RawFile, Path]],
        initial_cursor: str | None = None,
    ) -> None:
        self._files = files
        self._cursor = initial_cursor
        self._pending: str | None = "cursor-v2"
        self.commit_called_with: list[str] = []
        self.last_since: str | None = None  # captures argument passed to list_changed

    async def list_changed(self, since: str | None) -> AsyncIterator[RawFile]:
        self.last_since = since
        for f, _ in self._files:
            yield f

    async def fetch(self, file: RawFile) -> Path:
        for f, path in self._files:
            if f.source_id == file.source_id:
                return path
        raise FileNotFoundError(file.source_id)

    async def current_cursor(self) -> str | None:
        return self._cursor

    async def pending_cursor(self) -> str | None:
        return self._pending

    async def commit_delta(self, cursor: str) -> None:
        self._cursor = cursor
        self.commit_called_with.append(cursor)


@pytest.fixture
def schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="customers",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="name", type="string"),
                    ColumnSpec(name="tier", type="string"),
                ],
            ),
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="customer_id", type="integer", nullable=False),
                    ColumnSpec(name="day", type="date"),
                    ColumnSpec(name="amount", type="float"),
                    ColumnSpec(name="paid", type="boolean"),
                ],
                foreign_keys=[
                    ForeignKeySpec(
                        column="customer_id",
                        references_table="customers",
                        references_column="id",
                    )
                ],
            ),
        ]
    )


def _csv_raw(name: str, source_id: str) -> RawFile:
    return RawFile(
        source_id=source_id,
        name=name,
        mime_type="text/csv",
        size_bytes=0,
        etag="v1",
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


async def test_end_to_end_pipeline_writes_to_sqlite(schema: TargetSchema, tmp_path: Path):
    customers = tmp_path / "customers_q1.csv"
    customers.write_text("id,name,tier\n1,Alpha,gold\n2,Beta,silver\n")
    sales = tmp_path / "sales_q1.csv"
    sales.write_text("id,customer_id,day,amount,paid\n10,1,2026-01-15,99.5,true\n11,2,2026-02-20,12.0,false\n")
    source = FakeSource(
        [
            (_csv_raw("customers_q1.csv", "fake:cust1"), customers),
            (_csv_raw("sales_q1.csv", "fake:sales1"), sales),
        ]
    )
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.files_processed == 2
        assert result.records_written == {"customers": 2, "sales": 2}
        assert result.errors == []
        rows = sink.connection.execute(
            "SELECT customers.name, sales.amount FROM sales "
            "JOIN customers ON sales.customer_id = customers.id "
            "ORDER BY sales.id"
        ).fetchall()
        assert rows == [("Alpha", 99.5), ("Beta", 12.0)]
    finally:
        sink.close()


async def test_delta_is_committed_after_successful_run(schema: TargetSchema, tmp_path: Path):
    customers = tmp_path / "customers_q1.csv"
    customers.write_text("id,name,tier\n1,Alpha,gold\n")
    source = FakeSource([(_csv_raw("customers_q1.csv", "fake:c"), customers)])
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        await svc.run_full_rebuild()
    finally:
        sink.close()
    assert source.commit_called_with == ["cursor-v2"]


async def test_unsupported_file_records_error_and_continues(schema: TargetSchema, tmp_path: Path):
    customers = tmp_path / "customers_q1.csv"
    customers.write_text("id,name,tier\n1,Alpha,gold\n")
    unrelated = tmp_path / "weird.bin"
    unrelated.write_bytes(b"\x00\x01\x02")
    source = FakeSource(
        [
            (_csv_raw("weird.bin", "fake:weird"), unrelated),
            (_csv_raw("customers_q1.csv", "fake:cust1"), customers),
        ]
    )
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.files_processed == 1
        assert result.records_written["customers"] == 1
        assert any(e.kind == "NoMapperFound" for e in result.errors)
    finally:
        sink.close()


async def test_run_incremental_uses_persisted_cursor_when_since_is_none(schema: TargetSchema, tmp_path: Path):
    source = FakeSource(files=[], initial_cursor="saved-cursor")
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        await svc.run_incremental()
    finally:
        sink.close()
    # current_cursor() returned "saved-cursor"; verify it was passed to list_changed
    assert source.last_since == "saved-cursor"


async def test_fetch_failure_recorded_as_error(schema: TargetSchema, tmp_path: Path):
    customers = tmp_path / "customers_q1.csv"
    customers.write_text("id,name,tier\n1,Alpha,gold\n")

    class FailingSource(FakeSource):
        async def fetch(self, file: RawFile) -> Path:
            raise RuntimeError("network down")

    source = FailingSource([(_csv_raw("customers_q1.csv", "fake:c"), customers)])
    mapper = ScriptMapper(FIXTURES_DIR / "scripts")
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.files_processed == 0
        assert any(e.kind == "FetchError" and "network down" in e.message for e in result.errors)
    finally:
        sink.close()


async def test_mapping_script_failure_recorded_as_error(schema: TargetSchema, tmp_path: Path):
    bad = tmp_path / "scripts"
    bad.mkdir()
    (bad / "boom.py").write_text(
        "import re\n"
        "from collections.abc import Iterator\n"
        "from pathlib import Path\n"
        "PATTERN = re.compile(r'boom')\n"
        "def map(file, path, schema):\n"
        "    raise RuntimeError('mapping kaboom')\n"
        "    yield\n"
    )
    f = tmp_path / "boom.csv"
    f.write_text("x")
    source = FakeSource([(_csv_raw("boom.csv", "fake:b"), f)])
    mapper = ScriptMapper(bad)
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.files_processed == 0
        assert any(e.kind == "MappingScriptError" and "kaboom" in e.message for e in result.errors)
    finally:
        sink.close()


async def test_sink_validation_errors_propagate_to_result(schema: TargetSchema, tmp_path: Path):
    bad_scripts = tmp_path / "scripts"
    bad_scripts.mkdir()
    (bad_scripts / "sales_bad.py").write_text(
        "import re\n"
        "from collections.abc import Iterator\n"
        "from pathlib import Path\n"
        "from fireflyframework_agentic.ingestion.domain import "
        "RawFile, TargetSchema, TypedRecord\n"
        "PATTERN = re.compile(r'sales-bad')\n"
        "def map(file, path, schema):\n"
        "    yield TypedRecord(table='sales', row={'id': 1, 'amount': 1.0})\n"
    )
    f = tmp_path / "sales-bad.csv"
    f.write_text("x")
    source = FakeSource([(_csv_raw("sales-bad.csv", "fake:sb"), f)])
    mapper = ScriptMapper(bad_scripts)
    sink = SQLiteSink()
    try:
        svc = IngestionService(source, mapper, sink, schema)
        result = await svc.run_full_rebuild()
        assert result.records_written["sales"] == 0
        assert any(e.kind == "RowValidationError" for e in result.errors)
    finally:
        sink.close()
```

- [ ] **Step 2: Fix test_script_mapper.py — update _make_raw and map() calls**

In `tests/test_ingestion/test_script_mapper.py`:

Replace the `_make_raw` helper:
```python
# old
def _make_raw(name: str, source_id: str, local_path: Path) -> RawFile:
    return RawFile(
        source_id=source_id,
        name=name,
        fetched_at=datetime(2026, 1, 1),
        local_path=local_path,
    )
```

```python
# new — RawFile from content.sources.base (frozen dataclass, no local_path)
from datetime import timezone
from fireflyframework_agentic.content.sources.base import RawFile

def _make_raw(name: str, source_id: str) -> RawFile:
    return RawFile(
        source_id=source_id,
        name=name,
        mime_type="text/csv",
        size_bytes=0,
        etag="",
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
```

Also update the import at the top:
```python
# remove:
from fireflyframework_agentic.ingestion.domain import (
    ColumnSpec,
    RawFile,
    TableSpec,
    TargetSchema,
)
# add:
from fireflyframework_agentic.content.sources.base import RawFile
from fireflyframework_agentic.ingestion.domain import (
    ColumnSpec,
    TableSpec,
    TargetSchema,
)
```

For every call to `mapper.map(file, schema)` in the test file, add `tmp_path` as the second argument:
```python
# old
records = list(mapper.map(file, schema))
# new
records = list(mapper.map(file, tmp_path / file.name, schema))
```

For every call to `_make_raw(name, source_id, some_path)`, change to `_make_raw(name, source_id)`.

- [ ] **Step 3: Fix test_config.py — remove import of internal SharePointSource**

In `tests/test_ingestion/test_config.py`, remove:
```python
from fireflyframework_agentic.ingestion.adapters.sources import SharePointSource
```

Any test that asserts `isinstance(source, SharePointSource)` should change to:
```python
from fireflyframework_agentic.content.sources.sharepoint import SharePointSource
```

Also: `build_source` now requires real secret values at build time (it calls `secrets.get()` immediately to capture them in the token provider closure). Tests that call `build_source` must set env vars for the secret keys referenced in the config. Update any such test to set `os.environ["T"] = "fake-tenant"` etc. before calling `build_source`, or mock the `SecretsProvider.get` call.

Example updated test setup for `test_build_source_returns_sharepoint`:
```python
import os
from unittest.mock import MagicMock

def test_build_source_returns_sharepoint(tmp_path):
    secrets = MagicMock()
    secrets.get.side_effect = lambda key: {"T": "tenant", "C": "client-id", "S": "secret"}[key]
    section = SourceSection(
        type="sharepoint",
        config={
            "tenant_id_secret": "T",
            "client_id_secret": "C",
            "client_secret_secret": "S",
            "drive_id": "drive-1",
            "cache_dir": str(tmp_path / "cache"),
            "delta_file": str(tmp_path / "delta.json"),
        },
    )
    state = StateSection(cache_dir=tmp_path / "cache", delta_file=tmp_path / "delta.json")
    from fireflyframework_agentic.content.sources.sharepoint import SharePointSource
    source = build_source(section, state, secrets)
    assert isinstance(source, SharePointSource)
```

- [ ] **Step 4: Run ingestion tests**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pytest tests/test_ingestion/ -v 2>&1 | tail -30
```

Expected: all pass (green).

- [ ] **Step 5: Commit**

```bash
REPO=/home/u/signature/fireflyframework-agentic
git -C $REPO add tests/test_ingestion/
git -C $REPO commit -m "test(ingestion): update tests for ContentSource + explicit path parameter"
```

---

## Task 9: Add schema discovery agent

A standalone async function that reads headers and sample rows from an Excel or CSV file and calls Claude (via pydantic-ai) to return a `TargetSchema`. No LLM calls in tests — the agent is tested with a patched `Agent.run`.

**Files:**
- Create: `src/fireflyframework_agentic/ingestion/agents/__init__.py`
- Create: `src/fireflyframework_agentic/ingestion/agents/schema_discovery.py`
- Create: `tests/test_ingestion/test_schema_discovery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingestion/test_schema_discovery.py`:

```python
"""Tests for schema discovery agent (LLM call is patched)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.ingestion.agents.schema_discovery import (
    _read_sample,
    discover_schema,
)
from fireflyframework_agentic.ingestion.domain import ColumnSpec, TableSpec, TargetSchema


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    f = tmp_path / "orders.csv"
    f.write_text("id,customer,amount\n1,Alice,99.5\n2,Bob,12.0\n")
    return f


@pytest.fixture
def xlsx_file(tmp_path: Path) -> Path:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["product_id", "name", "price"])
    ws.append([1, "Widget", 9.99])
    ws.append([2, "Gadget", 19.99])
    wb.save(tmp_path / "products.xlsx")
    return tmp_path / "products.xlsx"


def test_read_sample_csv(csv_file: Path):
    headers, rows = _read_sample(csv_file)
    assert headers == ["id", "customer", "amount"]
    assert rows == [["1", "Alice", "99.5"], ["2", "Bob", "12.0"]]


def test_read_sample_xlsx(xlsx_file: Path):
    headers, rows = _read_sample(xlsx_file)
    assert headers == ["product_id", "name", "price"]
    assert len(rows) == 2
    assert rows[0][1] == "Widget"


def test_read_sample_unsupported_raises(tmp_path: Path):
    f = tmp_path / "data.parquet"
    f.write_bytes(b"PAR1")
    with pytest.raises(ValueError, match="Unsupported file type"):
        _read_sample(f)


async def test_discover_schema_returns_target_schema(csv_file: Path):
    expected = TargetSchema(
        tables=[
            TableSpec(
                name="orders",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="customer", type="string"),
                    ColumnSpec(name="amount", type="float"),
                ],
            )
        ]
    )
    mock_result = AsyncMock()
    mock_result.output = expected

    with patch(
        "fireflyframework_agentic.ingestion.agents.schema_discovery._agent.run",
        new=AsyncMock(return_value=mock_result),
    ):
        result = await discover_schema(csv_file)

    assert result == expected
    assert result.tables[0].name == "orders"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pytest tests/test_ingestion/test_schema_discovery.py -v 2>&1 | tail -15
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` (agent not created yet).

- [ ] **Step 3: Create agents/__init__.py**

```python
# src/fireflyframework_agentic/ingestion/agents/__init__.py
```
(empty file)

- [ ] **Step 4: Create schema_discovery.py**

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Schema discovery agent: infers a TargetSchema from a tabular file using Claude."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from fireflyframework_agentic.ingestion.domain.schema import TargetSchema

_SAMPLE_ROWS = 5

_agent: Agent[None, TargetSchema] = Agent(
    "claude-sonnet-4-6",
    output_type=TargetSchema,
    system_prompt=(
        "You are a data engineer. Given a sample of tabular data, infer a TargetSchema "
        "with appropriate column names, types (string/integer/float/boolean/date/datetime/json), "
        "nullability, and a primary key. Use snake_case for the table name derived from the "
        "file name (without extension). Choose the most specific type that fits the sample values."
    ),
)


def _read_sample(path: Path) -> tuple[list[str], list[list[Any]]]:
    """Read headers and up to _SAMPLE_ROWS sample rows from an Excel or CSV file."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            headers = next(reader, [])
            rows = [row for _, row in zip(range(_SAMPLE_ROWS), reader)]
        return headers, rows
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True)) if ws is not None else []
        wb.close()
        if not all_rows:
            return [], []
        headers = [str(c) if c is not None else "" for c in all_rows[0]]
        rows = [
            [str(c) if c is not None else "" for c in r]
            for r in all_rows[1 : _SAMPLE_ROWS + 1]
        ]
        return headers, rows
    raise ValueError(f"Unsupported file type for schema discovery: {suffix!r}")


async def discover_schema(path: Path) -> TargetSchema:
    """Analyse a tabular file and return an inferred TargetSchema.

    Reads up to _SAMPLE_ROWS rows and calls Claude to infer column types.
    Requires ANTHROPIC_API_KEY in environment.
    """
    headers, rows = _read_sample(path)
    table_name = path.stem.lower().replace(" ", "_").replace("-", "_")
    sample_lines = ", ".join(headers)
    if rows:
        sample_lines += "\nSample rows:\n" + "\n".join(str(r) for r in rows)
    prompt = f"File: {path.name}\nTable name to use: {table_name}\nHeaders and sample:\n{sample_lines}"
    result = await _agent.run(prompt)
    return result.output
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pytest tests/test_ingestion/test_schema_discovery.py -v 2>&1 | tail -15
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
REPO=/home/u/signature/fireflyframework-agentic
git -C $REPO add \
  src/fireflyframework_agentic/ingestion/agents/ \
  tests/test_ingestion/test_schema_discovery.py
git -C $REPO commit -m "feat(ingestion): add schema discovery agent using Claude"
```

---

## Task 10: Add SQLite query tool

A `query_sqlite` function that accepts a SELECT-only SQL statement and returns rows as `list[dict]`. Used by agents to query structured data without going through the vector store.

**Files:**
- Create: `src/fireflyframework_agentic/ingestion/tools/__init__.py`
- Create: `src/fireflyframework_agentic/ingestion/tools/sqlite_query.py`
- Create: `tests/test_ingestion/test_sqlite_query.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingestion/test_sqlite_query.py`:

```python
"""Tests for the SQLite query tool."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.ingestion.tools.sqlite_query import query_sqlite


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
        conn.execute("INSERT INTO products VALUES (1, 'Widget', 9.99)")
        conn.execute("INSERT INTO products VALUES (2, 'Gadget', 19.99)")
        conn.commit()
    return path


def test_select_returns_rows(db_path: str):
    rows = query_sqlite(db_path, "SELECT id, name FROM products ORDER BY id")
    assert rows == [{"id": 1, "name": "Widget"}, {"id": 2, "name": "Gadget"}]


def test_select_with_where(db_path: str):
    rows = query_sqlite(db_path, "SELECT name FROM products WHERE price > 10")
    assert rows == [{"name": "Gadget"}]


def test_non_select_raises(db_path: str):
    with pytest.raises(ValueError, match="Only SELECT"):
        query_sqlite(db_path, "DROP TABLE products")


def test_insert_raises(db_path: str):
    with pytest.raises(ValueError, match="Only SELECT"):
        query_sqlite(db_path, "INSERT INTO products VALUES (3, 'x', 1.0)")


def test_empty_result(db_path: str):
    rows = query_sqlite(db_path, "SELECT * FROM products WHERE id = 999")
    assert rows == []


def test_accepts_path_object(db_path: str):
    rows = query_sqlite(Path(db_path), "SELECT COUNT(*) AS n FROM products")
    assert rows == [{"n": 2}]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pytest tests/test_ingestion/test_sqlite_query.py -v 2>&1 | tail -10
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create tools/__init__.py**

```python
# src/fireflyframework_agentic/ingestion/tools/__init__.py
```
(empty file)

- [ ] **Step 4: Create sqlite_query.py**

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""SQLite query tool for agents: SELECT-only access to structured ingestion data."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

_SELECT_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


def query_sqlite(db_path: str | Path, sql: str) -> list[dict[str, Any]]:
    """Execute a SELECT-only query against a SQLite database.

    Args:
        db_path: Path to the SQLite database file.
        sql: SQL statement to execute. Must start with SELECT.

    Returns:
        List of rows as dicts mapping column name to value.

    Raises:
        ValueError: If sql is not a SELECT statement.
        sqlite3.Error: If the query fails.
    """
    if not _SELECT_RE.match(sql):
        raise ValueError("Only SELECT statements are permitted")
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        return [dict(row) for row in cur.fetchall()]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pytest tests/test_ingestion/test_sqlite_query.py -v 2>&1 | tail -15
```

Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
REPO=/home/u/signature/fireflyframework-agentic
git -C $REPO add \
  src/fireflyframework_agentic/ingestion/tools/ \
  tests/test_ingestion/test_sqlite_query.py
git -C $REPO commit -m "feat(ingestion): add SELECT-only SQLite query tool for agents"
```

---

## Task 11: Full test run, clean-up, and open PR

- [ ] **Step 1: Run full ingestion test suite**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pytest tests/test_ingestion/ -v 2>&1 | tail -40
```

Expected: all tests pass. If any tests in `test_config.py` or `test_domain.py` still reference `local_path` or `DataSourcePort`, fix them before continuing.

- [ ] **Step 2: Run broader test suite to check for regressions**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pytest tests/ -x --ignore=tests/integration --ignore=tests/test_ingestion -q 2>&1 | tail -20
```

Expected: all pass (no regressions in unrelated modules).

- [ ] **Step 3: Check pyright (if configured)**

```bash
cd /home/u/signature/fireflyframework-agentic && \
  source ~/.venvs/signature/bin/activate && \
  python -m pyright src/fireflyframework_agentic/ingestion/ 2>&1 | tail -20
```

Fix any type errors before pushing.

- [ ] **Step 4: Push branch and open PR**

```bash
git -C /home/u/signature/fireflyframework-agentic push -u origin feat/structured-ingestion-integration
gh pr create \
  --repo fireflyframework/fireflyframework-agentic \
  --base main \
  --head feat/structured-ingestion-integration \
  --title "feat(ingestion): structured data ingestion via ContentSource + schema discovery agent" \
  --body "$(cat <<'EOF'
## Summary

- Brings in the hexagonal ingestion module from `feat/ingestion-module`, removing the duplicate SharePoint source adapter
- `IngestionService` now accepts `ContentSource` (from PR #101) instead of a private `DataSourcePort`
- Mapper interface gains an explicit `path: Path` parameter; scripts no longer read from `file.local_path`
- Config factory wires to `content.sources.sharepoint.SharePointSource` via an OAuth2 token-provider closure
- Adds `ingestion/agents/schema_discovery.py`: Claude-based async function that infers a `TargetSchema` from an Excel or CSV file
- Adds `ingestion/tools/sqlite_query.py`: SELECT-only query function for agents to read structured data directly

## Flow

SharePoint Excel/CSV → `ContentSource.list_changed()` → `IngestionService` → `ScriptMapper` → `SQLiteSink` → agent queries via `query_sqlite()`

Schema discovery: `discover_schema(path)` → Claude → `TargetSchema` → feeds into `IngestionService`
EOF
)"
```
