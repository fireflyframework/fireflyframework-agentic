# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tests for the ``find_similar`` op + ``unaccent_lower`` UDF in the SQL retriever."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.sql import (
    _build_inspect_tool,
    _connect,
    _LoopContext,
    _unaccent_lower,
)


def _employees_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="employees",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                    ColumnSpec(name="name", type=ColumnType.string),
                    ColumnSpec(name="manager_id", type=ColumnType.integer),
                ],
            )
        ]
    )


def _employees_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE employees (id INTEGER, name TEXT, manager_id INTEGER)")
    conn.executemany(
        "INSERT INTO employees VALUES (?,?,?)",
        [
            (1, "Francisco Javier Álvarez Fernández Aragón", 99),
            (2, "Javier Álvarez García", 99),
            (3, "María Álvarez", 50),
            (4, "Bob Tan", 50),
            (5, "Alicia Pérez", 50),
        ],
    )
    conn.commit()
    conn.close()
    return db


# ---------- unaccent_lower UDF + helper -----------------------------------


def test_unaccent_lower_strips_accents_and_lowercases():
    assert _unaccent_lower("Álvarez") == "alvarez"
    assert _unaccent_lower("FRANCISCO JAVIER") == "francisco javier"
    assert _unaccent_lower("Niño") == "nino"
    assert _unaccent_lower("") == ""
    assert _unaccent_lower(None) is None


def test_unaccent_lower_registered_on_connection(tmp_path: Path):
    db = _employees_db(tmp_path)
    with _connect(db) as conn:
        row = conn.execute("SELECT unaccent_lower(name) FROM employees WHERE id=1").fetchone()
    assert row[0] == "francisco javier alvarez fernandez aragon"


def test_unaccent_lower_enables_like_match_through_diacritics(tmp_path: Path):
    """The whole point: 'alvarez' must match 'Álvarez' under unaccent_lower."""
    db = _employees_db(tmp_path)
    with _connect(db) as conn:
        rows = conn.execute(
            "SELECT name FROM employees WHERE unaccent_lower(name) LIKE ?",
            ("%alvarez%",),
        ).fetchall()
    names = {r[0] for r in rows}
    assert "Francisco Javier Álvarez Fernández Aragón" in names
    assert "Javier Álvarez García" in names
    assert "María Álvarez" in names
    assert "Bob Tan" not in names


# ---------- inspect_table find_similar ------------------------------------


@pytest.mark.asyncio
async def test_find_similar_and_combinator_finds_full_name(tmp_path: Path):
    db = _employees_db(tmp_path)
    ctx = _LoopContext(db_path=db, schemas=[_employees_schema()])
    inspect = _build_inspect_tool(ctx)

    result = await inspect("employees", "name", "find_similar", value="Javier Alvarez")
    # Both rows contain BOTH 'javier' AND 'alvarez' (accent-folded):
    #   - Francisco Javier Álvarez Fernández Aragón
    #   - Javier Álvarez García
    # 'María Álvarez' has only 'alvarez', so the AND-of-LIKEs drops it.
    assert "Francisco Javier Álvarez Fernández Aragón" in result
    assert "Javier Álvarez García" in result
    assert "María Álvarez" not in result

    # The probe record was logged with op='find_similar'.
    assert any(p.op == "find_similar" for p in ctx.probe_trail), ctx.probe_trail


@pytest.mark.asyncio
async def test_find_similar_falls_back_to_or_when_and_yields_nothing(tmp_path: Path):
    """If no row contains every token, fall back to OR to surface near-matches."""
    db = _employees_db(tmp_path)
    ctx = _LoopContext(db_path=db, schemas=[_employees_schema()])
    inspect = _build_inspect_tool(ctx)

    # 'Bob Alvarez' — no employee has both tokens, but two contain 'alvarez'
    # and one contains 'bob'. OR fallback should return all three.
    result = await inspect("employees", "name", "find_similar", value="Bob Alvarez")
    assert "Bob Tan" in result
    assert "Álvarez" in result  # at least one of the Álvarez rows


@pytest.mark.asyncio
async def test_find_similar_handles_single_token(tmp_path: Path):
    db = _employees_db(tmp_path)
    ctx = _LoopContext(db_path=db, schemas=[_employees_schema()])
    inspect = _build_inspect_tool(ctx)

    result = await inspect("employees", "name", "find_similar", value="alvarez")
    assert "Francisco Javier Álvarez Fernández Aragón" in result
    assert "Bob Tan" not in result


@pytest.mark.asyncio
async def test_find_similar_returns_no_rows_when_truly_absent(tmp_path: Path):
    db = _employees_db(tmp_path)
    ctx = _LoopContext(db_path=db, schemas=[_employees_schema()])
    inspect = _build_inspect_tool(ctx)

    result = await inspect("employees", "name", "find_similar", value="Nakamura")
    assert result == "(no rows)"


@pytest.mark.asyncio
async def test_find_similar_rejects_empty_value(tmp_path: Path):
    from pydantic_ai.exceptions import ModelRetry

    db = _employees_db(tmp_path)
    ctx = _LoopContext(db_path=db, schemas=[_employees_schema()])
    inspect = _build_inspect_tool(ctx)

    with pytest.raises(ModelRetry, match="non-empty 'value'"):
        await inspect("employees", "name", "find_similar", value="")
    with pytest.raises(ModelRetry, match="non-empty 'value'"):
        await inspect("employees", "name", "find_similar", value="   ")
    with pytest.raises(ModelRetry, match="non-empty 'value'"):
        await inspect("employees", "name", "find_similar", value=None)


@pytest.mark.asyncio
async def test_find_similar_is_parametric_against_injection(tmp_path: Path):
    """value goes through parameter binding — % and ' are inert."""
    db = _employees_db(tmp_path)
    ctx = _LoopContext(db_path=db, schemas=[_employees_schema()])
    inspect = _build_inspect_tool(ctx)

    # If the value were string-interpolated, "'); DROP TABLE..." would break
    # something. Through parameters it's just a literal string the LIKE
    # never matches.
    result = await inspect("employees", "name", "find_similar", value="'); DROP TABLE employees; --")
    assert result == "(no rows)"
    # Table still exists.
    with _connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    assert count == 5
