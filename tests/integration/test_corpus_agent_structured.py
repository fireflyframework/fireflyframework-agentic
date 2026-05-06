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

"""Integration test: ingest CSV → query → answer uses structured SQL context.

LLM calls (discover_schema, text-to-SQL, answer) are mocked so the test runs
in the standard PR gate without API keys. What is exercised for real:

- CorpusAgent lifecycle (init, _ensure_corpus_ready, _ensure_query_ready)
- SchemaRegistry.save() + list_schemas() against a real SQLite file
- ingest_structured() writing rows into corpus.sqlite
- StructuredRetriever._execute() querying those rows via SQL
- asyncio.gather parallel path in query()
- sql_context propagation through to AnswerAgent.answer()
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from examples.corpus_search.agent import CorpusAgent
from examples.corpus_search.retrieval.answerer import Answer
from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)

# ---------------------------------------------------------------------------
# Stubs (same pattern as test_agent_structured.py)
# ---------------------------------------------------------------------------


class _StubEmbedder:
    async def embed(self, texts: list[str], **_kwargs: Any) -> Any:
        return EmbeddingResult(
            embeddings=[[0.0] * 4 for _ in texts],
            model="stub",
            usage=None,
            dimensions=4,
        )

    async def embed_one(self, _text: str, **_kwargs: Any) -> list[float]:
        return [0.0] * 4


class _StubVectorStore:
    def __init__(self) -> None:
        self.docs: dict[str, Any] = {}

    async def upsert(self, documents: Sequence[Any], _namespace: str = "default") -> None:
        for d in documents:
            self.docs[d.id] = d

    async def delete(self, ids: Sequence[str], _namespace: str = "default") -> None:
        for i in ids:
            self.docs.pop(i, None)


def _make_agent(tmp_path: Path) -> CorpusAgent:
    return CorpusAgent(
        root=tmp_path / "corpus",
        embed_model="openai:text-embedding-3-small",
        embed_dimension=4,
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-haiku-4-5-20251001",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        _embedder=_StubEmbedder(),
        _vector_store=_StubVectorStore(),
    )


def _make_csv(tmp_path: Path) -> Path:
    p = tmp_path / "products.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "price"])
        writer.writerow(["1", "Widget", "9.99"])
        writer.writerow(["2", "Gadget", "19.99"])
    return p


def _make_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="products",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                    ColumnSpec(name="name", type=ColumnType.string),
                    ColumnSpec(name="price", type=ColumnType.float_),
                ],
            )
        ]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_ingest_writes_rows_to_sqlite(tmp_path: Path):
    """ingest_one(mode='structured') must persist rows into corpus.sqlite."""
    agent = _make_agent(tmp_path)
    csv_path = _make_csv(tmp_path)

    with patch(
        "fireflyframework_agentic.rag.agent.discover_schema",
        new_callable=AsyncMock,
        return_value=_make_schema(),
    ):
        result = await agent.ingest_one(csv_path, mode="structured")

    assert result.status == "success"
    db_path = tmp_path / "corpus" / "corpus.sqlite"
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, name FROM products ORDER BY id").fetchall()
    conn.close()
    assert rows == [(1, "Widget"), (2, "Gadget")]


@pytest.mark.asyncio
async def test_query_sql_context_reaches_answer_agent(tmp_path: Path):
    """After structured ingest, query() must pass sql_context to AnswerAgent."""
    agent = _make_agent(tmp_path)
    csv_path = _make_csv(tmp_path)
    schema = _make_schema()

    # Ingest the CSV so SchemaRegistry has a schema and products table exists.
    with patch(
        "fireflyframework_agentic.rag.agent.discover_schema",
        new_callable=AsyncMock,
        return_value=schema,
    ):
        await agent.ingest_one(csv_path, mode="structured")

    # Prepare query-stack mocks.
    await agent._ensure_query_ready()
    mock_answer = Answer(text="2 products", citations=[], cited_sources=[])
    sql_agent_result = MagicMock()
    sql_agent_result.output.sql = "SELECT id, name FROM products"

    captured_sql_context: list[str | None] = []

    async def capture_answer(
        question: str,
        hits: Any,
        *,
        sql_context: str | None = None,
    ) -> Answer:
        captured_sql_context.append(sql_context)
        return mock_answer

    with (
        patch.object(agent._expander, "expand", new_callable=AsyncMock, return_value=["q"]),
        patch.object(agent._retriever, "retrieve", new_callable=AsyncMock, return_value=[]),
        patch.object(agent._reranker, "rerank", new_callable=AsyncMock, return_value=[]),
        patch.object(agent._answerer, "answer", side_effect=capture_answer),
        patch("fireflyframework_agentic.rag.retrieval.sql._sql_agent") as mock_sql_agent,
    ):
        mock_sql_agent.run = AsyncMock(return_value=sql_agent_result)
        await agent.query("How many products?")

    assert len(captured_sql_context) == 1
    sql_ctx = captured_sql_context[0]
    assert sql_ctx is not None
    assert "Widget" in sql_ctx
    assert "Gadget" in sql_ctx


@pytest.mark.asyncio
async def test_second_ingest_is_skipped_by_ledger(tmp_path: Path):
    """The ledger must dedup: re-ingesting the same file returns 'skipped'."""
    agent = _make_agent(tmp_path)
    csv_path = _make_csv(tmp_path)

    with patch(
        "fireflyframework_agentic.rag.agent.discover_schema",
        new_callable=AsyncMock,
        return_value=_make_schema(),
    ) as mock_discover:
        first = await agent.ingest_one(csv_path, mode="structured")
        second = await agent.ingest_one(csv_path, mode="structured")

    assert first.status == "success"
    assert second.status == "skipped"
    # discover_schema must only be called on the first ingest.
    assert mock_discover.call_count == 1
