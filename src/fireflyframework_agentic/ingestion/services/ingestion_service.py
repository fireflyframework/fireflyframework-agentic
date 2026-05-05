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
