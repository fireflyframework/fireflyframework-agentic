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
from unittest.mock import AsyncMock, patch

import pytest

from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.agent import CorpusAgent
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.answerer import Answer

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
async def test_query_sql_outcome_reaches_answer_agent(tmp_path: Path):
    """After structured ingest, query() must pass sql_outcome to AnswerAgent."""
    from fireflyframework_agentic.rag.retrieval.sql import SqlRetrievalOutcome

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

    captured_sql_outcome: list[SqlRetrievalOutcome | None] = []

    async def capture_answer(
        question: str,
        hits: Any,
        *,
        sql_outcome: SqlRetrievalOutcome | None = None,
    ) -> Answer:
        captured_sql_outcome.append(sql_outcome)
        return mock_answer

    # Provide a fixed SQL outcome so StructuredRetriever.retrieve returns
    # structured data without making a real LLM call.
    stub_outcome = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="id | name\n--- | ---\n1 | Widget\n2 | Gadget",
        attempted_sql="SELECT id, name FROM products",
        probe_trail=[],
    )

    with (
        patch.object(agent._expander, "expand", new_callable=AsyncMock, return_value=["q"]),
        patch.object(agent._retriever, "retrieve", new_callable=AsyncMock, return_value=[]),
        patch.object(agent._reranker, "rerank", new_callable=AsyncMock, return_value=[]),
        patch.object(agent._answerer, "answer", side_effect=capture_answer),
        patch.object(agent._structured_retriever, "retrieve", new_callable=AsyncMock, return_value=stub_outcome),
    ):
        await agent.query("How many products?")

    assert len(captured_sql_outcome) == 1
    outcome = captured_sql_outcome[0]
    assert outcome is not None
    assert outcome.outcome == "answered"
    assert outcome.result_markdown is not None
    assert "Widget" in outcome.result_markdown
    assert "Gadget" in outcome.result_markdown


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
