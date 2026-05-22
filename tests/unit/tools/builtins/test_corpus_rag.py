# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Integration-style unit tests for the corpus_rag MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.exceptions import ToolError
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
async def test_ingest_corpus_structured_dispatches_structured_mode(configured_env: Path, stub_backends: None) -> None:
    """The new MCP tool delegates to CorpusAgent.ingest_one with mode='structured'.

    Schema discovery and the structured pipeline both make real LLM / file
    calls in production; we patch them out and only verify that the tool
    routes correctly and shapes its return value from the IngestionResult.
    """
    from fireflyframework_agentic.rag.ingest.structured_schema import (
        ColumnSpec,
        ColumnType,
        TableSpec,
        TargetSchema,
    )
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_structured

    csv_path = configured_env / "sales.csv"
    csv_path.write_text("id,amount\n1,10.5\n", encoding="utf-8")

    schema = TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, nullable=False, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_, nullable=True, primary_key=False),
                ],
            )
        ]
    )

    with (
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema",
            new=AsyncMock(return_value=schema),
        ),
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(return_value={"sales": {"status": "success", "inserted": 1, "errors": []}}),
        ) as mock_ingest_structured,
    ):
        result = await ingest_corpus_structured.execute(corpus_id="t-struct", path=str(csv_path))

    assert result == {
        "corpus_id": "t-struct",
        "ingested": 1,
        "skipped": 0,
        "failed": 0,
    }
    mock_ingest_structured.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_corpus_structured_folder_iterates(configured_env: Path, stub_backends: None) -> None:
    """Passing a folder path walks every non-hidden file and aggregates counts."""
    from fireflyframework_agentic.rag.ingest.structured_schema import (
        ColumnSpec,
        ColumnType,
        TableSpec,
        TargetSchema,
    )
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_structured

    folder = configured_env / "tabular"
    folder.mkdir()
    (folder / "a.csv").write_text("id,v\n1,2\n", encoding="utf-8")
    (folder / "b.csv").write_text("id,v\n3,4\n", encoding="utf-8")

    schema = TargetSchema(
        tables=[
            TableSpec(
                name="t",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, nullable=False, primary_key=True),
                    ColumnSpec(name="v", type=ColumnType.integer, nullable=True, primary_key=False),
                ],
            )
        ]
    )

    with (
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema",
            new=AsyncMock(return_value=schema),
        ),
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema_for_paths",
            new=AsyncMock(return_value=schema),
        ),
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(return_value={"t": {"status": "success", "inserted": 1, "errors": []}}),
        ),
    ):
        result = await ingest_corpus_structured.execute(corpus_id="t-folder", path=str(folder))

    assert result["corpus_id"] == "t-folder"
    # Folder discovery returns one TableSpec named "t" — neither file matches
    # by stem, so per-file fallback handles each file independently.
    assert result["ingested"] == 2
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_discover_corpus_schema_returns_schema_json(configured_env: Path, stub_backends: None) -> None:
    """discover_corpus_schema runs discovery and returns the TargetSchema as JSON without ingesting."""
    from fireflyframework_agentic.rag.ingest.structured_schema import (
        ColumnSpec,
        ColumnType,
        TableSpec,
        TargetSchema,
    )
    from fireflyframework_agentic.tools.builtins.corpus_rag import discover_corpus_schema

    csv_path = configured_env / "sales.csv"
    csv_path.write_text("id,amount\n1,10.5\n", encoding="utf-8")

    schema = TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_),
                ],
            )
        ]
    )

    with (
        patch(
            "fireflyframework_agentic.rag.agent.discover_schema",
            new=AsyncMock(return_value=schema),
        ),
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(side_effect=AssertionError("ingest must NOT run during discovery")),
        ),
    ):
        result = await discover_corpus_schema.execute(corpus_id="t-disc", path=str(csv_path))

    assert result["corpus_id"] == "t-disc"
    assert result["path"] == str(csv_path)
    assert result["schema"]["tables"][0]["name"] == "sales"
    assert {c["name"] for c in result["schema"]["tables"][0]["columns"]} == {"id", "amount"}


