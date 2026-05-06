from unittest.mock import AsyncMock, MagicMock

import pytest

from fireflyframework_agentic.rag.ingest.structured_registry import SchemaRegistry
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)


def _make_corpus(rows=None):
    corpus = MagicMock()
    corpus.query = AsyncMock(return_value=rows or [])
    return corpus


def _make_schema(name: str = "orders") -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name=name,
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="total", type=ColumnType.float_),
                ],
            )
        ]
    )


@pytest.mark.asyncio
async def test_initialise_creates_table():
    corpus = _make_corpus()
    registry = SchemaRegistry(corpus)
    await registry.initialise()
    corpus.query.assert_called_once()
    sql = corpus.query.call_args[0][0]
    assert "_schemas" in sql
    assert "CREATE TABLE" in sql


@pytest.mark.asyncio
async def test_save_inserts_json():
    corpus = _make_corpus()
    registry = SchemaRegistry(corpus)
    schema = _make_schema()
    await registry.save(schema)
    corpus.query.assert_called_once()
    args = corpus.query.call_args[0]
    assert "INSERT" in args[0]
    assert "orders" in args[1]["name"]


@pytest.mark.asyncio
async def test_list_schemas_empty():
    corpus = _make_corpus(rows=[])
    registry = SchemaRegistry(corpus)
    result = await registry.list_schemas()
    assert result == []


@pytest.mark.asyncio
async def test_list_schemas_returns_parsed():
    schema = _make_schema("customers")
    corpus = _make_corpus(rows=[{"schema_json": schema.model_dump_json()}])
    registry = SchemaRegistry(corpus)
    result = await registry.list_schemas()
    assert len(result) == 1
    assert result[0].tables[0].name == "customers"
