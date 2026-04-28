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

from fireflyframework_agentic.graphstores.sqlite import SqliteGraphStore


@pytest.fixture
async def store(tmp_path):
    s = SqliteGraphStore(tmp_path / "graph.sqlite")
    await s.initialise()
    yield s
    await s.close()


async def test_schema_creates_expected_tables(store: SqliteGraphStore):
    rows = await store.query(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name"
    )
    names = {r["name"] for r in rows}
    # Real tables
    for table in {"nodes", "edges", "ingestions", "node_chunks"}:
        assert table in names, f"missing table: {table}"
    # FTS virtual tables also create real shadow tables — at minimum check the parents exist
    assert "nodes_fts" in names or any("nodes_fts" in n for n in names)
    assert "edges_fts" in names or any("edges_fts" in n for n in names)
    # Indexes
    expected_indexes = {
        "idx_nodes_doc",
        "idx_nodes_label",
        "idx_nodes_label_key",
        "idx_edges_doc",
        "idx_edges_endpoints",
        "idx_edges_endpoints_reverse",
        "idx_node_chunks_node",
    }
    assert expected_indexes <= names


async def test_journal_mode_is_wal(store: SqliteGraphStore):
    rows = await store.query("PRAGMA journal_mode")
    assert rows[0]["journal_mode"].lower() == "wal"