@pytest.mark.asyncio
async def test_discover_corpus_schema_refines_with_corrections(configured_env: Path, stub_backends: None) -> None:
    """Passing previous_schema + corrections threads them into the underlying discover_schema call."""
    from fireflyframework_agentic.rag.ingest.structured_schema import (
        ColumnSpec,
        ColumnType,
        TableSpec,
        TargetSchema,
    )
    from fireflyframework_agentic.tools.builtins.corpus_rag import discover_corpus_schema

    csv_path = configured_env / "sales.csv"
    csv_path.write_text("id,amount\n1,10.5\n", encoding="utf-8")

    refined = TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_, nullable=False),
                ],
            )
        ]
    )

    prior = {
        "tables": [
            {
                "name": "sales",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True, "nullable": True, "foreign_key": None},
                    {"name": "amount", "type": "float", "nullable": True, "primary_key": False, "foreign_key": None},
                ],
            }
        ]
    }

    discover_mock = AsyncMock(return_value=refined)
    with patch("fireflyframework_agentic.rag.agent.discover_schema", new=discover_mock):
        result = await discover_corpus_schema.execute(
            corpus_id="t-refine",
            path=str(csv_path),
            corrections="amount is required, mark it not null",
            previous_schema=prior,
        )

    assert result["schema"]["tables"][0]["columns"][1]["nullable"] is False
    kwargs = discover_mock.await_args.kwargs
    assert kwargs["corrections"] == "amount is required, mark it not null"
    assert kwargs["previous_schema"].tables[0].name == "sales"


@pytest.mark.asyncio
async def test_ingest_corpus_structured_skips_discovery_when_schema_supplied(
    configured_env: Path, stub_backends: None
) -> None:
    """When schema= is passed, discovery is skipped and rows are loaded under the supplied schema."""
    from fireflyframework_agentic.rag.ingest.structured_schema import (
        ColumnSpec,
        ColumnType,
        TableSpec,
        TargetSchema,
    )
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_structured

    csv_path = configured_env / "sales.csv"
    csv_path.write_text("id,amount\n1,10.5\n", encoding="utf-8")

    operator_schema = TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_),
                ],
            )
        ]
    )

    discover_mock = AsyncMock(side_effect=AssertionError("discovery must NOT run when schema is supplied"))
    with (
        patch("fireflyframework_agentic.rag.agent.discover_schema", new=discover_mock),
        patch(
            "fireflyframework_agentic.rag.agent.ingest_structured",
            new=AsyncMock(return_value={"sales": {"status": "success", "inserted": 1, "errors": []}}),
        ) as mock_ingest,
    ):
        result = await ingest_corpus_structured.execute(
            corpus_id="t-with-schema",
            path=str(csv_path),
            schema=operator_schema.model_dump(mode="json"),
        )

    assert result == {
        "corpus_id": "t-with-schema",
        "ingested": 1,
        "skipped": 0,
        "failed": 0,
    }
    discover_mock.assert_not_called()
    # The schema arg passed to ingest_structured is the operator's schema.
    passed_schema = mock_ingest.await_args.args[2]
    assert passed_schema.tables[0].name == "sales"


@pytest.mark.asyncio
async def test_knowledge_search_raises_for_unknown_corpus(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import knowledge_search

    # BaseTool.execute wraps domain exceptions in ToolError; the original
    # CorpusNotFoundError is available as ToolError.__cause__.
    with pytest.raises(ToolError) as exc_info:
        await knowledge_search.execute(corpus_id="never-ingested", question="anything", top_k=3)
    assert isinstance(exc_info.value.__cause__, CorpusNotFoundError)


@pytest.mark.asyncio
async def test_corpus_query_raises_for_unknown_corpus(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_query

    # BaseTool.execute wraps domain exceptions in ToolError; the original
    # CorpusNotFoundError is available as ToolError.__cause__.
    with pytest.raises(ToolError) as exc_info:
        await corpus_query.execute(corpus_id="never-ingested", question="anything", top_k=3)
    assert isinstance(exc_info.value.__cause__, CorpusNotFoundError)


@pytest.mark.asyncio
async def test_list_corpora_empty_when_root_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import list_corpora

    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "does-not-exist"))
    result = await list_corpora.execute()
    assert result["corpora"] == []
    assert result["corpus_root"].endswith("does-not-exist")


