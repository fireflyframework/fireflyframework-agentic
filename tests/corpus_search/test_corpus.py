from __future__ import annotations

import pytest

from examples.corpus_search.corpus import ChunkHit, SqliteCorpus, StoredChunk


@pytest.fixture
async def corpus(tmp_path):
    c = SqliteCorpus(tmp_path / "corpus.sqlite")
    await c.initialise()
    yield c
    await c.close()


async def test_schema_creates_chunks_and_ingestions(corpus: SqliteCorpus):
    rows = await corpus.query(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = {r["name"] for r in rows}
    assert {"chunks", "ingestions"} <= names


async def test_journal_mode_is_wal(corpus: SqliteCorpus):
    rows = await corpus.query("PRAGMA journal_mode")
    assert rows[0]["journal_mode"].lower() == "wal"


async def test_upsert_chunks_then_bm25_search_returns_hit(corpus: SqliteCorpus):
    chunks = [
        StoredChunk(
            chunk_id="d-0",
            doc_id="d",
            source_path="/tmp/x.md",
            index_in_doc=0,
            content="Sam Altman is the chief executive officer of OpenAI.",
            metadata={"mime_type": "text/markdown"},
        ),
        StoredChunk(
            chunk_id="d-1",
            doc_id="d",
            source_path="/tmp/x.md",
            index_in_doc=1,
            content="The approval workflow goes from start to review to end.",
            metadata={"mime_type": "text/markdown"},
        ),
    ]
    await corpus.upsert_chunks(chunks)

    hits = await corpus.bm25_search("openai", top_k=10)
    assert any(h.chunk_id == "d-0" for h in hits)
    # Stemmer match: "executives" should hit content with "executive"
    hits_stem = await corpus.bm25_search("executives", top_k=10)
    assert any(h.chunk_id == "d-0" for h in hits_stem)


async def test_delete_by_doc_id_removes_chunks_and_fts_rows(corpus: SqliteCorpus):
    chunks = [
        StoredChunk(chunk_id="a-0", doc_id="a", source_path="/p", index_in_doc=0, content="alpha", metadata={}),
        StoredChunk(chunk_id="b-0", doc_id="b", source_path="/p", index_in_doc=0, content="beta", metadata={}),
    ]
    await corpus.upsert_chunks(chunks)
    deleted = await corpus.delete_by_doc_id("a")
    assert deleted == 1
    rows = await corpus.query("SELECT chunk_id FROM chunks ORDER BY chunk_id")
    assert [r["chunk_id"] for r in rows] == ["b-0"]
    fts_rows = await corpus.query("SELECT rowid FROM chunks_fts")
    # FTS triggers should have removed the deleted row's index entry too.
    assert len(fts_rows) == 1


async def test_upsert_chunks_replaces_on_conflict(corpus: SqliteCorpus):
    c1 = StoredChunk(chunk_id="d-0", doc_id="d", source_path="/p", index_in_doc=0, content="first version", metadata={})
    c2 = StoredChunk(chunk_id="d-0", doc_id="d", source_path="/p", index_in_doc=0, content="second version", metadata={})
    await corpus.upsert_chunks([c1])
    await corpus.upsert_chunks([c2])
    rows = await corpus.query("SELECT content FROM chunks WHERE chunk_id='d-0'")
    assert len(rows) == 1
    assert rows[0]["content"] == "second version"


async def test_get_chunks_by_ids(corpus: SqliteCorpus):
    chunks = [
        StoredChunk(chunk_id=f"d-{i}", doc_id="d", source_path="/p", index_in_doc=i,
                    content=f"chunk {i}", metadata={}) for i in range(3)
    ]
    await corpus.upsert_chunks(chunks)
    got = await corpus.get_chunks(["d-0", "d-2"])
    assert {c.chunk_id for c in got} == {"d-0", "d-2"}


async def test_get_chunks_with_empty_list_returns_empty(corpus: SqliteCorpus):
    assert await corpus.get_chunks([]) == []


async def test_bm25_search_no_match_returns_empty(corpus: SqliteCorpus):
    chunks = [
        StoredChunk(chunk_id="d-0", doc_id="d", source_path="/p", index_in_doc=0,
                    content="hello world", metadata={}),
    ]
    await corpus.upsert_chunks(chunks)
    hits = await corpus.bm25_search("totally-unrelated-query", top_k=10)
    assert hits == []
