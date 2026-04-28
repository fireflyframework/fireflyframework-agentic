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


from fireflyframework_agentic.graphstores import Node


async def test_upsert_nodes_writes_rows_and_fts(store: SqliteGraphStore):
    nodes = [
        Node(
            label="Person",
            key="sam-altman",
            properties={"name": "Sam Altman", "aliases": ["Sam", "S. Altman"], "description": "CEO of OpenAI"},
            source_doc_id="doc-1",
            extractor_name="person",
            chunk_ids=["c0", "c1"],
        ),
    ]
    await store.upsert_nodes(nodes)

    rows = await store.query("SELECT * FROM nodes WHERE source_doc_id='doc-1'")
    assert len(rows) == 1
    assert rows[0]["label"] == "Person"
    assert rows[0]["key"] == "sam-altman"
    import json
    props = json.loads(rows[0]["properties"])
    assert props["name"] == "Sam Altman"
    assert json.loads(rows[0]["chunk_ids"]) == ["c0", "c1"]

    junction = await store.query("SELECT * FROM node_chunks WHERE source_doc_id='doc-1'")
    assert {r["chunk_id"] for r in junction} == {"c0", "c1"}

    fts = await store.query(
        "SELECT key, text FROM nodes_fts WHERE nodes_fts MATCH :q",
        {"q": "altman"},
    )
    assert len(fts) >= 1
    assert "altman" in fts[0]["text"].lower()


async def test_upsert_nodes_replaces_on_conflict(store: SqliteGraphStore):
    n1 = Node(label="Person", key="a", properties={"v": 1}, source_doc_id="d", extractor_name="x", chunk_ids=["c1"])
    n2 = Node(label="Person", key="a", properties={"v": 2}, source_doc_id="d", extractor_name="x", chunk_ids=["c2"])
    await store.upsert_nodes([n1])
    await store.upsert_nodes([n2])

    rows = await store.query("SELECT * FROM nodes WHERE source_doc_id='d'")
    assert len(rows) == 1
    import json
    assert json.loads(rows[0]["properties"]) == {"v": 2}
    assert json.loads(rows[0]["chunk_ids"]) == ["c2"]

    junction = await store.query("SELECT chunk_id FROM node_chunks WHERE source_doc_id='d'")
    assert {r["chunk_id"] for r in junction} == {"c2"}


from fireflyframework_agentic.graphstores import Edge


async def test_upsert_edges_writes_rows_and_fts(store: SqliteGraphStore):
    edges = [
        Edge(
            label="WORKS_AT",
            source_label="Person",
            source_key="sam-altman",
            target_label="Organization",
            target_key="openai",
            properties={"role": "Chief Executive Officer", "start": "2019"},
            source_doc_id="doc-1",
            extractor_name="person",
        ),
    ]
    await store.upsert_edges(edges)
    rows = await store.query("SELECT * FROM edges WHERE source_doc_id='doc-1'")
    assert len(rows) == 1
    assert rows[0]["label"] == "WORKS_AT"
    fts = await store.query(
        "SELECT * FROM edges_fts WHERE edges_fts MATCH :q",
        {"q": '"chief executive"'},
    )
    assert len(fts) == 1


async def test_delete_by_doc_id_cascades_through_all_tables(store: SqliteGraphStore):
    n1 = Node(label="Person", key="a", properties={}, source_doc_id="doc-1", extractor_name="x", chunk_ids=["c0"])
    n2 = Node(label="Person", key="b", properties={}, source_doc_id="doc-2", extractor_name="x", chunk_ids=["c1"])
    e1 = Edge(label="X", source_label="Person", source_key="a", target_label="Person", target_key="b",
              properties={}, source_doc_id="doc-1", extractor_name="x")
    e2 = Edge(label="X", source_label="Person", source_key="b", target_label="Person", target_key="a",
              properties={}, source_doc_id="doc-2", extractor_name="x")
    await store.upsert_nodes([n1, n2])
    await store.upsert_edges([e1, e2])

    deleted = await store.delete_by_doc_id("doc-1")
    assert deleted >= 2

    nodes_left = await store.query("SELECT source_doc_id FROM nodes")
    assert {r["source_doc_id"] for r in nodes_left} == {"doc-2"}
    edges_left = await store.query("SELECT source_doc_id FROM edges")
    assert {r["source_doc_id"] for r in edges_left} == {"doc-2"}
    junction_left = await store.query("SELECT source_doc_id FROM node_chunks")
    assert {r["source_doc_id"] for r in junction_left} == {"doc-2"}
    fts_nodes = await store.query("SELECT source_doc_id FROM nodes_fts")
    assert {r["source_doc_id"] for r in fts_nodes} == {"doc-2"}
    fts_edges = await store.query("SELECT source_doc_id FROM edges_fts")
    assert {r["source_doc_id"] for r in fts_edges} == {"doc-2"}
