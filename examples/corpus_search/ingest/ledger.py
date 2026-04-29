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

from __future__ import annotations

from datetime import UTC, datetime

from examples.corpus_search.corpus import SqliteCorpus


class IngestLedger:
    """Thin wrapper over the ``ingestions`` table in the corpus SQLite file.

    Statuses: ``success`` | ``failed`` | ``load_failed``. No ``partial`` status —
    the V1 ingest pipeline is linear, so there is no partial state.
    """

    def __init__(self, corpus: SqliteCorpus) -> None:
        self._corpus = corpus

    async def should_skip(self, doc_id: str, content_hash: str) -> bool:
        rows = await self._corpus.query(
            "SELECT status, content_hash FROM ingestions WHERE doc_id = :id",
            {"id": doc_id},
        )
        if not rows:
            return False
        row = rows[0]
        return row["status"] == "success" and row["content_hash"] == content_hash

    async def upsert(
        self,
        doc_id: str,
        source_path: str,
        content_hash: str,
        *,
        status: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        await self._corpus.query(
            """INSERT INTO ingestions
                 (doc_id, source_path, content_hash, status, ingested_at, attempt)
               VALUES (:id, :path, :hash, :status, :now, 1)
               ON CONFLICT(doc_id) DO UPDATE SET
                 source_path  = excluded.source_path,
                 content_hash = excluded.content_hash,
                 status       = excluded.status,
                 ingested_at  = excluded.ingested_at,
                 attempt      = ingestions.attempt + 1""",
            {
                "id": doc_id,
                "path": source_path,
                "hash": content_hash,
                "status": status,
                "now": now,
            },
        )
