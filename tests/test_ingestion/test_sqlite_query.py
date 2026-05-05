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