@pytest.mark.asyncio
async def test_list_corpora_returns_only_dirs_with_sqlite(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import (
        ingest_corpus_filesystem,
        list_corpora,
    )

    docs = configured_env / "src"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")

    await ingest_corpus_filesystem.execute(corpus_id="bravo", root_path=str(docs))
    await ingest_corpus_filesystem.execute(corpus_id="alpha", root_path=str(docs))

    # A stray directory with no corpus.sqlite must be ignored.
    (configured_env / "corpora" / "stray").mkdir(parents=True)

    result = await list_corpora.execute()
    ids = [c["corpus_id"] for c in result["corpora"]]
    assert ids == ["alpha", "bravo"]
    for entry in result["corpora"]:
        assert entry["size_bytes"] > 0
        assert "T" in entry["modified"]  # ISO 8601 marker


# ---- Tool-description workflow guidance (prompt-contract tests) ---------
#
# These pin the directive language an MCP host's LLM reads when deciding
# which corpus tool to call. The original descriptions buried the
# discover→review→ingest workflow in the middle of a paragraph and Claude
# Desktop's LLM consistently skipped discovery. The descriptions below
# put the workflow up front with imperative voice. These tests fail if
# a future edit strips the directives.


def test_ingest_corpus_filesystem_description_excludes_tabular_files() -> None:
    """The filesystem ingest tool's description must spell out that
    tabular files are not handled here — otherwise an LLM thinks
    "Ingest every file under root_path" covers Excel too, never calls
    ingest_corpus_structured, and the user's spreadsheets silently
    don't get loaded.
    """
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_filesystem

    desc = ingest_corpus_filesystem.description.lower()
    assert "tabular files" in desc, "must spell out which file types are excluded"
    assert "excluded" in desc or "exclude" in desc
    # Must reciprocally point at the right tool so the LLM knows where to go.
    assert "ingest_corpus_structured" in desc


def test_ingest_corpus_filesystem_description_covers_mixed_folders() -> None:
    """When a folder mixes documents and spreadsheets, the LLM must
    call BOTH tools. The description has to say this explicitly.
    """
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_filesystem

    desc = ingest_corpus_filesystem.description.lower()
    assert "both" in desc, "must tell the LLM to call BOTH tools on mixed folders"
    assert "neither alone" in desc or "alone" in desc


def test_discover_corpus_schema_description_requires_user_review() -> None:
    """Discovery must direct the LLM to surface the proposed schema for
    user review before passing it to ingest_corpus_structured. Without
    this, unreviewed schemas reach ingest, units / FKs / types are wrong,
    and the user can't tell until corpus_query gives a confidently-wrong
    answer.
    """
    from fireflyframework_agentic.tools.builtins.corpus_rag import discover_corpus_schema

    desc = discover_corpus_schema.description
    assert "STEP 1" in desc, "must position itself as the first step of a workflow"
    # Imperative voice — softer phrasings ("the caller can review") didn't
    # land for the model.
    assert "MUST present" in desc or "must present" in desc
    assert "review" in desc.lower()
    # Must explicitly call out unit because PR #165 added it and discovery
    # is the only point in the workflow where the user can correct it.
    assert "unit" in desc.lower()


def test_discover_corpus_schema_description_explains_refinement_loop() -> None:
    """The previous_schema / corrections refinement loop is the only way
    a user can iterate on a wrong schema. The description must spell it
    out so the LLM knows to call this tool again on user feedback.
    """
    from fireflyframework_agentic.tools.builtins.corpus_rag import discover_corpus_schema

    desc = discover_corpus_schema.description
    assert "previous_schema" in desc
    assert "corrections" in desc


def test_ingest_corpus_structured_description_requires_schema_arg() -> None:
    """The structured-ingest tool must direct interactive callers to pass
    a user-reviewed schema. Auto-inference still works for scripts, but
    the recommendation in chat / MCP must be discover → review → ingest.
    """
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_structured

    desc = ingest_corpus_structured.description
    assert "STEP 2" in desc, "must position itself as the second step of a workflow"
    assert "ALWAYS" in desc, "should use strong directive language"
    assert "discover_corpus_schema" in desc, "must reciprocally name the step-1 tool"
    # Numbered steps make the flow scannable for the LLM.
    assert "1." in desc and "2." in desc and "3." in desc and "4." in desc


def test_ingest_corpus_structured_description_warns_about_no_schema_fallback() -> None:
    """Auto-inference is the foot-gun. The description must mark it
    clearly as the wrong choice for interactive contexts so the LLM
    doesn't accidentally take that branch.
    """
    from fireflyframework_agentic.tools.builtins.corpus_rag import ingest_corpus_structured

    desc = ingest_corpus_structured.description.lower()
    assert "without a schema" in desc or "without schema" in desc or "without an explicit schema" in desc.lower()
    assert "unreviewed" in desc or "non-interactive" in desc


# ---- list_corpus_schemas / corpus_sql ----------------------------------
#
# These tests cover the read-only structured introspection tools. To exercise
# them without going through the LLM-driven ingest pipeline, the helper seeds
# a real SQLite table on disk and registers a matching TargetSchema via the
# agent's SchemaRegistry. Both tools then run end-to-end against that state.


async def _seed_structured_corpus(
    corpus_id: str,
    *,
    table_name: str,
    columns_sql: str,
    rows: list[tuple[Any, ...]],
    column_specs: list[Any],
) -> Path:
    """Materialise a corpus with one structured table + a registered schema.

    Calls into ``_agent_for`` so the same cached agent the tools use sees the
    table via its own connection. Returns the path to the corpus sqlite file.
    """
    import sqlite3 as _sqlite3

    from fireflyframework_agentic.rag.ingest.structured_schema import TableSpec, TargetSchema
    from fireflyframework_agentic.tools.builtins.corpus_rag import _agent_for, _corpus_root

    agent = await _agent_for(corpus_id)
    await agent._ensure_corpus_ready()
    sqlite_path = _corpus_root() / corpus_id / "corpus.sqlite"
    # Use a separate connection in WAL mode (the agent already opened in WAL)
    # so the writes are visible across connections without a checkpoint.
    conn = _sqlite3.connect(sqlite_path)
    try:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_sql})")
        placeholders = ", ".join(["?"] * len(rows[0])) if rows else ""
        if rows:
            conn.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", rows)
        conn.commit()
    finally:
        conn.close()
    schema = TargetSchema(tables=[TableSpec(name=table_name, columns=column_specs)])
    assert agent._schema_registry is not None
    await agent._schema_registry.save(schema)
    return sqlite_path


