# Copyright 2026 Firefly Software Foundation
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

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.sql import StructuredRetriever, _build_schema_context, _execute


def _schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="products",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                    ColumnSpec(name="name", type=ColumnType.string),
                ],
            )
        ]
    )


def _populated_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE products (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO products VALUES (1, 'Widget')")
    conn.execute("INSERT INTO products VALUES (2, 'Gadget')")
    conn.commit()
    conn.close()
    return db


@pytest.mark.asyncio
async def test_retrieve_returns_none_for_empty_schemas(tmp_path: Path):
    retriever = StructuredRetriever(tmp_path / "corpus.sqlite")
    result = await retriever.retrieve("How many products?", schemas=[])
    assert result is None


@pytest.mark.asyncio
async def test_retrieve_returns_markdown_table(tmp_path: Path):
    db = _populated_db(tmp_path)
    retriever = StructuredRetriever(db)
    mock_result = MagicMock()
    mock_result.output.sql = "SELECT id, name FROM products"
    with patch.object(retriever, "_sql_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        result = await retriever.retrieve("List all products", schemas=[_schema()])
    assert result is not None
    assert "Widget" in result
    assert "Gadget" in result


@pytest.mark.asyncio
async def test_retrieve_rejects_non_select_sql(tmp_path: Path):
    db = _populated_db(tmp_path)
    retriever = StructuredRetriever(db)
    mock_result = MagicMock()
    mock_result.output.sql = "DROP TABLE products"
    with patch.object(retriever, "_sql_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        result = await retriever.retrieve("drop table", schemas=[_schema()])
    assert result is None


@pytest.mark.asyncio
async def test_retrieve_returns_none_on_sql_error(tmp_path: Path):
    retriever = StructuredRetriever(tmp_path / "corpus.sqlite")  # empty DB
    mock_result = MagicMock()
    mock_result.output.sql = "SELECT * FROM nonexistent_table"
    with patch.object(retriever, "_sql_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        result = await retriever.retrieve("something", schemas=[_schema()])
    assert result is None


def test_build_schema_context():
    ctx = _build_schema_context([_schema()])
    assert "products" in ctx
    assert "id" in ctx
    assert "name" in ctx


def test_execute_returns_none_for_empty_result(tmp_path: Path):
    db = _populated_db(tmp_path)
    result = _execute(db, "SELECT * FROM products WHERE 1=0")
    assert result is None
