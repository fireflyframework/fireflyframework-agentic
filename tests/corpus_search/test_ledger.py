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

import pytest

from examples.corpus_search.corpus import SqliteCorpus
from examples.corpus_search.ingest.ledger import IngestLedger


@pytest.fixture
async def ledger(tmp_path):
    corpus = SqliteCorpus(tmp_path / "corpus.sqlite")
    await corpus.initialise()
    yield IngestLedger(corpus)
    await corpus.close()


async def test_should_skip_returns_false_for_unknown_doc(ledger: IngestLedger):
    assert await ledger.should_skip("doc-1", "deadbeef") is False


async def test_upsert_records_status_then_skip_when_success_and_hash_matches(ledger: IngestLedger):
    await ledger.upsert("doc-1", "/tmp/x.pdf", "deadbeef", status="success")
    assert await ledger.should_skip("doc-1", "deadbeef") is True


async def test_should_not_skip_when_hash_changes(ledger: IngestLedger):
    await ledger.upsert("doc-1", "/tmp/x.pdf", "deadbeef", status="success")
    assert await ledger.should_skip("doc-1", "different-hash") is False


async def test_failed_status_does_not_skip_even_with_same_hash(ledger: IngestLedger):
    await ledger.upsert("doc-1", "/tmp/x.pdf", "deadbeef", status="failed")
    assert await ledger.should_skip("doc-1", "deadbeef") is False


async def test_load_failed_status_does_not_skip(ledger: IngestLedger):
    await ledger.upsert("doc-1", "/tmp/x.pdf", "deadbeef", status="load_failed")
    assert await ledger.should_skip("doc-1", "deadbeef") is False


async def test_upsert_increments_attempt_on_re_upsert(ledger: IngestLedger):
    await ledger.upsert("doc-1", "/tmp/x.pdf", "h1", status="failed")
    await ledger.upsert("doc-1", "/tmp/x.pdf", "h2", status="success")
    rows = await ledger._corpus.query("SELECT attempt, status, content_hash FROM ingestions WHERE doc_id='doc-1'")
    assert rows[0]["attempt"] == 2
    assert rows[0]["status"] == "success"
    assert rows[0]["content_hash"] == "h2"


async def test_upsert_writes_iso_timestamp(ledger: IngestLedger):
    await ledger.upsert("doc-1", "/tmp/x.pdf", "h", status="success")
    rows = await ledger._corpus.query("SELECT ingested_at FROM ingestions WHERE doc_id='doc-1'")
    # ISO-8601 with timezone, e.g. "2026-04-29T...+00:00"
    ts = rows[0]["ingested_at"]
    assert "T" in ts
    assert len(ts) >= 19