@pytest.mark.asyncio
async def test_list_corpus_schemas_raises_for_unknown_corpus(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import list_corpus_schemas

    with pytest.raises(ToolError) as exc_info:
        await list_corpus_schemas.execute(corpus_id="missing")
    assert isinstance(exc_info.value.__cause__, CorpusNotFoundError)


@pytest.mark.asyncio
async def test_list_corpus_schemas_empty_when_no_structured_ingest(configured_env: Path, stub_backends: None) -> None:
    """A corpus with only unstructured documents reports an empty tables list."""
    from fireflyframework_agentic.tools.builtins.corpus_rag import (
        ingest_corpus_filesystem,
        list_corpus_schemas,
    )

    docs = configured_env / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")
    await ingest_corpus_filesystem.execute(corpus_id="empty-struct", root_path=str(docs))

    result = await list_corpus_schemas.execute(corpus_id="empty-struct")
    assert result == {"corpus_id": "empty-struct", "tables": []}


@pytest.mark.asyncio
async def test_list_corpus_schemas_returns_registered_tables(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.rag.ingest.structured_schema import ColumnSpec, ColumnType
    from fireflyframework_agentic.tools.builtins.corpus_rag import list_corpus_schemas

    await _seed_structured_corpus(
        "seeded",
        table_name="sales",
        columns_sql="id INTEGER PRIMARY KEY, amount REAL",
        rows=[(1, 10.5), (2, 20.0)],
        column_specs=[
            ColumnSpec(name="id", type=ColumnType.integer, primary_key=True, nullable=False),
            ColumnSpec(name="amount", type=ColumnType.float_, unit="USD"),
        ],
    )

    result = await list_corpus_schemas.execute(corpus_id="seeded")
    assert result["corpus_id"] == "seeded"
    assert len(result["tables"]) == 1
    table = result["tables"][0]
    assert table["name"] == "sales"
    assert {c["name"] for c in table["columns"]} == {"id", "amount"}
    amount_col = next(c for c in table["columns"] if c["name"] == "amount")
    assert amount_col["unit"] == "USD"


@pytest.mark.asyncio
async def test_corpus_sql_raises_for_unknown_corpus(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_sql

    with pytest.raises(ToolError) as exc_info:
        await corpus_sql.execute(corpus_id="missing", sql="SELECT 1")
    assert isinstance(exc_info.value.__cause__, CorpusNotFoundError)


@pytest.mark.asyncio
async def test_corpus_sql_returns_rows_against_registered_table(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.rag.ingest.structured_schema import ColumnSpec, ColumnType
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_sql

    await _seed_structured_corpus(
        "sql-happy",
        table_name="sales",
        columns_sql="id INTEGER PRIMARY KEY, amount REAL",
        rows=[(1, 10.5), (2, 20.0), (3, 30.0)],
        column_specs=[
            ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
            ColumnSpec(name="amount", type=ColumnType.float_),
        ],
    )

    result = await corpus_sql.execute(
        corpus_id="sql-happy",
        sql="SELECT id, amount FROM sales ORDER BY id",
    )
    assert result["corpus_id"] == "sql-happy"
    assert result["columns"] == ["id", "amount"]
    assert result["rows"] == [
        {"id": 1, "amount": 10.5},
        {"id": 2, "amount": 20.0},
        {"id": 3, "amount": 30.0},
    ]
    assert result["truncated"] is False
    assert result["tables"] == ["sales"]


@pytest.mark.asyncio
async def test_corpus_sql_supports_named_params(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.rag.ingest.structured_schema import ColumnSpec, ColumnType
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_sql

    await _seed_structured_corpus(
        "sql-params",
        table_name="sales",
        columns_sql="id INTEGER, amount REAL",
        rows=[(1, 10.0), (2, 20.0), (3, 30.0)],
        column_specs=[
            ColumnSpec(name="id", type=ColumnType.integer),
            ColumnSpec(name="amount", type=ColumnType.float_),
        ],
    )

    result = await corpus_sql.execute(
        corpus_id="sql-params",
        sql="SELECT id FROM sales WHERE amount >= :threshold ORDER BY id",
        params={"threshold": 20.0},
    )
    assert [r["id"] for r in result["rows"]] == [2, 3]


@pytest.mark.asyncio
async def test_corpus_sql_truncates_at_limit(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.rag.ingest.structured_schema import ColumnSpec, ColumnType
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_sql

    await _seed_structured_corpus(
        "sql-trunc",
        table_name="items",
        columns_sql="id INTEGER",
        rows=[(i,) for i in range(10)],
        column_specs=[ColumnSpec(name="id", type=ColumnType.integer)],
    )

    result = await corpus_sql.execute(
        corpus_id="sql-trunc",
        sql="SELECT id FROM items ORDER BY id",
        limit=3,
    )
    assert len(result["rows"]) == 3
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_corpus_sql_rejects_non_select(configured_env: Path, stub_backends: None) -> None:
    """UPDATE / DELETE / DDL must be rejected at the parser before sqlite sees them."""
    from fireflyframework_agentic.rag.ingest.structured_schema import ColumnSpec, ColumnType
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_sql

    await _seed_structured_corpus(
        "sql-write",
        table_name="sales",
        columns_sql="id INTEGER",
        rows=[(1,)],
        column_specs=[ColumnSpec(name="id", type=ColumnType.integer)],
    )

    for bad_sql in (
        "UPDATE sales SET id = 99",
        "DELETE FROM sales",
        "DROP TABLE sales",
        "INSERT INTO sales VALUES (5)",
    ):
        with pytest.raises(ToolError) as exc_info:
            await corpus_sql.execute(corpus_id="sql-write", sql=bad_sql)
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert "SELECT" in str(exc_info.value.__cause__)


@pytest.mark.asyncio
async def test_corpus_sql_rejects_internal_tables(configured_env: Path, stub_backends: None) -> None:
    """Even read-only, querying internal tables (chunks, _schemas) is rejected."""
    from fireflyframework_agentic.rag.ingest.structured_schema import ColumnSpec, ColumnType
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_sql

    await _seed_structured_corpus(
        "sql-internal",
        table_name="sales",
        columns_sql="id INTEGER",
        rows=[(1,)],
        column_specs=[ColumnSpec(name="id", type=ColumnType.integer)],
    )

    for bad_sql in (
        "SELECT * FROM chunks",
        "SELECT * FROM _schemas",
        "SELECT s.id FROM sales s JOIN chunks c ON c.doc_id = s.id",
    ):
        with pytest.raises(ToolError) as exc_info:
            await corpus_sql.execute(corpus_id="sql-internal", sql=bad_sql)
        assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_corpus_sql_rejects_unknown_table(configured_env: Path, stub_backends: None) -> None:
    from fireflyframework_agentic.rag.ingest.structured_schema import ColumnSpec, ColumnType
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_sql

    await _seed_structured_corpus(
        "sql-unknown",
        table_name="sales",
        columns_sql="id INTEGER",
        rows=[(1,)],
        column_specs=[ColumnSpec(name="id", type=ColumnType.integer)],
    )

    with pytest.raises(ToolError) as exc_info:
        await corpus_sql.execute(corpus_id="sql-unknown", sql="SELECT * FROM customers")
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "customers" in str(exc_info.value.__cause__)


@pytest.mark.asyncio
async def test_corpus_sql_read_only_connection_blocks_writes(configured_env: Path, stub_backends: None) -> None:
    """Belt-and-braces: even if the parser were bypassed, the read-only conn
    refuses writes. We construct a parser-passing-but-mutating statement
    via a CTE that the parser sees as a SELECT (impossible in stock sqlite,
    so this test instead asserts that the connection uri carries mode=ro).
    """
    import sqlite3 as _sqlite3

    from fireflyframework_agentic.tools.builtins.corpus_rag import _execute_select_readonly

    sqlite_path = configured_env / "corpora" / "ro-test" / "corpus.sqlite"
    sqlite_path.parent.mkdir(parents=True)
    conn = _sqlite3.connect(sqlite_path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()

    with pytest.raises(_sqlite3.OperationalError, match="readonly"):
        _execute_select_readonly(sqlite_path, "DELETE FROM t", params=None, limit=10)


@pytest.mark.asyncio
async def test_corpus_query_strategy_fast_keeps_legacy_response_shape(
    configured_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default strategy must not surface reasoning_trace; existing MCP clients
    see the same JSON shape they did before this feature landed.

    The fast path never populates ``Answer.reasoning_trace`` (it stays None),
    so the serialised payload never carries the field. The legacy response
    shape is preserved *by construction*, not by suppression at the MCP
    boundary.
    """
    from fireflyframework_agentic.rag.retrieval.answerer import Answer, CitedSource
    from fireflyframework_agentic.tools.builtins import corpus_rag
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_query

    # Make _assert_corpus_exists a no-op so we don't need to materialise a
    # corpus.sqlite — we're only testing the response-shape contract here.
    async def _noop_assert(corpus_id: str) -> None:
        return None

    monkeypatch.setattr(corpus_rag, "_assert_corpus_exists", _noop_assert)

    class _StubAgent:
        async def query(self, question, *, top_k=5, include_trace=True):
            # Fast path: even when the MCP layer asks for a trace, the agent
            # returns a None trace (fast strategy doesn't build one).
            return Answer(
                text="ok",
                citations=["c1"],
                cited_sources=[CitedSource(chunk_id="c1", source_path="/x", snippet="hi")],
                reasoning_trace=None,
            )

    monkeypatch.setitem(corpus_rag._AGENT_CACHE, ("t1", "fast"), _StubAgent())
    out = await corpus_query.execute(corpus_id="t1", question="?")
    assert "reasoning_trace" not in out, f"fast path must never surface reasoning_trace in payload; got: {out}"
    assert out["cited_sources"][0]["chunk_id"] == "c1"


@pytest.mark.asyncio
async def test_corpus_query_strategy_reasoning_with_trace(
    configured_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When strategy='reasoning' and include_trace=true, the response carries
    a serialised reasoning_trace matching the Answer's typed trace.
    """
    from fireflyframework_agentic.rag.retrieval.answerer import Answer
    from fireflyframework_agentic.reasoning.trace import ActionStep, ReasoningTrace
    from fireflyframework_agentic.tools.builtins import corpus_rag
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_query

    async def _noop_assert(corpus_id: str) -> None:
        return None

    monkeypatch.setattr(corpus_rag, "_assert_corpus_exists", _noop_assert)

    trace = ReasoningTrace(pattern_name="reasoning_answerer")
    trace.add_step(ActionStep(tool_name="knowledge_search", tool_args={"query": "x"}))

    class _StubAgent:
        async def query(self, question, *, top_k=5, include_trace=True):
            assert include_trace is True, "reasoning + include_trace should propagate"
            return Answer(text="ok", citations=[], cited_sources=[], reasoning_trace=trace)

    monkeypatch.setitem(corpus_rag._AGENT_CACHE, ("t1", "reasoning"), _StubAgent())
    out = await corpus_query.execute(corpus_id="t1", question="?", strategy="reasoning", include_trace=True)
    assert "reasoning_trace" in out
    assert out["reasoning_trace"]["pattern_name"] == "reasoning_answerer"
    assert out["reasoning_trace"]["steps"][0]["tool_name"] == "knowledge_search"


@pytest.mark.asyncio
async def test_corpus_query_reasoning_omits_trace_by_default(
    configured_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """include_trace defaults to False at the MCP boundary. A caller that
    asks for the reasoning strategy without explicitly opting in must NOT
    receive the trace — it can be tens of KB and most callers don't read
    it. Opt-in is verified by ``test_corpus_query_strategy_reasoning_with_trace``.
    """
    from fireflyframework_agentic.rag.retrieval.answerer import Answer
    from fireflyframework_agentic.reasoning.trace import ActionStep, ReasoningTrace
    from fireflyframework_agentic.tools.builtins import corpus_rag
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_query

    async def _noop_assert(corpus_id: str) -> None:
        return None

    monkeypatch.setattr(corpus_rag, "_assert_corpus_exists", _noop_assert)

    trace = ReasoningTrace(pattern_name="reasoning_answerer")
    trace.add_step(ActionStep(tool_name="sql_query", tool_args={"question": "x"}))

    class _StubAgent:
        async def query(self, question, *, top_k=5, include_trace=False):
            assert include_trace is False, "include_trace must default to False on the reasoning path — opt-in only"
            return Answer(text="ok", citations=[], cited_sources=[], reasoning_trace=None)

    monkeypatch.setitem(corpus_rag._AGENT_CACHE, ("t1", "reasoning"), _StubAgent())
    # NOTE: no include_trace= kwarg here — relies on the default.
    out = await corpus_query.execute(corpus_id="t1", question="?", strategy="reasoning")
    assert "reasoning_trace" not in out


@pytest.mark.asyncio
async def test_corpus_query_include_trace_false_opts_out(configured_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """include_trace=False is the explicit opt-out for smaller payloads,
    even on the reasoning path. The trace exists in the Answer but the
    MCP layer doesn't serialise it.
    """
    from fireflyframework_agentic.rag.retrieval.answerer import Answer
    from fireflyframework_agentic.reasoning.trace import ActionStep, ReasoningTrace
    from fireflyframework_agentic.tools.builtins import corpus_rag
    from fireflyframework_agentic.tools.builtins.corpus_rag import corpus_query

    async def _noop_assert(corpus_id: str) -> None:
        return None

    monkeypatch.setattr(corpus_rag, "_assert_corpus_exists", _noop_assert)

    trace = ReasoningTrace(pattern_name="reasoning_answerer")
    trace.add_step(ActionStep(tool_name="sql_query", tool_args={"question": "x"}))

    class _StubAgent:
        async def query(self, question, *, top_k=5, include_trace=True):
            # Agent receives include_trace=False explicitly; returns None trace.
            assert include_trace is False
            return Answer(text="ok", citations=[], cited_sources=[], reasoning_trace=None)

    monkeypatch.setitem(corpus_rag._AGENT_CACHE, ("t1", "reasoning"), _StubAgent())
    out = await corpus_query.execute(corpus_id="t1", question="?", strategy="reasoning", include_trace=False)
    assert "reasoning_trace" not in out


@pytest.mark.asyncio
async def test_corpus_query_strategy_cache_isolation(configured_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fast and reasoning agents for the same corpus must not share the cache
    slot — otherwise switching strategies in one process tears down the
    other's lazily-constructed retrieval components.
    """
    # Resolve fast and reasoning for the same corpus_id and assert two distinct
    # CorpusAgent instances came out. Stub the embedder/vector_store factories
    # so no network is touched.
    from fireflyframework_agentic.rag import agent as agent_mod
    from fireflyframework_agentic.tools.builtins import corpus_rag

    monkeypatch.setattr(agent_mod.CorpusAgent, "_build_embedder", lambda self, m: _StubEmbedder())
    monkeypatch.setattr(agent_mod.CorpusAgent, "_build_vector_store", lambda self: _StubVectorStore())

    a_fast = await corpus_rag._agent_for("t1", strategy="fast")
    a_reasoning = await corpus_rag._agent_for("t1", strategy="reasoning")
    assert a_fast is not a_reasoning
    # Idempotent: second resolve returns the same instance.
    assert await corpus_rag._agent_for("t1", strategy="fast") is a_fast
    assert await corpus_rag._agent_for("t1", strategy="reasoning") is a_reasoning
